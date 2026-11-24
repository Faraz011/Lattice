"""Backup routes, freeze what-ifs, the size curve, inferred roles and the SAR draft."""

import random

from lattice.agents.narrator import ID_PATTERN
from lattice.datagen import typologies
from lattice.datagen.background import build_background
from lattice.datagen.builder import WINDOW_START, WorldBuilder, days
from lattice.datagen.generator import DEMO_SEED, FIXTURE_SEED, generate_world
from lattice.explain.circuit import find_circuit
from lattice.explain.report import build_report
from lattice.explain.routes import find_routes, freeze_whatif, infer_roles, size_curve
from lattice.graph.subgraph import EvidenceGraph
from lattice.scoring.scorer import Scorer

SCORER = Scorer()


def planted(kind: str, seed: int = 5):
    b = WorldBuilder(seed)
    build_background(b, random.Random(seed), persons=30, businesses=4)
    pattern = getattr(typologies, kind)(b, random.Random(seed), WINDOW_START + days(20))
    noise = random.Random(seed).sample(
        sorted(t.id for t in b.batch.transfers if t.id not in pattern.transfer_ids), 20)
    return pattern, EvidenceGraph.from_batch(b.batch, pattern.transfer_ids + noise)


PATTERN, GRAPH = planted("parallel_mules")
ROUTE_A, ROUTE_B = (set(r) for r in PATTERN.routes)


def test_both_planted_routes_are_recovered_and_disjoint():
    routes = find_routes(GRAPH, SCORER)

    assert len(routes) == 2
    assert set(routes[0].edges) <= ROUTE_A  # the scorer's proof: the longer route
    assert set(routes[1].edges) <= ROUTE_B  # the backup
    assert not set(routes[0].path) & set(routes[1].path)
    assert all(r.score >= SCORER.threshold for r in routes)


def test_roles_are_read_from_the_routes_and_match_the_planted_ones():
    roles = infer_roles(GRAPH, find_routes(GRAPH, SCORER))

    assert roles  # every inferred role is checked against the answer key
    assert all(PATTERN.roles[a] == role for a, role in roles.items())
    assert set(roles.values()) == {"originator", "mule", "collector"}


def test_freezing_a_mule_on_the_proof_leaves_the_backup_route_carrying_the_flag():
    mule = next(a for a, r in PATTERN.roles.items() if r == "mule"
                and any(a in (t.src, t.dst) for t in GRAPH.all_transfers if t.id in ROUTE_A))

    whatif = freeze_whatif(GRAPH, SCORER, mule, "mule")

    assert whatif.still_flagged
    assert whatif.score_after >= SCORER.threshold
    assert set(whatif.backup_edges) <= ROUTE_B
    assert whatif.removed_edges and set(whatif.removed_edges) <= ROUTE_A


def test_on_a_single_route_freezing_a_mid_chain_account_stops_the_case():
    pattern, graph = planted("rapid_layering", seed=9)
    middle = pattern.path[len(pattern.path) // 2] if pattern.path else None
    accounts = [middle] if middle else [a for a in pattern.account_ids[1:-1]]

    results = [freeze_whatif(graph, SCORER, a) for a in accounts]

    assert any(not r.still_flagged and r.backup_edges == [] for r in results)


def test_the_size_curve_names_the_smallest_flagging_explanation():
    circuit = find_circuit(GRAPH, SCORER)

    curve = size_curve(GRAPH, SCORER, circuit)

    k = curve.sufficient_at
    assert k is not None and k <= len(curve.ranked_edges)
    assert curve.scores[k - 1] >= SCORER.threshold
    assert all(s < SCORER.threshold for s in curve.scores[: k - 1])
    assert len(curve.scores) == len(curve.ranked_edges)


def test_only_keeps_edges_already_removed_out():
    some = next(iter(ROUTE_A))
    view = GRAPH.without({some}).only(set(GRAPH.edge_ids()))

    assert some not in view.edge_ids()


def test_the_sar_draft_cites_only_ids_from_the_report_and_names_the_backup():
    report = build_report(GRAPH, SCORER, subject=PATTERN.seed_account_id)

    draft = report.sar_draft
    assert draft is not None
    assert "Route 2" in draft and "would not stop the activity" in draft
    known = ({e.id for e in report.edges} | {a for r in report.routes for a in r.accounts}
             | {PATTERN.seed_account_id})
    assert set(ID_PATTERN.findall(draft)) <= known


def test_showcase_cases_are_appended_without_touching_existing_worlds():
    fixture = generate_world(FIXTURE_SEED, "fixture")
    demo = generate_world(DEMO_SEED, "demo")

    assert not [c for c in fixture.manifest.cases if c.kind == "parallel_mules"]
    showcase = [c for c in demo.manifest.cases if c.kind == "parallel_mules"]
    assert len(showcase) == 2 and demo.manifest.cases[-2:] == showcase
    assert all(len(c.routes) == 2 and c.roles for c in showcase)
    # Alerts from evaluation runs recorded before the showcase existed are still there.
    alerts = {a.id for a in demo.batch.alerts}
    assert {"alert_6a8f985f048773a2", "alert_9d9c55d58621f478"} <= alerts
