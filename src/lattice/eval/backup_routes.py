"""The numbers sheet for the freeze demo: the greedy circuit against the backup-aware search.

For every planted case in a world, scored offline on its planted edges plus seeded noise (the
evidence a careful investigator would cite, with distractions), it reports:

- the greedy circuit: size, sufficiency, and whether the rest of the evidence still flags
  (`redundant`), which the circuit alone does not show;
- the route search: how many independent routes it finds;
- freezes: of the accounts on the greedy circuit, how many a reader of the circuit alone would
  expect to stop the case (every one of them: removing any account removes circuit edges),
  against how many actually do once backup routes are counted;
- for showcase cases with planted routes and roles: whether each planted route was recovered and
  how many inferred roles match the answer key.

    uv run python -m lattice.eval.backup_routes --out docs/eval/backup-routes-demo-2026.md
"""

import argparse
import random
import sys
from pathlib import Path

from pydantic import BaseModel

from lattice.datagen.generator import DEMO_SEED, World, generate_world
from lattice.datagen.manifest import CaseRecord
from lattice.explain.circuit import find_circuit
from lattice.explain.routes import find_routes, freeze_whatif, infer_roles, touching
from lattice.graph.subgraph import EvidenceGraph
from lattice.ids import link_id
from lattice.scoring.scorer import Scorer

NOISE = 30


class CaseRow(BaseModel):
    case_id: str
    kind: str
    flagged: bool
    circuit_size: int
    sufficiency: float
    redundant: bool
    routes: int
    circuit_accounts: int  # accounts on the greedy circuit: each looks essential from it alone
    essential: int  # of those, how many really stop the case when frozen
    planted_routes: int | None = None
    routes_recovered: int | None = None
    roles_correct: int | None = None
    roles_inferred: int | None = None


def _edges(world: World, case: CaseRecord) -> list[str]:
    links = [link_id("USED_DEVICE", ad.account_id, ad.device_id)
             for ad in world.batch.account_devices if ad.device_id in case.device_ids]
    return [*case.transfer_ids, *links]


def measure(world: World, case: CaseRecord, scorer: Scorer, noise: list[str]) -> CaseRow:
    graph = EvidenceGraph.from_batch(world.batch, _edges(world, case) + noise)
    circuit = find_circuit(graph, scorer)
    if circuit.status != "circuit":
        return CaseRow(case_id=case.case_id, kind=case.kind, flagged=False, circuit_size=0,
                       sufficiency=0.0, redundant=False, routes=0, circuit_accounts=0,
                       essential=0)
    routes = find_routes(graph, scorer, first=circuit)
    on_circuit = sorted({a for t in graph.all_transfers if t.id in set(circuit.circuit_edges)
                         for a in (t.src, t.dst)})
    essential = sum(not freeze_whatif(graph, scorer, a).still_flagged for a in on_circuit
                    if touching(graph, a))
    row = CaseRow(case_id=case.case_id, kind=case.kind, flagged=True,
                  circuit_size=len(circuit.circuit_edges),
                  sufficiency=round(circuit.sufficiency_score, 3), redundant=circuit.redundant,
                  routes=len(routes), circuit_accounts=len(on_circuit), essential=essential)
    if case.routes:
        planted = [set(r) for r in case.routes]
        row.planted_routes = len(planted)
        row.routes_recovered = sum(any(set(r.edges) <= p for r in routes) for p in planted)
        roles = infer_roles(graph, routes)
        row.roles_inferred = len(roles)
        row.roles_correct = sum(case.roles.get(a) == role for a, role in roles.items())
    return row


def render(rows: list[CaseRow], seed: int) -> str:
    flagged = [r for r in rows if r.flagged]
    redundant = [r for r in flagged if r.redundant]
    looks = sum(r.circuit_accounts for r in flagged)
    real = sum(r.essential for r in flagged)
    showcase = [r for r in rows if r.planted_routes]
    size = sum(r.circuit_size for r in flagged) / max(len(flagged), 1)
    sufficiency = sum(r.sufficiency for r in flagged) / max(len(flagged), 1)
    lines = [
        f"# Backup routes: greedy circuit vs route search (demo world, seed {seed})",
        "",
        f"- Planted cases: {len(rows)}; flagged on their planted evidence plus {NOISE} noise "
        f"edges: {len(flagged)}.",
        f"- Mean greedy circuit: {size:.1f} edges, mean sufficiency {sufficiency:.2f}.",
        f"- Cases with a second body of evidence (`redundant`): {len(redundant)} of "
        f"{len(flagged)}. The circuit alone shows only one route for these.",
        f"- Freezes: {looks} accounts sit on a greedy circuit, so each looks essential from the "
        f"circuit alone. Counting backup routes, {real} of them really stop the case; "
        f"{looks - real} would leave it standing.",
    ]
    if showcase:
        lines.append(
            f"- Showcase cases with planted parallel routes: {len(showcase)}. Planted routes "
            f"recovered: {sum(r.routes_recovered or 0 for r in showcase)} of "
            f"{sum(r.planted_routes or 0 for r in showcase)}; inferred roles correct: "
            f"{sum(r.roles_correct or 0 for r in showcase)} of "
            f"{sum(r.roles_inferred or 0 for r in showcase)}.")
    lines += [
        "",
        "| Case | Kind | Circuit edges | Sufficiency | Redundant | Routes found | Accounts on "
        "circuit | Really essential | Planted routes recovered | Roles correct |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        recovered = (f"{r.routes_recovered} of {r.planted_routes}"
                     if r.planted_routes else "")
        roles = f"{r.roles_correct} of {r.roles_inferred}" if r.roles_inferred else ""
        lines.append(
            f"| {r.case_id} | {r.kind} | {r.circuit_size if r.flagged else 'not flagged'} | "
            f"{r.sufficiency:.2f} | {'yes' if r.redundant else 'no'} | {r.routes} | "
            f"{r.circuit_accounts} | {r.essential} | {recovered} | {roles} |")
    lines += [
        "",
        "Scored offline with the deterministic scorer, no model. Each case's evidence is its "
        f"planted edges plus {NOISE} random background transfers, seeded by case. A column for "
        "the research search (the backup-aware search on GPT-2) belongs here once it runs on "
        "these cases.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lattice.eval.backup_routes",
                                     description=__doc__.split("\n")[0])
    parser.add_argument("--seed", type=int, default=DEMO_SEED)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    world = generate_world(args.seed, "demo")
    scorer = Scorer()
    planted_edges = {t for c in world.manifest.cases for t in c.transfer_ids}
    background = sorted(t.id for t in world.batch.transfers if t.id not in planted_edges)
    rows = []
    for case in [c for c in world.manifest.cases if c.category == "planted"]:
        noise = random.Random(case.case_id).sample(background, NOISE)
        rows.append(measure(world, case, scorer, noise))
    sheet = render(rows, args.seed)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(sheet)
    print(sheet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
