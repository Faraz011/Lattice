"""Load a bounded slice of Elliptic2 into the Lattice schema (U16, R22).

Elliptic2 (Bellei et al. 2024) is a Bitcoin graph: about 49M clusters (wallet groupings) and
196M flows between them, with about 122K labelled subgraphs, each licit or suspicious. The files
come from https://www.elliptic.co/elliptic2 (registration required):

- connected_components.csv: ccId, ccLabel (licit | suspicious)
- nodes.csv: clId, ccId (which clusters make up each labelled subgraph)
- edges.csv: clId1, clId2, ... (flows inside the labelled subgraphs)
- background_nodes.csv, background_edges.csv: the whole graph (clId1, clId2, ...); features
  are anonymised

The slice is a seeded, label-balanced sample of labelled subgraphs plus each member's flows in
the background graph (one hop, capped per cluster). The files are streamed, so memory follows
the slice, not the 196M-edge background.

How it maps:

- A cluster becomes an Account (kind `cluster`) owned by its own Customer (kind `entity`).
- A flow becomes a TRANSFER with no amount and no timestamp: Elliptic2's edge features are
  anonymised. Detectors that need amounts, times or devices contribute zero, so the risk scorer
  will not flag these cases. Structural tools (neighbours, paths, cycles, PageRank, communities,
  blast radius) work as usual.
- Each sampled subgraph raises one Alert on its best-connected member. The alert text never
  carries the label.
- The labels become the manifest: suspicious subgraphs are `planted` and licit ones `decoy`,
  with the subgraph's internal flows as the expected edges.

    uv run python -m lattice.ingest.elliptic2 --dir dataset --subgraphs 100 --load
"""

import argparse
import asyncio
import csv
import hashlib
import random
import sys
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from lattice.datagen.manifest import CaseRecord, Manifest
from lattice.graph.loader import Account, Alert, Customer, GraphBatch, Transfer

WORLD = "elliptic2"
CASE_KIND = "elliptic2_subgraph"
OUT_DIR = Path(__file__).resolve().parents[3] / "data"


@dataclass(frozen=True)
class Slice:
    batch: GraphBatch
    manifest: Manifest


# IDs carry "ell": `l` is not a hex digit, so they can never collide with generated IDs
# (a prefix and 16 hex digits) and are easy to pick out.
def account_id(cluster: str) -> str:
    return f"acct_ell{cluster}"


def customer_id(cluster: str) -> str:
    return f"cust_ell{cluster}"


def alert_id(component: str) -> str:
    return f"alert_ell{component}"


def transfer_id(src: str, dst: str) -> str:
    return "tx_ell" + hashlib.sha256(f"elliptic2:{src}:{dst}".encode()).hexdigest()[:16]


def _rows(path: Path) -> Iterator[list[str]]:
    """Data rows of a CSV, header skipped. Columns are read by position, as the official
    preprocessing code does."""
    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        yield from reader


def choose_subgraphs(labels: dict[str, str], count: int, seed: int) -> list[str]:
    """Up to `count` subgraph IDs, half suspicious and half licit where the data allows."""
    by_label: dict[str, list[str]] = defaultdict(list)
    for cc, label in labels.items():
        by_label[label].append(cc)
    rng = random.Random(seed)
    for ccs in by_label.values():
        ccs.sort()
        rng.shuffle(ccs)
    suspicious, licit = by_label.get("suspicious", []), by_label.get("licit", [])
    want_suspicious = min(len(suspicious), count // 2)
    chosen = suspicious[:want_suspicious] + licit[:count - want_suspicious]
    return sorted(chosen)


def build_slice(directory: Path, subgraphs: int = 100, neighbors: int = 25,
                seed: int = 2) -> Slice:
    components = _rows(directory / "connected_components.csv")
    labels = {row[0]: row[1].strip().lower() for row in components}
    chosen = set(choose_subgraphs(labels, subgraphs, seed))

    members: dict[str, set[str]] = defaultdict(set)  # ccId -> clusters
    for cluster, cc, *_ in _rows(directory / "nodes.csv"):
        if cc in chosen:
            members[cc].add(cluster)
    in_slice = {c for clusters in members.values() for c in clusters}
    cc_of: dict[str, set[str]] = defaultdict(set)
    for cc, clusters in members.items():
        for cluster in clusters:
            cc_of[cluster].add(cc)

    flows: dict[tuple[str, str], None] = {}  # ordered, deduplicated
    internal: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for src, dst, *_ in _rows(directory / "edges.csv"):
        for cc in cc_of.get(src, set()) & cc_of.get(dst, set()):
            internal[cc].append((src, dst))
            flows[(src, dst)] = None

    # The neighbourhood: each member's flows in the background graph, capped per member.
    taken: dict[str, int] = defaultdict(int)
    for src, dst, *_ in _rows(directory / "background_edges.csv"):
        anchor = src if src in in_slice else dst if dst in in_slice else None
        if anchor is None or (src, dst) in flows or taken[anchor] >= neighbors:
            continue
        taken[anchor] += 1
        flows[(src, dst)] = None

    clusters = sorted({c for pair in flows for c in pair} | in_slice)
    batch = GraphBatch(
        customers=[Customer(id=customer_id(c), name=f"Elliptic2 cluster {c}", kind="entity",
                            country="") for c in clusters],
        accounts=[Account(id=account_id(c), customer_id=customer_id(c), kind="cluster",
                          created_at=None, country="") for c in clusters],
        transfers=[Transfer(id=transfer_id(s, d), src=account_id(s), dst=account_id(d),
                            amount=None, ts=None, channel="bitcoin") for s, d in flows],
    )

    cases, alerts = [], []
    for cc in sorted(members):
        edges = internal.get(cc, [])
        degree: dict[str, int] = defaultdict(int)
        for s, d in edges:
            degree[s] += 1
            degree[d] += 1
        seed_cluster = min(members[cc], key=lambda c: (-degree[c], c))
        alerts.append(Alert(id=alert_id(cc), seed_account_id=account_id(seed_cluster),
                            reason=f"cluster group of {len(members[cc])} referred for review",
                            ts=None))
        suspicious = labels[cc] == "suspicious"
        cases.append(CaseRecord(
            case_id=f"elliptic2-{cc}", category="planted" if suspicious else "decoy",
            kind=CASE_KIND, expected_verdict="suspicious" if suspicious else "benign",
            seed_account_id=account_id(seed_cluster), alert_id=alert_id(cc),
            account_ids=sorted(account_id(c) for c in members[cc]),
            transfer_ids=list(dict.fromkeys(transfer_id(s, d) for s, d in edges)),
        ))
    batch.alerts = alerts
    manifest = Manifest(world=WORLD, seed=seed, reporting_threshold=0.0, cases=cases)
    return Slice(batch=batch, manifest=manifest)


async def _load(slice_: Slice) -> None:
    from lattice.config import load_settings
    from lattice.graph.client import GraphClient
    from lattice.graph.loader import load_batch
    from lattice.graph.schema import apply_schema

    async with GraphClient.from_settings(load_settings()) as graph:
        await apply_schema(graph)
        await load_batch(graph, slice_.batch)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lattice.ingest.elliptic2",
                                     description=__doc__.split("\n")[0])
    parser.add_argument("--dir", type=Path, required=True, help="the unzipped Elliptic2 folder")
    parser.add_argument("--subgraphs", type=int, default=100)
    parser.add_argument("--neighbors", type=int, default=25,
                        help="background flows kept per member cluster")
    parser.add_argument("--seed", type=int, default=2)
    parser.add_argument("--out", type=Path, default=OUT_DIR / "elliptic2-manifest.json")
    parser.add_argument("--load", action="store_true", help="load the slice into Neo4j")
    args = parser.parse_args(argv)

    slice_ = build_slice(args.dir, args.subgraphs, args.neighbors, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(slice_.manifest.to_json())
    planted = sum(c.category == "planted" for c in slice_.manifest.cases)
    print(f"slice: {len(slice_.manifest.cases)} subgraphs ({planted} suspicious), "
          f"{len(slice_.batch.accounts)} clusters, {len(slice_.batch.transfers)} flows; "
          f"manifest written to {args.out} (keep it out of Neo4j)")
    if args.load:
        asyncio.run(_load(slice_))
        print("loaded into Neo4j")
    return 0


if __name__ == "__main__":
    sys.exit(main())
