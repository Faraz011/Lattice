"""Evidence loaded from Neo4j matches the offline evidence graph and scores the same."""

from lattice.graph.subgraph import EvidenceGraph, load_evidence
from lattice.scoring.scorer import Scorer


def evidence_ids(world, case):
    links = [f"used_device:{link.account_id}:{link.device_id}"
             for link in world.batch.account_devices if link.device_id in case.device_ids]
    return [*case.transfer_ids, *links]


async def test_loading_from_neo4j_reproduces_the_offline_evidence_graph(graph, fixture_world):
    for kind in ("peeling_chain", "shared_device", "exit_via_mixer"):
        case = next(c for c in fixture_world.manifest.cases if c.kind == kind)
        ids = evidence_ids(fixture_world, case)

        loaded = await load_evidence(graph, ids)
        offline = EvidenceGraph.from_batch(fixture_world.batch, ids)

        assert loaded == offline, kind
        assert Scorer().score(loaded) == Scorer().score(offline)


async def test_unknown_ids_are_simply_absent(graph):
    loaded = await load_evidence(graph, ["tx_doesnotexist0000", "used_device:acct_x:dev_y"])

    assert loaded.edge_ids() == []
