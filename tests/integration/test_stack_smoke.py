"""Smoke checks against the compose stack: `docker compose up -d neo4j redis` first."""

import uuid

import pytest
import redis
from neo4j import GraphDatabase

from lattice.config import load_settings


@pytest.fixture(scope="module")
def settings():
    return load_settings()


@pytest.fixture(scope="module")
def driver(settings):
    auth = (settings.neo4j_user, settings.neo4j_password.get_secret_value())
    with GraphDatabase.driver(settings.neo4j_uri, auth=auth) as drv:
        yield drv


def test_neo4j_reports_a_gds_version(driver):
    version = driver.execute_query("RETURN gds.version() AS v").records[0]["v"]
    assert isinstance(version, str) and version


def test_gds_can_run_an_algorithm(driver):
    # Proves GDS procedures are callable, not just installed.
    records = driver.execute_query(
        """
        CALL gds.graph.project.cypher(
          $name,
          'UNWIND [1, 2, 3] AS id RETURN id',
          'UNWIND [[1, 2], [2, 3]] AS e RETURN e[0] AS source, e[1] AS target'
        ) YIELD nodeCount
        RETURN nodeCount
        """,
        name=f"smoke-{uuid.uuid4().hex}",
    ).records
    assert records[0]["nodeCount"] == 3
    driver.execute_query("CALL gds.graph.list() YIELD graphName "
                         "WITH graphName WHERE graphName STARTS WITH 'smoke-' "
                         "CALL gds.graph.drop(graphName) YIELD graphName AS dropped "
                         "RETURN count(dropped)")


def test_neo4j_has_apoc(driver):
    version = driver.execute_query("RETURN apoc.version() AS v").records[0]["v"]
    assert version


def test_redis_round_trips_a_value(settings):
    client = redis.Redis.from_url(settings.redis_url)
    key = f"lattice:smoke:{uuid.uuid4().hex}"
    client.set(key, "ok", ex=30)
    assert client.get(key) == b"ok"
    client.delete(key)
