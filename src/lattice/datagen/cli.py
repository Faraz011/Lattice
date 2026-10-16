"""Generate a synthetic world, write its manifest, and optionally load it into Neo4j.

    python -m lattice.datagen.cli --world demo --load
    python -m lattice.datagen.cli --world fixture --seed 99 --load --wipe
    python -m lattice.datagen.cli --write-fixture
"""

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

from lattice.config import load_settings
from lattice.datagen.generator import DEMO_SEED, FIXTURE_SEED, World, generate_world
from lattice.graph.client import GraphClient
from lattice.graph.loader import load_batch
from lattice.graph.schema import DATA_LABELS, apply_schema

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "small_world.json"
WIPE_CHUNK = 10_000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lattice.datagen.cli", description=__doc__.split("\n")[0])
    parser.add_argument("--world", choices=["fixture", "demo"], default="fixture")
    parser.add_argument("--seed", type=int, help="defaults: fixture 7, demo 2026")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--load", action="store_true", help="load the world into Neo4j")
    parser.add_argument(
        "--wipe", action="store_true", help="delete existing transaction data before loading"
    )
    parser.add_argument(
        "--write-fixture", action="store_true", help=f"rewrite {FIXTURE_PATH.name} and exit"
    )
    args = parser.parse_args(argv)

    if args.write_fixture:
        FIXTURE_PATH.write_text(generate_world(FIXTURE_SEED, "fixture").to_json())
        print(f"wrote {FIXTURE_PATH}")
        return 0

    default_seed = DEMO_SEED if args.world == "demo" else FIXTURE_SEED
    seed = args.seed if args.seed is not None else default_seed
    world = generate_world(seed, args.world)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out_dir / f"{args.world}-{seed}-manifest.json"
    manifest_path.write_text(world.manifest.to_json())

    batch = world.batch
    print(
        f"generated {args.world} world seed={seed}: {len(batch.customers)} customers, "
        f"{len(batch.accounts)} accounts, {len(batch.devices)} devices, "
        f"{len(batch.transfers)} transfers, {len(batch.alerts)} alerts"
    )
    print(f"manifest written to {manifest_path} (keep it out of Neo4j)")

    if args.load:
        return asyncio.run(_load_and_verify(world, wipe=args.wipe))
    return 0


async def _load_and_verify(world: World, wipe: bool) -> int:
    async with GraphClient.from_settings(load_settings()) as graph:
        await apply_schema(graph)
        if wipe:
            await _wipe(graph)
        await load_batch(graph, world.batch)
        return await _verify(graph, world)


async def _wipe(graph: GraphClient) -> None:
    labels = " OR ".join(f"n:{label}" for label in DATA_LABELS)
    deleted = 0
    while True:
        rows = await graph.write(
            f"MATCH (n) WHERE {labels} WITH n LIMIT {WIPE_CHUNK} DETACH DELETE n "
            "RETURN count(*) AS n"
        )
        if rows[0]["n"] == 0:
            break
        deleted += rows[0]["n"]
    print(f"wiped {deleted} existing transaction nodes")


async def _verify(graph: GraphClient, world: World) -> int:
    """Count each kind's manifest transfers and accounts in Neo4j and compare."""
    expected: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    for case in world.manifest.cases:
        row = expected[(case.category, case.kind)]
        row[0] += 1
        row[1] += len(case.transfer_ids)
        row[2] += len(case.account_ids)

    print(f"\n{'category':<8} {'kind':<20} {'cases':>5} {'transfers':>14} {'accounts':>14}")
    ok = True
    for (category, kind), (n_cases, n_tx, n_acct) in sorted(expected.items()):
        cases = [c for c in world.manifest.cases if (c.category, c.kind) == (category, kind)]
        tx_ids = [t for c in cases for t in c.transfer_ids]
        acct_ids = [a for c in cases for a in c.account_ids]
        found_tx = (await graph.read(
            "MATCH ()-[t:TRANSFER]->() WHERE t.id IN $ids RETURN count(t) AS n", ids=tx_ids
        ))[0]["n"]
        found_acct = (await graph.read(
            "MATCH (a:Account) WHERE a.id IN $ids RETURN count(a) AS n", ids=acct_ids
        ))[0]["n"]
        match = found_tx == n_tx and found_acct == n_acct
        ok &= match
        print(
            f"{category:<8} {kind:<20} {n_cases:>5} {f'{found_tx}/{n_tx}':>14} "
            f"{f'{found_acct}/{n_acct}':>14} {'ok' if match else 'MISMATCH'}"
        )

    n_alerts = (await graph.read(
        "MATCH (a:Alert) WHERE a.id IN $ids RETURN count(a) AS n",
        ids=[a.id for a in world.batch.alerts],
    ))[0]["n"]
    alerts_ok = n_alerts == len(world.batch.alerts)
    print(f"\nalerts {n_alerts}/{len(world.batch.alerts)} {'ok' if alerts_ok else 'MISMATCH'}")
    print("counts match the manifest" if ok and alerts_ok else "COUNTS DO NOT MATCH THE MANIFEST")
    return 0 if ok and alerts_ok else 1


if __name__ == "__main__":
    sys.exit(main())
