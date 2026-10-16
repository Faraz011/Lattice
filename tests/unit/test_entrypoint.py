"""The `lattice <role>` entrypoint passes container-safe defaults to each server."""

import pytest

import lattice.mcp_server.server as mcp_server
from lattice.__main__ import mcp


@pytest.fixture
def served(monkeypatch):
    seen: list[list[str]] = []
    monkeypatch.setattr(mcp_server, "main", lambda argv: seen.append(argv))
    monkeypatch.delenv("PORT", raising=False)
    return seen


def test_mcp_listens_on_every_interface_by_default(served):
    mcp([])

    assert served == [["--host", "0.0.0.0", "--port", "8000"]]


def test_mcp_keeps_the_container_host_when_only_the_port_is_given(served):
    mcp(["--port", "9000"])

    assert served == [["--host", "0.0.0.0", "--port", "9000"]]


def test_mcp_reads_the_platform_port(served, monkeypatch):
    monkeypatch.setenv("PORT", "10000")

    mcp([])

    assert served == [["--host", "0.0.0.0", "--port", "10000"]]
