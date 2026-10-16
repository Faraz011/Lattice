"""`python -m lattice check` verifies configuration and reaches Neo4j (with GDS) and Redis."""

import argparse
import sys

import redis
from neo4j import GraphDatabase

from lattice.config import ConfigError, load_settings


def check() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1

    auth = (settings.neo4j_user, settings.neo4j_password.get_secret_value())
    with GraphDatabase.driver(settings.neo4j_uri, auth=auth) as driver:
        gds_version = driver.execute_query("RETURN gds.version() AS v").records[0]["v"]
    print(f"neo4j ok, gds {gds_version}")

    redis.Redis.from_url(settings.redis_url).ping()
    print("redis ok")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="lattice")
    parser.add_argument("command", choices=["check"])
    args = parser.parse_args()
    if args.command == "check":
        sys.exit(check())


if __name__ == "__main__":
    main()
