"""Evaluation harness (U15, R21): every demo-world alert, both agent modes, one report.

    uv run python -m lattice.eval.harness --model scripted
    uv run python -m lattice.eval.harness --model google:gemini-flash-latest --price-in 0.3 \\
        --price-out 2.5

It runs alerts through the running stack (API, MCP server and workers), single-agent and
multi-agent on the same alerts, a few at a time, and writes the R21 report (`report.py`).

The demo world (seed 2026) is held out from the fixture world the scorer was tuned on. A full
run needs roughly 70 model requests per alert across both modes. When that exceeds today's
remaining quota (the free tier), it runs a seeded, stratified subset sized to the quota: one
alert from each kind in turn, injection pairs kept together. The same seed always picks the
same subset, and the report names it.
"""

import argparse
import asyncio
import json
import random
import re
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

import httpx

from lattice.config import Settings, load_settings
from lattice.datagen.generator import DEMO_SEED, World, generate_world
from lattice.datagen.manifest import CaseRecord, Manifest
from lattice.eval.fixture_check import (
    MAX_HYPOTHESES,
    NARRATOR_REQUESTS,
    ORCHESTRATOR_REQUESTS,
    CapReached,
    State,
    api_investigator,
    budget,
    expected_edges,
    release,
)
from lattice.eval.metrics import AlertOutcome
from lattice.eval.report import Pricing, Subset, render_report
from lattice.graph.client import GraphClient
from lattice.graph.loader import load_batch
from lattice.graph.schema import apply_schema

MODES = ("single", "orchestrated")
OUT_DIR = Path(__file__).resolve().parents[3] / "data" / "evaluation"
SUBSET_SEED = 21


# --- what to run -----------------------------------------------------------------------------


def all_alerts(world: World) -> list[AlertOutcome]:
    """Every alert in a generated world, with its role and the planted edges to recover."""
    return alerts_from_manifest(world.manifest, lambda case: expected_edges(world, case))


def alerts_from_manifest(
    manifest: Manifest, edges_of: Callable[[CaseRecord], list[str]] | None = None
) -> list[AlertOutcome]:
    """Every case in a manifest as an alert to run. Without `edges_of`, a case's expected
    edges are its transfers (enough for data without devices, such as Elliptic2)."""
    twins = {c.twin_case_id for c in manifest.cases if c.injected_transfer_id}
    alert_of = {c.case_id: c.alert_id for c in manifest.cases}
    out = []
    for case in sorted(manifest.cases, key=lambda c: c.case_id):
        role = ("injected" if case.injected_transfer_id
                else "twin" if case.case_id in twins else case.category)
        out.append(AlertOutcome(
            alert_id=case.alert_id, case_kind=case.kind, role=role,
            expected_suspicious=case.expected_verdict == "suspicious",
            expected_edges=edges_of(case) if edges_of else list(case.transfer_ids),
            twin_alert_id=alert_of.get(case.twin_case_id or ""),
        ))
    return out


def requests_per_alert(mode: str, settings: Settings) -> int:
    """Upper bound on model requests for one alert in one mode."""
    if mode == "single":
        return settings.investigation_step_budget + NARRATOR_REQUESTS
    return (ORCHESTRATOR_REQUESTS + MAX_HYPOTHESES * settings.investigation_step_budget
            + NARRATOR_REQUESTS)


def estimate(alerts: int, modes: tuple[str, ...], settings: Settings) -> int:
    return alerts * sum(requests_per_alert(m, settings) for m in modes)


def stratified_subset(alerts: list[AlertOutcome], size: int, seed: int) -> list[AlertOutcome]:
    """Up to `size` alerts: one per stratum in turn (seeded order), injection pairs together."""
    by_id = {a.alert_id: a for a in alerts}
    strata: dict[str, list[list[AlertOutcome]]] = {}
    for alert in alerts:
        if alert.role == "twin":
            continue  # travels with its injected partner
        unit = [alert] + ([by_id[alert.twin_alert_id]] if alert.role == "injected"
                          and alert.twin_alert_id in by_id else [])
        name = "injection pair" if alert.role == "injected" else f"{alert.role} {alert.case_kind}"
        strata.setdefault(name, []).append(unit)

    rng = random.Random(seed)
    for units in strata.values():
        rng.shuffle(units)
    order = sorted(strata)
    chosen: list[AlertOutcome] = []
    while any(strata[name] for name in order):
        for name in order:
            if strata[name] and len(chosen) + len(strata[name][0]) <= size:
                chosen.extend(strata[name].pop(0))
            elif strata[name]:
                strata[name].clear()  # this stratum's next unit no longer fits
    return chosen


def plan_run(alerts: list[AlertOutcome], modes: tuple[str, ...], settings: Settings,
             remaining: int | None, seed: int,
             case_room: int | None = None) -> tuple[list[AlertOutcome], Subset | None]:
    """All alerts when the request quota and the daily case cap allow; otherwise the largest
    stratified subset that fits both."""
    needed = estimate(len(alerts), modes, settings)
    limits = []
    if remaining is not None and needed > remaining:
        limits.append((remaining // estimate(1, modes, settings),
                       f"a full run needs about {needed} model requests and {remaining} "
                       "remained today"))
    cases = len(alerts) * len(modes)
    if case_room is not None and cases > case_room:
        limits.append((case_room // len(modes),
                       f"a full run starts {cases} cases and only {case_room} more may start "
                       "today (LATTICE_MAX_CASES_PER_DAY)"))
    if not limits:
        return alerts, None
    size, reason = min(limits)
    chosen = stratified_subset(alerts, size, seed)
    return chosen, Subset(seed=seed, of=len(alerts), reason=reason,
                          alert_ids=[a.alert_id for a in chosen])


# --- running ---------------------------------------------------------------------------------


def state_key(outcome: AlertOutcome) -> str:
    return f"{outcome.mode}:{outcome.alert_id}"


async def run_all(alerts: list[AlertOutcome], modes: tuple[str, ...], investigate,
                  state: State, concurrency: int) -> list[AlertOutcome]:
    """Each alert in each mode once, `concurrency` alerts at a time, saving as each finishes.

    An alert's modes run one after the other: an alert has at most one open case.
    """
    done = state.load()
    gate = asyncio.Semaphore(concurrency)

    async def one(alert: AlertOutcome) -> None:
        async with gate:
            for mode in modes:
                key = f"{mode}:{alert.alert_id}"
                if key in done:
                    continue
                outcome = await investigate(alert.model_copy(update={"mode": mode}), mode)
                state.save(outcome)
                done[key] = outcome
                print(f"{mode:<12} {alert.alert_id} {alert.role} {alert.case_kind}: "
                      f"{outcome.status or outcome.error}", flush=True)

    # One failure (the case cap, say) cancels the alerts still running; finished ones are saved.
    async with asyncio.TaskGroup() as group:
        for alert in alerts:
            group.create_task(one(alert))
    return [done[f"{m}:{a.alert_id}"] for a in alerts for m in modes]


# --- command line ----------------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()


async def main_async(args: argparse.Namespace) -> int:
    settings = load_settings()
    modes = tuple(args.modes)
    if args.manifest:
        # A world loaded elsewhere (an Elliptic2 slice): run its alerts against its labels.
        manifest = Manifest.model_validate_json(args.manifest.read_text())
        world, alerts = None, alerts_from_manifest(manifest)
        world_name = f"{manifest.world} (seed {manifest.seed}, from {args.manifest.name})"
        args.no_load = True
    else:
        world = generate_world(args.seed, "demo")
        alerts = all_alerts(world)
        world_name = f"demo world, seed {args.seed}"


    prefix = f"manifest-{_slug(args.manifest.stem)}" if args.manifest else f"demo-{args.seed}"
    label = f"{prefix}-{_slug(args.model)}-{'-'.join(modes)}"
    state = State(args.out_dir / f"{label}.json", key=state_key)
    if args.fresh and state.path.exists():
        state.path.unlink()
    finished = set(state.load())
    # A run keeps the subset it started with, so a resumed run finishes the same alerts.
    plan_path = state.path.with_suffix(".subset.json")
    if args.fresh and plan_path.exists():
        plan_path.unlink()
    if plan_path.exists():
        saved = json.loads(plan_path.read_text())
        subset = Subset(**saved) if saved else None
        chosen = [a for a in alerts if subset is None or a.alert_id in set(subset.alert_ids)]
    else:
        limits = {} if args.ignore_quota else await budget(args.api)
        # Alerts this run already finished cost nothing more.
        done = {key.split(":", 1)[1] for key in finished}
        planned, subset = plan_run([a for a in alerts if a.alert_id not in done], modes,
                                   settings, limits.get("remaining_today"), args.subset_seed,
                                   limits.get("case_room"))
        keep = done | {a.alert_id for a in planned}
        chosen = [a for a in alerts if a.alert_id in keep]
        if subset is not None:
            subset = Subset(seed=subset.seed, of=len(alerts), reason=subset.reason,
                            alert_ids=[a.alert_id for a in chosen])
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(asdict(subset) if subset else None))
    if subset is not None:
        print(f"running a stratified subset of {len(chosen)} of {len(alerts)} alerts, because "
              f"{subset.reason}")
    else:
        print(f"running all {len(alerts)} alerts in modes {', '.join(modes)}")

    concurrency = max(1, min(args.concurrency, settings.max_active_cases))
    token = settings.approver_token.get_secret_value()
    async with GraphClient.from_settings(settings) as graph:
        if not args.no_load and world is not None:
            await apply_schema(graph)
            await load_batch(graph, world.batch)
        async with httpx.AsyncClient(base_url=args.api, timeout=30) as http:
            for outcome in state.load().values():  # a stopped run may have left one open
                if outcome.case_id:
                    await release(http, outcome.case_id, token)
            runners = {m: api_investigator(http, graph, args.timeout, token, mode=m)
                       for m in modes}

            async def investigate(alert: AlertOutcome, mode: str) -> AlertOutcome:
                return await runners[mode](alert)

            try:
                outcomes = await run_all(chosen, modes, investigate, state, concurrency)
            except ExceptionGroup as group:
                cap, rest = group.split(CapReached)
                if cap is None or rest is not None:
                    raise
                print(f"stopped: {cap.exceptions[0]}. Finished alerts are saved; run again "
                      "to resume.", file=sys.stderr)
                return 3

    report = render_report(outcomes, model=args.model, world=world_name,
                           modes=modes, subset=subset,
                           pricing=Pricing(args.price_in, args.price_out))
    path = args.out_dir / f"{label}.md"
    path.write_text(report)
    print(report)
    print(f"report written to {path}")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="lattice.eval.harness",
                                     description=__doc__.split("\n")[0])
    parser.add_argument("--model", default=None,
                        help="the model the workers run, for the report (default LATTICE_MODEL)")
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    parser.add_argument("--seed", type=int, default=DEMO_SEED, help="world seed")
    parser.add_argument("--manifest", type=Path, default=None,
                        help="run the alerts of an already loaded world, such as an Elliptic2 "
                             "slice's manifest, instead of the demo world")
    parser.add_argument("--subset-seed", type=int, default=SUBSET_SEED)
    parser.add_argument("--concurrency", type=int, default=2,
                        help="alerts in flight at once (capped by LATTICE_MAX_ACTIVE_CASES)")
    parser.add_argument("--api", default="http://localhost:8080")
    parser.add_argument("--timeout", type=float, default=600, help="seconds per case")
    parser.add_argument("--price-in", type=float, default=0.0,
                        help="price per million input tokens, for cost per case")
    parser.add_argument("--price-out", type=float, default=0.0,
                        help="price per million output tokens")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--fresh", action="store_true", help="discard saved progress first")
    parser.add_argument("--no-load", action="store_true", help="the world is already loaded")
    parser.add_argument("--ignore-quota", action="store_true",
                        help="run every alert even if the estimate exceeds today's quota")
    args = parser.parse_args(argv)
    args.model = args.model or load_settings().model
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
