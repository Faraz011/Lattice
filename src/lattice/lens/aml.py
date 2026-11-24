"""The AML account check: features from an account's transaction neighbourhood, and its network.

For one account at one moment, `account_features` reads the transfers seen so far and returns
14 numbers (`INPUTS`). Some are about the account alone (how much came in, how fast it went
out); the rest are read from the graph around it (how long a forwarding chain it sits on,
whether money comes back to a sender, how many accounts share its devices). The network picks
one of five verdicts (`OUTPUTS`).

Training data comes from synthetic worlds with planted laundering (`lattice.datagen`): an account
is labelled with its pattern's family when it is a working member of a planted case (at least two
of the case's transfers touch it), and clear otherwise, decoys included.
"""

import bisect
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from lattice.datagen.builder import REPORTING_THRESHOLD
from lattice.datagen.generator import World
from lattice.graph.loader import GraphBatch
from lattice.lens.mlp import Feature

WINDOW = timedelta(days=30)
FORWARD_WITHIN = timedelta(hours=48)
NEW_ACCOUNT = timedelta(days=30)
MAX_DEPTH = 6

INPUTS = [
    Feature("in_count", "many inflows", "Transfers received in the last 30 days.", "few inflows"),
    Feature("out_count", "many outflows", "Transfers sent in the last 30 days.", "few outflows"),
    Feature("in_amount", "large inflows", "Total received, on a log scale.", "small inflows"),
    Feature("forward_ratio", "passes money on", "Share of what came in that went out within 48 h.",
            "keeps the money"),
    Feature("fast_forward", "forwards within a day",
            "Share of inflows forwarded, mostly intact, within 24 h.", "holds funds"),
    Feature("near_threshold", "deposits under the limit",
            "Inflows just under the 10,000 reporting threshold.", "no near-limit deposits"),
    Feature("senders", "many senders", "Distinct accounts that sent money.", "few senders"),
    Feature("receivers", "many receivers", "Distinct accounts that received money.",
            "few receivers"),
    Feature("new_account", "new account", "Opened recently (1 for days old, 0 for a year).",
            "long-standing account"),
    Feature("chain_depth", "on a long forwarding chain",
            "Hops in the longest chain of mostly-intact forwards through this account (graph).",
            "not on a chain"),
    Feature("cycle", "money returns to a sender",
            "Within 4 hops, money from this account reaches one of its senders (graph).",
            "no cycle"),
    Feature("shared_device", "shares devices", "Other accounts seen on this account's devices.",
            "own devices"),
    Feature("new_counterparties", "trades with new accounts",
            "Share of counterparties opened in the last 30 days (graph).",
            "established counterparties"),
    Feature("to_exit", "sends to exchange or mixer", "Sent money to an exchange or a mixer.",
            "no exits"),
]

OUTPUTS = [
    Feature("clear", "clear"),
    Feature("layering", "layering", "Money walked through a chain of accounts."),
    Feature("structuring", "structuring", "Deposits split to stay under the limit."),
    Feature("round_trip", "round trip", "Money sent out comes back to where it started."),
    Feature("device_ring", "device ring", "Several accounts run from the same devices."),
]

FAMILY = {
    "peeling_chain": "layering", "rapid_layering": "layering", "parallel_mules": "layering",
    "exit_via_mixer": "layering", "fan_in_structuring": "structuring",
    "fan_out": "structuring", "round_trip": "round_trip", "shared_device": "device_ring",
}
CLASS = {f.id: i for i, f in enumerate(OUTPUTS)}


@dataclass(frozen=True)
class Tx:
    id: str
    src: str
    dst: str
    amount: float
    ts: datetime


@dataclass
class Ledger:
    """Transfers indexed by account and time, so features can be read as of any moment."""

    kinds: dict[str, str]
    created: dict[str, datetime | None]
    devices: dict[str, set[str]]  # account -> other accounts sharing a device
    inflows: dict[str, list[Tx]] = field(default_factory=lambda: defaultdict(list))
    outflows: dict[str, list[Tx]] = field(default_factory=lambda: defaultdict(list))

    @classmethod
    def from_world(cls, world: World) -> "Ledger":
        return cls.from_batch(world.batch)

    @classmethod
    def from_batch(cls, batch: GraphBatch) -> "Ledger":
        by_device: dict[str, set[str]] = defaultdict(set)
        for ad in batch.account_devices:
            by_device[ad.device_id].add(ad.account_id)
        devices: dict[str, set[str]] = defaultdict(set)
        for accounts in by_device.values():
            for a in accounts:
                devices[a] |= accounts - {a}
        ledger = cls({a.id: a.kind for a in batch.accounts},
                     {a.id: a.created_at for a in batch.accounts}, devices)
        txs = sorted((Tx(t.id, t.src, t.dst, t.amount, t.ts) for t in batch.transfers
                      if t.amount is not None and t.ts is not None), key=lambda t: t.ts)
        for t in txs:
            ledger.outflows[t.src].append(t)
            ledger.inflows[t.dst].append(t)
        return ledger

    @staticmethod
    def _until(txs: list[Tx], end: datetime) -> list[Tx]:
        return txs[:bisect.bisect_right([t.ts for t in txs], end)]

    def ins(self, a: str, start: datetime, end: datetime) -> list[Tx]:
        return [t for t in self._until(self.inflows.get(a, []), end) if t.ts >= start]

    def outs(self, a: str, start: datetime, end: datetime) -> list[Tx]:
        return [t for t in self._until(self.outflows.get(a, []), end) if t.ts >= start]


def _forwarded(ledger: Ledger, t: Tx, now: datetime, within: timedelta = FORWARD_WITHIN) -> bool:
    """Did the receiver send most of this transfer on, soon after, as of `now`?"""
    outs = ledger.outs(t.dst, t.ts, min(now, t.ts + within))
    return any(o.amount >= 0.7 * t.amount for o in outs if o.id != t.id)


def _upstream(ledger: Ledger, a: str, before: datetime, now: datetime, depth: int) -> int:
    if depth >= MAX_DEPTH:
        return 0
    best = 0
    for t in ledger.ins(a, before - FORWARD_WITHIN * 2, before):
        prior = ledger.ins(t.src, t.ts - FORWARD_WITHIN, t.ts)
        if any(p.amount * 0.7 <= t.amount for p in prior):  # the sender was forwarding too
            best = max(best, 1 + _upstream(ledger, t.src, t.ts, now, depth + 1))
    return best


def _downstream(ledger: Ledger, a: str, after: datetime, now: datetime, depth: int) -> int:
    if depth >= MAX_DEPTH:
        return 0
    best = 0
    for t in ledger.outs(a, after, min(now, after + FORWARD_WITHIN)):
        if _forwarded(ledger, t, now):
            best = max(best, 1 + _downstream(ledger, t.dst, t.ts, now, depth + 1))
    return best


def _chain_depth(ledger: Ledger, a: str, now: datetime) -> int:
    best = 0
    for t in ledger.ins(a, now - WINDOW, now):
        if _forwarded(ledger, t, now):
            up = _upstream(ledger, a, t.ts, now, 0)
            down = _downstream(ledger, a, t.ts, now, 0)
            best = max(best, up + down)
    return min(best, MAX_DEPTH)


def _cycle(ledger: Ledger, a: str, now: datetime) -> bool:
    senders = {t.src for t in ledger.ins(a, now - WINDOW, now)}
    if not senders:
        return False
    frontier = [(a, now - WINDOW)]
    for _ in range(4):
        nxt = []
        for node, since in frontier:
            for t in ledger.outs(node, since, now):
                if t.dst in senders or t.dst == a:
                    return True
                # An exchange or mixer pays out to everyone: walking through it finds a
                # "cycle" behind every account that ever bought crypto.
                if ledger.kinds.get(t.dst) not in ("exchange", "mixer"):
                    nxt.append((t.dst, t.ts))
        frontier = nxt[:200]
    return False


def _squash(n: float, scale: float) -> float:
    return min(1.0, math.log1p(n) / math.log1p(scale))


def account_features(ledger: Ledger, a: str, now: datetime) -> list[float]:
    """The 14 numbers the network sees for account `a`, from transfers up to `now`."""
    start = now - WINDOW
    ins, outs = ledger.ins(a, start, now), ledger.outs(a, start, now)
    in_amt = sum(t.amount for t in ins)
    forwarded_amt = sum(o.amount for o in outs
                        if any(i.ts <= o.ts <= i.ts + FORWARD_WITHIN for i in ins))
    fast = [i for i in ins if _forwarded(ledger, i, now, timedelta(hours=24))]
    near = [i for i in ins if 0.9 * REPORTING_THRESHOLD <= i.amount < REPORTING_THRESHOLD]
    created = ledger.created.get(a)
    age = (now - created).days if created else 3650
    parties = {t.src for t in ins} | {t.dst for t in outs}
    new_parties = [p for p in parties
                   if (c := ledger.created.get(p)) is not None and now - c < NEW_ACCOUNT]
    exits = [t for t in outs if ledger.kinds.get(t.dst) in ("exchange", "mixer")]
    return [
        _squash(len(ins), 30),
        _squash(len(outs), 30),
        _squash(in_amt, 1_000_000),
        min(1.0, forwarded_amt / in_amt) if in_amt else 0.0,
        len(fast) / len(ins) if ins else 0.0,
        min(1.0, len(near) / 8),
        _squash(len({t.src for t in ins}), 20),
        _squash(len({t.dst for t in outs}), 20),
        1.0 - min(age, 365) / 365,
        _chain_depth(ledger, a, now) / MAX_DEPTH,
        1.0 if _cycle(ledger, a, now) else 0.0,
        min(1.0, len(ledger.devices.get(a, ())) / 5),
        len(new_parties) / len(parties) if parties else 0.0,
        1.0 if exits else 0.0,
    ]


def labelled_accounts(world: World) -> list[tuple[str, int, list[datetime]]]:
    """(account, class, moments) for the working members of planted cases and decoys.

    A member is labelled from its second case transfer on, while the case is still unfolding,
    and again once it has finished: the simulation shows cases as they happen, so the network
    must recognise them part way. At its first case transfer a member is labelled clear: one
    large deposit into a new account is not yet evidence of anything, and the network should
    wait for the money to move on. Decoy members are labelled clear throughout.
    """
    ts = {t.id: t.ts for t in world.batch.transfers}
    out = []
    for case in world.manifest.cases:
        times = [ts[t] for t in case.transfer_ids if ts.get(t)]
        if not times:
            continue
        own: dict[str, list[datetime]] = defaultdict(list)
        ids = set(case.transfer_ids)
        for t in world.batch.transfers:
            if t.id in ids and t.ts:
                own[t.src].append(t.ts)
                own[t.dst].append(t.ts)
        cls = CLASS[FAMILY[case.kind]] if case.category == "planted" else CLASS["clear"]
        for a in case.account_ids:
            moments = sorted(own[a])
            if len(moments) >= 2:
                out.append((a, CLASS["clear"], [moments[0]]))
                out.append((a, cls, [*moments[1:], max(times)]))
            elif a == case.seed_account_id:
                out.append((a, cls, [max(times)]))
    return out


def dataset(seeds: list[int], background_per_world: int = 120) -> tuple[np.ndarray, np.ndarray]:
    """Features and labels over several small synthetic worlds."""
    from lattice.datagen.generator import generate_world

    xs, ys = [], []
    for seed in seeds:
        world = generate_world(seed, "fixture")
        ledger = Ledger.from_world(world)
        members = labelled_accounts(world)
        taken = {a for a, _, _ in members}
        rng = random.Random(seed)
        for a, cls, moments in members:
            later = [] if len(moments) == 1 and cls == CLASS["clear"] else [
                moments[-1] + timedelta(days=rng.uniform(0.5, 3.0))]
            for when in [*moments, *later]:
                xs.append(account_features(ledger, a, when))
                ys.append(cls)
        stamps = [t.ts for t in world.batch.transfers if t.ts]
        lo, hi = min(stamps), max(stamps)
        others = [a.id for a in world.batch.accounts if a.id not in taken
                  and a.kind in ("person", "business")]
        for a in rng.sample(others, min(background_per_world, len(others))):
            when = lo + (hi - lo) * rng.uniform(0.3, 1.0)
            xs.append(account_features(ledger, a, when))
            ys.append(CLASS["clear"])
    return np.array(xs), np.array(ys)
