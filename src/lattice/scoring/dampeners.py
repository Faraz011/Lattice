"""Benign-pattern dampeners (KTD7): ordinary business that shares a typology's surface shape."""

from collections import defaultdict
from collections.abc import Callable

from lattice.graph.subgraph import EvidenceGraph
from lattice.scoring.detectors import DetectorResult


def payroll_cadence(g: EvidenceGraph, result: DetectorResult) -> float:
    """A business paying most recipients the same amount on the same day each month."""
    hub = g.account(result.anchor) if result.anchor else None
    if hub is None or hub.kind != "business":
        return 1.0
    payments: dict[str, list] = defaultdict(list)
    for t in g.priced_transfers():
        if t.src == hub.id:
            payments[t.dst].append(t)
    regular = [
        recipient for recipient, ts in payments.items()
        if len(ts) >= 2 and len({t.amount for t in ts}) == 1 and len({t.ts.day for t in ts}) == 1
    ]
    return 0.15 if payments and len(regular) >= 0.5 * len(payments) else 1.0


def merchant_inflows(g: EvidenceGraph, result: DetectorResult) -> float:
    """A business collecting card payments, as a shop does."""
    collector = g.account(result.anchor) if result.anchor else None
    if collector is None or collector.kind != "business":
        return 1.0
    inflows = [t for t in g.priced_transfers() if t.dst == collector.id]
    card = [t for t in inflows if t.channel == "card"]
    return 0.2 if inflows and len(card) >= 0.5 * len(inflows) else 1.0


DAMPENERS: dict[str, list[Callable[[EvidenceGraph, DetectorResult], float]]] = {
    "fan_out": [payroll_cadence],
    "fan_in_structuring": [merchant_inflows],
}


def dampening(g: EvidenceGraph, result: DetectorResult) -> float:
    factor = 1.0
    for dampener in DAMPENERS.get(result.name, []):
        factor *= dampener(g, result)
    return factor
