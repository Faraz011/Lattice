"""End to end over Streamable HTTP: a real server process and a real MCP client."""

import socket
import threading
import time
import uuid

import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from lattice.mcp_server.server import CASE_HEADER, build_app

SURFACE = {
    "graph_schema", "graph_get_node", "graph_neighbors", "graph_find_paths",
    "graph_match_pattern", "graph_cypher_readonly", "algo_pagerank", "algo_communities",
    "algo_similar", "algo_impact", "case_cite", "case_propose_action",
}


@pytest.fixture(scope="module")
def server_url(fixture_world):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(build_app(), host="127.0.0.1", port=port,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started:
        assert time.time() < deadline, "MCP server did not start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=10)


def client(url: str, case_id: str | None):
    headers = {CASE_HEADER: case_id} if case_id else {}
    return Client(streamable_http_client(url, http_client=httpx2.AsyncClient(headers=headers)))


async def test_the_server_lists_exactly_the_tool_surface(server_url):
    async with client(server_url, None) as mcp:
        tools = await mcp.list_tools()

    assert {t.name for t in tools.tools} == SURFACE
    assert all(t.description for t in tools.tools)
    assert not any("execute" in t.name for t in tools.tools)


async def test_a_call_without_the_case_header_is_refused(server_url, fixture_world, graph):
    account = fixture_world.batch.accounts[0].id
    async with client(server_url, None) as mcp:
        result = await mcp.call_tool("graph_get_node", {"node_id": account})

    assert result.is_error
    assert "case context" in result.content[0].text
    rows = await graph.read("MATCH (l:LedgerEntry {case_id: ''}) RETURN count(l) AS n")
    assert rows[0]["n"] == 0


async def test_a_call_with_the_case_header_is_answered_and_ledgered(server_url, fixture_world,
                                                                    graph):
    case_id = f"case_http{uuid.uuid4().hex[:12]}"
    account = fixture_world.batch.accounts[0].id
    try:
        async with client(server_url, case_id) as mcp:
            result = await mcp.call_tool("graph_get_node", {"node_id": account})
        rows = await graph.read(
            "MATCH (l:LedgerEntry {case_id: $c}) RETURN l.result_id AS r, l.node_ids AS n",
            c=case_id,
        )
    finally:
        await graph.write("MATCH (l:LedgerEntry {case_id: $c}) DELETE l", c=case_id)

    assert not result.is_error
    payload = result.structured_content
    assert payload["node"]["id"] == account
    assert rows == [{"r": payload["result_id"], "n": [account]}]


async def test_a_rejected_cypher_write_comes_back_as_a_tool_error(server_url):
    async with client(server_url, f"case_http{uuid.uuid4().hex[:12]}") as mcp:
        result = await mcp.call_tool("graph_cypher_readonly",
                                     {"query": "MATCH (n:Account) DETACH DELETE n"})

    assert result.is_error
    assert "DELETE" in result.content[0].text
