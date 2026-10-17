"""Typology detectors (KTD7). Each is a pure function of an evidence graph.

A detector returns how strongly the graph shows its typology (0 to 1), which edges it relied on
(with each edge's share of that evidence), and the account the pattern centres on. Detectors
read only the edges the graph currently includes, so removing an edge changes their output:
that is what makes the evidence circuit (U12) a faithful explanation.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import timedelta

from lattice.graph.subgraph import EvidenceGraph, Transfer

REPORTING_THRESHOLD = 10_000.0


@dataclass(frozen=True)
class DetectorResult:
    name: str
    strength: float
    edges: dict[str, float] = field(default_factory=dict)
    anchor: str | None = None
    reason: str = ""


def _found(name: str, strength: float, edges: Iterable[str], anchor: str | None,
           reason: str) -> DetectorResult:
    unique = list(dict.fromkeys(edges))
    if strength <= 0 or not unique:
        return DetectorResult(name, 0.0)
    share = 1 / len(unique)
    return DetectorResult(name, round(min(1.0, strength), 6), {e: share for e in unique},
                          anchor, reason)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _outflows(transfers: list[Transfer]) -> dict[str, list[Transfer]]:
    out: dict[str, list[Transfer]] = defaultdict(list)
    for t in transfers:  # already in time order
        out[t.src].append(t)
    return dict(out)


def _inflows(transfers: list[Transfer]) -> dict[str, list[Transfer]]:
    inn: dict[str, list[Transfer]] = defaultdict(list)
    for t in transfers:
        inn[t.dst].append(t)
    return dict(inn)


def _longest(start: Transfer, step: Callable[[Transfer], tuple[Transfer, list[str]] | None],
             memo: dict[str, tuple[int, list[str]]]) -> tuple[int, list[str]]:
    """Length (in hops) and edges of the longest chain reachable by repeatedly applying `step`."""
    if start.id in memo:
        return memo[start.id]
    memo[start.id] = (0, [start.id])  # guards against cycles while recursing
    nxt = step(start)
    if nxt is None:
        result = (0, [start.id])
    else:
        forward, extra = nxt
        hops, edges = _longest(forward, step, memo)
        result = (hops + 1, [start.id, *extra, *edges])
    memo[start.id] = result
    return result


# --- peeling chain ------------------------------------------------------------------------


def peeling_chain(g: EvidenceGraph) -> DetectorResult:
    """Money forwarded hop by hop within 48h, each hop skimming a small slice to a side account."""
    transfers = g.priced_transfers()
    out = _outflows(transfers)
    window = timedelta(hours=48)

    def step(inflow: Transfer) -> tuple[Transfer, list[str]] | None:
        later = [t for t in out.get(inflow.dst, []) if inflow.ts <= t.ts <= inflow.ts + window]
        forwards = [t for t in later if 0.85 * inflow.amount <= t.amount <= inflow.amount * 1.0001]
        if not forwards:
            return None
        forward = max(forwards, key=lambda t: (t.amount, t.id))
        peels = [t for t in later
                 if t.id != forward.id and t.amount <= 0.1 * inflow.amount]
        if not peels:
            return None
        return forward, [p.id for p in peels]

    memo: dict[str, tuple[int, list[str]]] = {}
    best = max((_longest(t, step, memo) for t in transfers), default=(0, []),
               key=lambda r: (r[0], -len(r[1])))
    hops, edges = best
    if hops < 2:
        return DetectorResult("peeling_chain", 0.0)
    anchor = next((t.dst for t in transfers if t.id == edges[0]), None)
    return _found("peeling_chain", hops / 4, edges, anchor, f"{hops} forwarding hops that skim")


# --- fan in / fan out ---------------------------------------------------------------------


def fan_in_structuring(g: EvidenceGraph) -> DetectorResult:
    """Many senders depositing just under the reporting threshold into one account within 7 days."""
    transfers = g.priced_transfers()
    out = _outflows(transfers)
    window = timedelta(days=7)
    best: tuple[int, list[Transfer], str | None] = (0, [], None)
    for account, inflows in _inflows(transfers).items():
        band = [t for t in inflows if 0.8 * REPORTING_THRESHOLD <= t.amount < REPORTING_THRESHOLD]
        start = 0
        for end in range(len(band)):
            while band[end].ts - band[start].ts > window:
                start += 1
            current = band[start : end + 1]
            senders = len({t.src for t in current})
            if senders > best[0]:
                best = (senders, current, account)
    senders, deposits, collector = best
    if not deposits:
        return DetectorResult("fan_in_structuring", 0.0)
    total = sum(t.amount for t in deposits)
    onward = [t for t in out.get(collector, [])
              if deposits[-1].ts <= t.ts <= deposits[-1].ts + timedelta(days=3)
              and t.amount >= 0.5 * total]
    edges = [t.id for t in deposits] + [t.id for t in onward[:1]]
    return _found("fan_in_structuring", _clamp((senders - 4) / 8), edges, collector,
                  f"{senders} senders just under the threshold within 7 days")


def fan_out(g: EvidenceGraph) -> DetectorResult:
    """One large deposit split across many recipients within 48 hours."""
    transfers = g.priced_transfers()
    out = _outflows(transfers)
    best: tuple[int, list[str], str | None] = (0, [], None)
    for hub, inflows in _inflows(transfers).items():
        for inflow in inflows:
            if inflow.amount < REPORTING_THRESHOLD:
                continue
            payouts = [t for t in out.get(hub, [])
                       if inflow.ts <= t.ts <= inflow.ts + timedelta(hours=48)]
            if sum(t.amount for t in payouts) < 0.5 * inflow.amount:
                continue
            recipients = len({t.dst for t in payouts})
            if recipients > best[0]:
                best = (recipients, [inflow.id, *(t.id for t in payouts)], hub)
    recipients, edges, hub = best
    return _found("fan_out", _clamp((recipients - 4) / 6), edges, hub,
                  f"one deposit split across {recipients} recipients within 48h")


# --- round trip ---------------------------------------------------------------------------


def round_trip(g: EvidenceGraph) -> DetectorResult:
    """Similar amounts leaving an account and returning to it within 14 days (3+ transfers)."""
    out = _outflows(g.priced_transfers())
    span = timedelta(days=14)
    best: list[Transfer] = []

    def walk(origin: str, path: list[Transfer]) -> None:
        nonlocal best
        last = path[-1]
        for t in out.get(last.dst, []):
            if t.ts < last.ts or t.ts - path[0].ts > span or t in path:
                continue
            if abs(t.amount - path[0].amount) > 0.2 * path[0].amount:
                continue
            if t.dst == origin:
                if len(path) + 1 >= 3 and len(path) + 1 > len(best):
                    best = [*path, t]
            elif len(path) < 5:
                walk(origin, [*path, t])

    for transfers in out.values():
        for first in transfers:
            walk(first.src, [first])
    if not best:
        return DetectorResult("round_trip", 0.0)
    return _found("round_trip", 1.0, [t.id for t in best], best[0].src,
                  f"{len(best)}-transfer cycle back to the origin within 14 days")


# --- rapid layering -----------------------------------------------------------------------


def rapid_layering(g: EvidenceGraph) -> DetectorResult:
    """Funds passing nearly whole through accounts opened within 14 days, each hop within 24h."""
    transfers = g.priced_transfers()
    out = _outflows(transfers)

    def step(inflow: Transfer) -> tuple[Transfer, list[str]] | None:
        account = g.account(inflow.dst)
        if (account is None or account.created_at is None
                or inflow.ts - account.created_at > timedelta(days=14)):
            return None
        onward = [t for t in out.get(inflow.dst, [])
                  if inflow.ts <= t.ts <= inflow.ts + timedelta(hours=24)
                  and t.amount >= 0.95 * inflow.amount]
        if not onward:
            return None
        return max(onward, key=lambda t: (t.amount, t.id)), []

    memo: dict[str, tuple[int, list[str]]] = {}
    hops, edges = max((_longest(t, step, memo) for t in transfers), default=(0, []),
                      key=lambda r: (r[0], -len(r[1])))
    if hops < 2:
        return DetectorResult("rapid_layering", 0.0)
    anchor = next((t.src for t in transfers if t.id == edges[0]), None)
    return _found("rapid_layering", (hops - 1) / 3, edges, anchor,
                  f"{hops} new accounts passed the funds on within hours")


# --- shared device ------------------------------------------------------------------------


def shared_device(g: EvidenceGraph) -> DetectorResult:
    """Accounts of different customers on one device, all paying the same destination."""
    out = _outflows(g.priced_transfers())
    by_device: dict[str, list] = defaultdict(list)
    for link in g.links():
        by_device[link.device_id].append(link)

    best: tuple[int, list[str], str | None] = (0, [], None)
    for device, links in sorted(by_device.items()):
        payers: dict[str, list] = defaultdict(list)
        for link in links:
            account = g.account(link.account_id)
            for t in out.get(link.account_id, []):
                payers[t.dst].append((link, t, account.customer_id if account else None))
        for _destination, rows in sorted(payers.items()):
            customers = {customer for _, _, customer in rows}
            if len(customers) > best[0]:
                edges = [link.id for link, _, _ in rows] + [t.id for _, t, _ in rows]
                best = (len(customers), edges, device)
    customers, edges, device = best
    strength = 1.0 if customers >= 4 else 0.6 if customers == 3 else 0.0
    return _found("shared_device", strength, edges, device,
                  f"{customers} customers on one device paying one destination")


# --- exit via mixer -----------------------------------------------------------------------


def exit_via_mixer(g: EvidenceGraph) -> DetectorResult:
    """Funds sent into a mixer and on to an exchange within 3 days."""
    transfers = g.priced_transfers()
    out, inn = _outflows(transfers), _inflows(transfers)

    def kind(account_id: str) -> str | None:
        account = g.account(account_id)
        return account.kind if account else None

    for entry in transfers:
        if kind(entry.dst) != "mixer":
            continue
        exits = [t for t in out.get(entry.dst, [])
                 if kind(t.dst) == "exchange" and entry.ts <= t.ts <= entry.ts + timedelta(days=3)
                 and t.amount >= 0.8 * entry.amount]
        if not exits:
            continue
        upstream, current = [], entry
        for _ in range(3):
            feeders = [t for t in inn.get(current.src, [])
                       if t.ts <= current.ts and t.ts >= current.ts - timedelta(days=7)]
            if not feeders:
                break
            current = max(feeders, key=lambda t: (t.amount, t.id))
            upstream.append(current.id)
        edges = [*reversed(upstream), entry.id, exits[0].id]
        return _found("exit_via_mixer", 1.0, edges, entry.src,
                      "funds passed through a mixer to an exchange")
    return DetectorResult("exit_via_mixer", 0.0)


DETECTORS: dict[str, Callable[[EvidenceGraph], DetectorResult]] = {
    "peeling_chain": peeling_chain,
    "fan_in_structuring": fan_in_structuring,
    "fan_out": fan_out,
    "round_trip": round_trip,
    "rapid_layering": rapid_layering,
    "shared_device": shared_device,
    "exit_via_mixer": exit_via_mixer,
}
