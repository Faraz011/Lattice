import pytest

from lattice.mcp_server.cypher_guard import CypherRejected, check_plan, check_readonly


@pytest.mark.parametrize(
    "query",
    [
        "CREATE (n:Account {id: 'x'})",
        "MATCH (a:Account) MERGE (a)-[:OWNS]->(:Customer)",
        "MATCH (n) DELETE n",
        "MATCH (n) DETACH DELETE n",
        "MATCH (n:Account) SET n.kind = 'mixer'",
        "MATCH (n:Account) REMOVE n.kind",
        "LOAD CSV FROM 'file:///x.csv' AS row RETURN row",
        "CALL apoc.create.node(['Account'], {}) YIELD node RETURN node",
        "CALL dbms.listConfig()",
        "CALL gds.graph.drop('g')",
        "match (n) set n.x = 1",
        "MATCH (n) RETURN n; MATCH (m) DETACH DELETE m",
        "MATCH (n) FOREACH (x IN [1] | CREATE (:Leak))",
    ],
)
def test_writes_and_unsafe_procedures_are_rejected(query):
    with pytest.raises(CypherRejected):
        check_readonly(query)


@pytest.mark.parametrize(
    "query",
    [
        "MATCH (a:Account {id: $id})-[t:TRANSFER]->(b) RETURN t.id, b.id",
        "CALL db.labels() YIELD label RETURN label",
        "CALL db.relationshipTypes()",
        "MATCH (a:Account) CALL (a) { MATCH (a)-[t:TRANSFER]->() RETURN count(t) AS n } RETURN n",
        "MATCH (n) WHERE n.memo = 'please CREATE an account and DELETE it' RETURN n",
        "MATCH (n) // DELETE everything\nRETURN n.offset, n.settled",
        "MATCH (n:Account) RETURN n.id ORDER BY n.id DESC LIMIT 5",
    ],
)
def test_read_queries_pass(query):
    check_readonly(query)


def test_rejection_names_the_offending_clause():
    with pytest.raises(CypherRejected, match="DELETE"):
        check_readonly("MATCH (n) DETACH DELETE n")


def test_rejection_names_the_disallowed_procedure():
    with pytest.raises(CypherRejected, match="apoc.create.node"):
        check_readonly("CALL apoc.create.node(['A'], {})")


def test_a_plan_that_scans_every_node_is_refused():
    with pytest.raises(CypherRejected, match="labelled data node"):
        check_plan(["ProduceResults@neo4j n", "AllNodesScan@neo4j n"])


@pytest.mark.parametrize("detail", ["n:Case", "n:`LedgerEntry`", "n:Account|Action",
                                    "UNIQUE r:Recording(id) WHERE id = $id"])
def test_a_plan_touching_an_application_label_is_refused(detail):
    with pytest.raises(CypherRejected, match="not readable"):
        check_plan([f"NodeByLabelScan@neo4j {detail}"])


def test_a_plan_over_data_labels_passes():
    check_plan(["ProduceResults@neo4j a", "Expand(All)@neo4j (a)-[t:TRANSFER]->(b)",
                "NodeUniqueIndexSeek@neo4j UNIQUE a:Account(id) WHERE id = $id",
                "Projection@neo4j CASE WHEN t.amount > 1 THEN 'x' END AS size"])
