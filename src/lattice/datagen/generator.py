"""Assemble a complete synthetic world: background, planted cases, decoys, injections, alerts."""

import json
import random
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from lattice.datagen import decoys, typologies
from lattice.datagen.alerts import raise_alert
from lattice.datagen.background import build_background
from lattice.datagen.builder import REPORTING_THRESHOLD, WINDOW_START, Pattern, WorldBuilder, days
from lattice.datagen.injection import inject
from lattice.datagen.manifest import CaseRecord, Manifest
from lattice.graph.loader import GraphBatch

FIXTURE_SEED = 7
DEMO_SEED = 2026

WorldSize = Literal["fixture", "demo"]


@dataclass(frozen=True)
class SizeSpec:
    persons: int
    businesses: int
    per_typology: int
    per_decoy: int
    injected_planted: int
    injected_decoys: int


SIZES: dict[str, SizeSpec] = {
    "fixture": SizeSpec(persons=60, businesses=8, per_typology=2, per_decoy=2,
                        injected_planted=1, injected_decoys=1),
    "demo": SizeSpec(persons=6_000, businesses=300, per_typology=6, per_decoy=6,
                     injected_planted=3, injected_decoys=3),
}


class World(BaseModel):
    batch: GraphBatch
    manifest: Manifest

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), indent=1, sort_keys=True) + "\n"


def generate_world(seed: int, size: WorldSize) -> World:
    spec = SIZES[size]
    rng = random.Random(seed)
    b = WorldBuilder(seed)
    build_background(b, random.Random(rng.getrandbits(64)), spec.persons, spec.businesses)

    jobs = [("planted", fn) for fn in typologies.ALL for _ in range(spec.per_typology)]
    jobs += [("decoy", fn) for fn in decoys.ALL for _ in range(spec.per_decoy)]
    injected = set(_pick(rng, jobs, "planted", spec.injected_planted))
    injected |= set(_pick(rng, jobs, "decoy", spec.injected_decoys))

    cases: list[CaseRecord] = []
    counters: dict[str, int] = {}
    for index, (category, fn) in enumerate(jobs):
        case_seed = rng.getrandbits(64)
        start = WINDOW_START + days(rng.uniform(5, 70))
        n = counters[fn.__name__] = counters.get(fn.__name__, 0) + 1
        case_id = f"{category}-{fn.__name__}-{n:02d}"

        pattern = fn(b, random.Random(case_seed), start)
        record = _record(b, case_id, category, pattern)
        cases.append(record)
        if index in injected:
            # Same seed and start reproduce the same structure on fresh accounts.
            twin_pattern = fn(b, random.Random(case_seed), start)
            twin = _record(b, f"{case_id}-twin", category, twin_pattern)
            record.injected_transfer_id = inject(b, random.Random(case_seed), pattern)
            record.twin_case_id, twin.twin_case_id = twin.case_id, record.case_id
            cases.append(twin)

    manifest = Manifest(
        world=size, seed=seed, reporting_threshold=REPORTING_THRESHOLD, cases=cases
    )
    return World(batch=b.batch, manifest=manifest)


def _pick(rng: random.Random, jobs, category: str, count: int) -> list[int]:
    indexes = [i for i, (c, _) in enumerate(jobs) if c == category]
    return rng.sample(indexes, count)


def _record(b: WorldBuilder, case_id: str, category: str, pattern: Pattern) -> CaseRecord:
    alert = raise_alert(b, pattern)
    return CaseRecord(
        case_id=case_id,
        category=category,
        kind=pattern.kind,
        expected_verdict="suspicious" if category == "planted" else "benign",
        seed_account_id=pattern.seed_account_id,
        alert_id=alert.id,
        account_ids=pattern.account_ids,
        transfer_ids=pattern.transfer_ids,
        device_ids=pattern.device_ids,
    )
