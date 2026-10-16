import pytest

from lattice.mcp_server.cypher_guard import CypherRejected, check_readonly


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
