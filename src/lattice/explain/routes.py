"""Backup routes, freeze what-ifs, the size curve and account roles (the "freeze" demo).

The evidence circuit (circuit.py) is the *smallest* set of edges that keeps the flag. When the
evidence is redundant, a second, independent set would keep it too, and an investigator who
freezes an account in the first one needs to know that. This module makes that visible:

- `find_routes`: repeat the circuit search on the evidence minus every route found so far, so
  each route is a minimal sufficient circuit that shares no edge with the ones before it.
- `freeze_whatif`: remove every edge that touches one account (what freezing it would do to
  this evidence), rescore, and if the flag survives, find the route that still carries it.
- `size_curve`: the score of the top-k edges by attribution for every k, so an explanation's
  size can be traded against how much of the decision it covers.
- `infer_roles`: originator, mule and collector, read from the routes' structure alone. The
  planted roles in the manifest are the answer key these are evaluated against, never an input.

All of it is computed from the scorer over the cited evidence: no model is involved.
"""

from pydantic import BaseModel

from lattice.explain.circuit import Circuit, find_circuit
from lattice.graph.subgraph import EvidenceGraph
from lattice.scoring.scorer import Scorer

MAX_ROUTES = 3
MAX_CURVE = 40
MAX_WHATIFS = 12


class Route(BaseModel):
    edges: list[str]  # the minimal proof (a circuit), in time order
    path: list[str]  # every edge the detectors used for this route, in time order
    accounts: list[str]  # along `path`, in the order money reaches them
    score: float  # the proof's score on its own


class FreezeWhatIf(BaseModel):
    account_id: str
    role: str | None
    removed_edges: list[str]
    score_before: float
    score_after: float
    still_flagged: bool
    typology_after: str | None
    backup_edges: list[str]  # the route that still carries the flag, if any


class SizeCurve(BaseModel):
    ranked_edges: list[str]  # by attribution, strongest first
    scores: list[float]  # scores[k - 1] is the score of the top k edges alone
    sufficient_at: int | None  # the smallest k whose edges alone keep the flag


def _ordered(graph: EvidenceGraph, edges: list[str]) -> tuple[list[str], list[str]]:
    """Edges in time order, and the accounts money reaches along them."""
    wanted = set(edges)
    transfers = [t for t in graph.all_transfers if t.id in wanted]
    transfers.sort(key=lambda t: (t.ts is None, t.ts.isoformat() if t.ts else "", t.id))
    accounts: list[str] = []
    for t in transfers:
        for a in (t.src, t.dst):
            if a not in accounts:
                accounts.append(a)
    links = [link.id for link in graph.all_links if link.id in wanted]
    return [t.id for t in transfers] + links, accounts


def find_routes(graph: EvidenceGraph, scorer: Scorer, first: Circuit | None = None,
                max_routes: int = MAX_ROUTES) -> list[Route]:
    """Edge-disjoint minimal circuits, the scorer's proof first and then each backup."""
    routes: list[Route] = []
    used: set[str] = set()
    circuit = first or find_circuit(graph, scorer)
    while circuit.status == "circuit" and circuit.circuit_edges and len(routes) < max_routes:
        edges, _ = _ordered(graph, circuit.circuit_edges)
        # The proof stops as soon as it is sufficient; the path is the whole shape the
        # detectors saw (a chain's last hop into the collector, say), which roles are read from.
        path, accounts = _ordered(graph, circuit.supporting_edges or circuit.circuit_edges)
        routes.append(Route(edges=edges, path=path, accounts=accounts,
                            score=round(circuit.sufficiency_score, 4)))
        used |= set(circuit.supporting_edges) | set(circuit.circuit_edges)
        remaining = graph.without(used)
        if scorer.score(remaining).score < scorer.threshold:
            break
        circuit = find_circuit(remaining, scorer)
    return routes


def touching(graph: EvidenceGraph, account: str) -> list[str]:
    """Every edge in the evidence that freezing `account` would stop."""
    edges = [t.id for t in graph.transfers() if account in (t.src, t.dst)]
    edges += [link.id for link in graph.links() if link.account_id == account]
    return edges


def freeze_whatif(graph: EvidenceGraph, scorer: Scorer, account: str,
                  role: str | None = None) -> FreezeWhatIf:
    before = scorer.score(graph)
    removed = touching(graph, account)
    after_graph = graph.without(set(removed))
    after = scorer.score(after_graph)
    flagged = after.score >= scorer.threshold
    backup: list[str] = []
    if flagged:
        backup, _ = _ordered(after_graph, find_circuit(after_graph, scorer).circuit_edges)
    return FreezeWhatIf(account_id=account, role=role, removed_edges=removed,
                        score_before=round(before.score, 4), score_after=round(after.score, 4),
                        still_flagged=flagged, typology_after=after.typology if flagged else None,
                        backup_edges=backup)


def size_curve(graph: EvidenceGraph, scorer: Scorer, circuit: Circuit,
               limit: int = MAX_CURVE) -> SizeCurve:
    order = {e: i for i, e in enumerate(graph.edge_ids())}
    ranked = sorted(circuit.attribution, key=lambda e: (-circuit.attribution[e], order.get(e, 0)))
    ranked = [e for e in ranked if circuit.attribution[e] > 0][:limit]
    scores = [round(scorer.score(graph.only(set(ranked[:k]))).score, 4)
              for k in range(1, len(ranked) + 1)]
    sufficient = next((k for k, s in enumerate(scores, 1) if s >= scorer.threshold), None)
    return SizeCurve(ranked_edges=ranked, scores=scores, sufficient_at=sufficient)


def infer_roles(graph: EvidenceGraph, routes: list[Route]) -> dict[str, str]:
    """Roles from the routes' structure: money enters at the originator, passes through mules,
    and settles at the collector. An account in more than one route keeps its first role."""
    roles: dict[str, str] = {}
    by_id = {t.id: t for t in graph.all_transfers}
    for route in routes:
        transfers = [by_id[e] for e in route.path if e in by_id]
        senders = {t.src for t in transfers}
        receivers = {t.dst for t in transfers}
        for account in route.accounts:
            if account in roles:
                continue
            if account in senders and account not in receivers:
                roles[account] = "originator"
            elif account in receivers and account not in senders:
                roles[account] = "collector"
            elif account in senders and account in receivers:
                roles[account] = "mule"
    return roles


def route_relation(routes: list[Route]) -> str | None:
    """How the routes relate, in the investigator's terms."""
    if len(routes) < 2:
        return None
    starts = {r.accounts[0] for r in routes if r.accounts}
    ends = {r.accounts[-1] for r in routes if r.accounts}
    if len(starts) == 1 and len(ends) == 1:
        return ("parallel: the routes run from the same originator to the same collector, so "
                "each is a backup for the others (either one keeps the flag)")
    return "independent: each route keeps the flag on its own"


def freeze_whatifs(graph: EvidenceGraph, scorer: Scorer, routes: list[Route],
                   roles: dict[str, str], limit: int = MAX_WHATIFS) -> list[FreezeWhatIf]:
    """A what-if for each account on the scorer's proof, then on the backups, up to `limit`."""
    accounts: list[str] = []
    for route in routes:
        for account in route.accounts:
            if account not in accounts:
                accounts.append(account)
    return [freeze_whatif(graph, scorer, a, roles.get(a)) for a in accounts[:limit]]
