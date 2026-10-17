"""Structural detectors: typology shapes read from counts and topology alone.

Elliptic2's flows carry no amount and no time, so the amount- and time-based detectors in
`detectors.py` see nothing there. These detectors read `EvidenceGraph.transfers()` and only the
shape of the flows: who pays whom, how many distinct counterparties, which accounts loop money
back, which small groups trade densely among themselves.

The scorer runs them only when the evidence graph has no priced flows at all (see
`EvidenceGraph.has_priced_flows`), or when a setting forces them on. The synthetic world is
fully priced, so its scores are untouched.

Like the priced detectors, each is a pure function of the edges the graph currently includes,
so removing an edge changes their output and the evidence circuit stays faithful.
"""

from collections import defaultdict
from collections.abc import Callable
from math import comb

from lattice.graph.subgraph import EvidenceGraph, Transfer
from lattice.scoring.detectors import DetectorResult, _clamp, _found

MIN_CYCLE, MAX_CYCLE = 3, 6  # accounts in a cycle; A->B->A is a deposit and its refund
CYCLE_SEARCH_BUDGET = 50_000  # DFS steps, so a dense evidence graph cannot stall the scorer
DENSE_MIN_ACCOUNTS = 4

# Prior weights: the real Elliptic2 labels were not available, and the five-subgraph sample only
# supports the cycle weight. Retune with `lattice.eval.tune_structural`. A cycle of 3+ accounts
# flags on its own; a fan never does (exchanges and services are hubs), and a dense group needs
# a second signal unless it is close to a clique.
STRUCTURAL_WEIGHTS: dict[str, float] = {
    "structural_cycle": 0.75,
    "structural_fan_in": 0.3,
    "structural_fan_out": 0.3,
    "structural_dense": 0.6,
}


def _pairs(transfers: list[Transfer]) -> dict[tuple[str, str], list[str]]:
    """Edge IDs for each ordered (src, dst) pair, self-loops dropped."""
    pairs: dict[tuple[str, str], list[str]] = defaultdict(list)
    for t in transfers:
        if t.src != t.dst:
            pairs[(t.src, t.dst)].append(t.id)
    return dict(pairs)


# --- cycle --------------------------------------------------------------------------------


def structural_cycle(g: EvidenceGraph) -> DetectorResult:
    """Flows that leave an account and come back to it through two or more other accounts."""
    pairs = _pairs(g.transfers())
    succ: dict[str, list[str]] = defaultdict(list)
    for src, dst in sorted(pairs):
        succ[src].append(dst)

    best: list[str] = []
    steps = 0

    # Each simple cycle is found once, from its smallest account, through larger ones only.
    def walk(start: str, path: list[str]) -> None:
        nonlocal best, steps
        for nxt in succ.get(path[-1], []):
            steps += 1
            if steps > CYCLE_SEARCH_BUDGET:
                return
            if nxt == start:
                if len(path) >= MIN_CYCLE and len(path) > len(best):
                    best = list(path)
            elif nxt > start and nxt not in path and len(path) < MAX_CYCLE:
                walk(start, [*path, nxt])

    for start in sorted(succ):
        walk(start, [start])
    if not best:
        return DetectorResult("structural_cycle", 0.0)
    hops = list(zip(best, [*best[1:], best[0]], strict=True))
    edges = [pairs[hop][0] for hop in hops]
    return _found("structural_cycle", 1.0, edges, best[0],
                  f"flows loop through {len(best)} accounts back to the start")


# --- fan in / fan out ---------------------------------------------------------------------


def _fan(g: EvidenceGraph, name: str, outward: bool) -> DetectorResult:
    edges: dict[str, list[str]] = defaultdict(list)
    others: dict[str, set[str]] = defaultdict(set)
    for (src, dst), ids in _pairs(g.transfers()).items():
        hub, other = (src, dst) if outward else (dst, src)
        edges[hub].extend(ids)
        others[hub].add(other)
    if not others:
        return DetectorResult(name, 0.0)
    hub = min(others, key=lambda a: (-len(others[a]), a))
    count = len(others[hub])
    direction = "pays" if outward else "is paid by"
    return _found(name, _clamp((count - 4) / 8), sorted(edges[hub]), hub,
                  f"one account {direction} {count} distinct counterparties")


def structural_fan_out(g: EvidenceGraph) -> DetectorResult:
    """One account paying many distinct counterparties."""
    return _fan(g, "structural_fan_out", outward=True)


def structural_fan_in(g: EvidenceGraph) -> DetectorResult:
    """One account paid by many distinct counterparties."""
    return _fan(g, "structural_fan_in", outward=False)


# --- dense group --------------------------------------------------------------------------


def structural_dense(g: EvidenceGraph) -> DetectorResult:
    """A small group of accounts that transact densely among themselves.

    Greedy peeling (Charikar): drop the account with the fewest links in the group, one at a
    time, and keep the densest group of at least four accounts seen on the way. Density is
    linked pairs over possible pairs, ignoring direction. A star (fan) peels down to density
    0.5 at best, below where strength starts.
    """
    pairs = _pairs(g.transfers())
    neighbours: dict[str, set[str]] = defaultdict(set)
    for src, dst in pairs:
        neighbours[src].add(dst)
        neighbours[dst].add(src)
    group = set(neighbours)

    def links(accounts: set[str]) -> int:
        return sum(len(neighbours[a] & accounts) for a in accounts) // 2

    best: tuple[float, set[str]] = (0.0, set())
    while len(group) >= DENSE_MIN_ACCOUNTS:
        density = links(group) / comb(len(group), 2)
        if density > best[0]:
            best = (density, set(group))
        weakest = min(group, key=lambda a: (len(neighbours[a] & group), a))
        group.discard(weakest)

    density, members = best
    if not members:
        return DetectorResult("structural_dense", 0.0)
    edges = sorted(e for (src, dst), ids in pairs.items()
                   if src in members and dst in members for e in ids)
    anchor = min(members, key=lambda a: (-len(neighbours[a] & members), a))
    return _found("structural_dense", _clamp((density - 0.5) / 0.4), edges, anchor,
                  f"{len(members)} accounts with {density:.0%} of possible links among them")


STRUCTURAL_DETECTORS: dict[str, Callable[[EvidenceGraph], DetectorResult]] = {
    "structural_cycle": structural_cycle,
    "structural_fan_in": structural_fan_in,
    "structural_fan_out": structural_fan_out,
    "structural_dense": structural_dense,
}
