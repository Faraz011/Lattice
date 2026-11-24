"""One entrypoint for every Lattice role (KTD12): `lattice <role>` or `python -m lattice <role>`.

    python -m lattice check                  # configuration, Neo4j (with GDS) and Redis reachable
    python -m lattice api [--port 8080]      # the HTTP API (reads $PORT when set, as Render does)
    python -m lattice mcp [--port 8000]      # the MCP tool server
    python -m lattice worker <role>          # orchestrator, investigator, verifier, action, echo
    python -m lattice seed [--if-empty]      # load a world and the committed replay recordings
"""

import argparse
import asyncio
import os
import sys

import redis
from neo4j import GraphDatabase

from lattice.config import ConfigError, load_settings

COMMANDS = ["check", "api", "mcp", "worker", "seed"]


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


def api(argv: list[str]) -> int:
    import uvicorn

    parser = argparse.ArgumentParser(prog="lattice api")
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104 - it runs in a container
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = parser.parse_args(argv)
    uvicorn.run("lattice.api.app:app", host=args.host, port=args.port, proxy_headers=True,
                forwarded_allow_ips="*")
    return 0


def mcp(argv: list[str]) -> int:
    from lattice.mcp_server.server import main as serve

    parser = argparse.ArgumentParser(prog="lattice mcp")
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104 - it runs in a container
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args(argv)
    serve(["--host", args.host, "--port", str(args.port)])
    return 0


def worker(argv: list[str]) -> int:
    from lattice.workers.main import main as run_worker

    run_worker(argv)
    return 0


def seed(argv: list[str]) -> int:
    from lattice.seed import seed as run_seed

    parser = argparse.ArgumentParser(prog="lattice seed")
    parser.add_argument("--world", choices=["fixture", "demo"], default="demo")
    parser.add_argument("--if-empty", action="store_true",
                        help="do nothing when the database already holds alerts")
    args = parser.parse_args(argv)
    return asyncio.run(run_seed(args.world, if_empty=args.if_empty))


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in COMMANDS:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    command, rest = args[0], args[1:]
    if command == "check":
        sys.exit(check())
    sys.exit({"api": api, "mcp": mcp, "worker": worker, "seed": seed}[command](rest))


if __name__ == "__main__":
    main()
