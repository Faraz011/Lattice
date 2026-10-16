"""Pre-submission metrics check (U19): the Success Criteria, measured through the full pipeline.

It runs 12 stratified alerts from a held-out world through the running stack (API, MCP server
and workers) in multi-agent mode, then scores the outcomes against the manifest:

- one planted case per typology (7);
- one decoy per kind (3);
- one prompt-injection pair (2).

The held-out world uses a seed other than the fixture world the scorer was tuned on.

    uv run python -m lattice.eval.fixture_check --model scripted
    uv run python -m lattice.eval.fixture_check --model google:gemini-flash-latest

Before starting, it estimates the model requests it needs and refuses when today's remaining
quota is smaller. Each finished alert is saved straight away, so an interrupted or
quota-limited run resumes where it stopped and never re-spends a completed alert.
"""

import argparse
import asyncio
import json
import re
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
import redis.asyncio as redis

from lattice.config import Settings, load_settings
from lattice.datagen.generator import World, generate_world
from lattice.datagen.manifest import CaseRecord
from lattice.eval.metrics import AlertOutcome, compute, render
from lattice.graph.client import GraphClient
from lattice.graph.loader import load_batch
from lattice.graph.schema import apply_schema
from lattice.ids import link_id
from lattice.queue.jobs import Keys
from lattice.queue.ratelimit import RateLimiter

HELD_OUT_SEED = 4242
OUT_DIR = Path(__file__).resolve().parents[3] / "data" / "fixture-check"
FINAL = {"awaiting_approval", "needs_review", "closed_no_action", "actioned", "rejected"}

# Upper bounds on model requests per alert, from the step budgets each role runs with.
ORCHESTRATOR_REQUESTS = 3
MAX_HYPOTHESES = 4
NARRATOR_REQUESTS = 4  # two attempts of up to two requests


class QuotaShortfall(RuntimeError):
    """The check would need more model requests than today's remaining quota."""


class CapReached(RuntimeError):
    """The API refused a new investigation (case caps); resume later."""


Investigate = Callable[[AlertOutcome], Awaitable[AlertOutcome]]


# --- selection -------------------------------------------------------------------------------


def expected_edges(world: World, case: CaseRecord) -> list[str]:
    links = [link_id("USED_DEVICE", ad.account_id, ad.device_id)
             for ad in world.batch.account_devices if ad.device_id in case.device_ids]
    return [*case.transfer_ids, *links]


def select_alerts(world: World) -> list[AlertOutcome]:
    """Seven planted typologies, three decoy kinds and one injection pair, in a fixed order."""
    plain = [c for c in world.manifest.cases
             if not c.injected_transfer_id and not c.twin_case_id]
    chosen: list[tuple[CaseRecord, str]] = []
    for category, role in (("planted", "planted"), ("decoy", "decoy")):
        seen: set[str] = set()
        for case in sorted(plain, key=lambda c: c.case_id):
            if case.category == category and case.kind not in seen:
                seen.add(case.kind)
                chosen.append((case, role))
    injected = sorted((c for c in world.manifest.cases if c.injected_transfer_id),
                      key=lambda c: c.case_id)
    by_id = {c.case_id: c for c in world.manifest.cases}
    if injected:
        twin = by_id[injected[0].twin_case_id]
        chosen += [(injected[0], "injected"), (twin, "twin")]

    alert_of = {case.case_id: case.alert_id for case, _ in chosen}
    return [
        AlertOutcome(
            alert_id=case.alert_id, case_kind=case.kind, role=role,
            expected_suspicious=case.expected_verdict == "suspicious",
            expected_edges=expected_edges(world, case),
            twin_alert_id=alert_of.get(case.twin_case_id or ""),
        )
        for case, role in chosen
    ]


# --- budget ----------------------------------------------------------------------------------


def estimate_requests(alerts: int, settings: Settings) -> int:
    per_alert = (ORCHESTRATOR_REQUESTS + MAX_HYPOTHESES * settings.investigation_step_budget
                 + NARRATOR_REQUESTS)
    return alerts * per_alert


def check_quota(estimate: int, remaining: int | None) -> None:
    if remaining is not None and estimate > remaining:
        raise QuotaShortfall(
            f"the check needs up to {estimate} model requests but only {remaining} remain "
            f"today ({estimate - remaining} short). Run it tomorrow or raise "
            "LATTICE_LLM_REQUESTS_PER_DAY; finished alerts are kept."
        )


# --- resumable state -------------------------------------------------------------------------


class State:
    """Finished alerts, one JSON file per run label, rewritten after every alert."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, AlertOutcome]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text())
        return {k: AlertOutcome.model_validate(v) for k, v in raw.items()}

    def save(self, outcome: AlertOutcome) -> None:
        done = self.load()
        done[outcome.alert_id] = outcome
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({k: v.model_dump(mode="json") for k, v in done.items()},
                                        indent=1))


async def run_alerts(alerts: list[AlertOutcome], investigate: Investigate,
                     state: State) -> list[AlertOutcome]:
    """Investigate every alert not already finished, saving each as it completes."""
    done = state.load()
    for alert in alerts:
        if alert.alert_id in done:
            continue
        print(f"investigating {alert.alert_id} ({alert.role} {alert.case_kind})", flush=True)
        outcome = await investigate(alert)
        state.save(outcome)
        done[alert.alert_id] = outcome
        print(f"  -> {outcome.status or outcome.error}", flush=True)
    return [done[a.alert_id] for a in alerts]


# --- one alert through the running stack -----------------------------------------------------


async def release(http: httpx.AsyncClient, case_id: str, token: str) -> None:
    """Close a measured case so it stops counting against the open-case cap.

    A flagged case stays open while it waits for a person, so twelve alerts would pass the
    default cap of five. Its proposed action is rejected, or its review cleared; the outcome
    was recorded before this runs.
    """
    headers = {"X-Approver-Token": token, "X-Approver-Name": "metrics check"}
    body = (await http.get(f"/cases/{case_id}")).json()
    status = body["case"]["status"]
    if status == "awaiting_approval":
        for action in body["actions"]:
            if action["status"] == "proposed":
                await http.post(f"/actions/{action['id']}/reject", headers=headers,
                                json={"reason": "closed by the metrics check"})
    elif status == "needs_review":
        await http.post(f"/cases/{case_id}/clear", headers=headers)


async def ledger_ids(graph: GraphClient, case_id: str) -> set[str]:
    rows = await graph.read(
        "MATCH (l:LedgerEntry {case_id: $c}) RETURN l.node_ids AS n, l.rel_ids AS r", c=case_id)
    return {i for row in rows for i in [*(row["n"] or []), *(row["r"] or [])]}


def api_investigator(http: httpx.AsyncClient, graph: GraphClient, timeout_s: float,
                     token: str) -> Investigate:
    async def investigate(alert: AlertOutcome) -> AlertOutcome:
        outcome = await _measure(alert)
        if outcome.case_id:
            await release(http, outcome.case_id, token)
        return outcome

    async def _measure(alert: AlertOutcome) -> AlertOutcome:
        started = time.monotonic()
        response = await http.post(f"/alerts/{alert.alert_id}/investigate",
                                   json={"mode": "orchestrated"})
        if response.status_code == 429:
            raise CapReached(response.json().get("detail", "case cap reached"))
        response.raise_for_status()
        case_id = response.json()["case"]["id"]

        case: dict = {}
        while time.monotonic() - started < timeout_s:
            case = (await http.get(f"/cases/{case_id}")).json()["case"]
            if case["status"] in FINAL:
                break
            await asyncio.sleep(3)
        seconds = time.monotonic() - started
        if case.get("status") not in FINAL or not case.get("verdict"):
            return alert.model_copy(update={
                "case_id": case_id, "status": case.get("status"), "seconds": seconds,
                "error": f"no verdict after {timeout_s:.0f}s"})

        verdict = case["verdict"]
        circuit = (case.get("circuit") or {}).get("circuit") or {}
        cited = {i for c in verdict["claims"] for i in [*c["rel_ids"], *c["node_ids"]]}
        ledgered = await ledger_ids(graph, case_id)
        return alert.model_copy(update={
            "case_id": case_id,
            "status": case["status"],
            "suspicious": verdict["suspicious"],
            "typology": verdict["typology"],
            "score": verdict["score"],
            "circuit_edges": circuit.get("circuit_edges", []),
            "supporting_edges": circuit.get("supporting_edges", []),
            "sufficient": (circuit["sufficiency_score"] >= circuit["threshold"]
                           if circuit.get("status") == "circuit" else None),
            "comprehensive": circuit.get("comprehensive"),
            "unledgered_ids": sorted(cited - ledgered),
            "seconds": seconds,
        })

    return investigate


# --- command line ----------------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()


async def main_async(args: argparse.Namespace) -> int:
    settings = load_settings()
    world = generate_world(args.seed, "fixture")
    alerts = select_alerts(world)
    label = f"seed-{args.seed}-{_slug(args.model)}"
    state = State(args.out_dir / f"{label}.json")
    if args.fresh and state.path.exists():
        state.path.unlink()
    pending = [a for a in alerts if a.alert_id not in state.load()]

    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    limiter = RateLimiter(client, Keys(settings.redis_namespace).limiter(),
                          settings.llm_requests_per_minute, settings.llm_requests_per_day)
    estimate = estimate_requests(len(pending), settings)
    remaining = await limiter.remaining_today()
    await client.aclose()
    print(f"{len(alerts)} alerts, {len(pending)} still to run; up to {estimate} model requests "
          f"needed, {'no daily cap' if remaining is None else f'{remaining} remain today'}")
    try:
        check_quota(estimate, remaining)
    except QuotaShortfall as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return 2

    async with GraphClient.from_settings(settings) as graph:
        if pending and not args.no_load:
            await apply_schema(graph)
            await load_batch(graph, world.batch)  # idempotent; a separate component of the graph
        token = settings.approver_token.get_secret_value()
        async with httpx.AsyncClient(base_url=args.api, timeout=30) as http:
            for done in state.load().values():  # a run stopped before releasing its last case
                if done.case_id:
                    await release(http, done.case_id, token)
            try:
                outcomes = await run_alerts(
                    alerts, api_investigator(http, graph, args.timeout, token), state)
            except CapReached as exc:
                print(f"stopped: {exc}. Finished alerts are saved; run again to resume.",
                      file=sys.stderr)
                return 3

    metrics = compute(outcomes)
    report = render(metrics, outcomes, f"Pre-submission metrics check ({args.model})", [
        f"Held-out fixture world, seed {args.seed} (the scorer was tuned on seed 7).",
        f"Model: `{args.model}`. Multi-agent mode, through the running API and workers.",
        "Rates use the 7 planted and 3 decoy alerts; the injection pair is checked for "
        "agreement. A case with no verdict counts as not flagged.",
    ])
    path = args.out_dir / f"{label}.md"
    path.write_text(report)
    print(report)
    print(f"report written to {path}")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="lattice.eval.fixture_check",
                                     description=__doc__.split("\n")[0])
    parser.add_argument("--model", default=None,
                        help="the model the workers run, for the report (default LATTICE_MODEL)")
    parser.add_argument("--seed", type=int, default=HELD_OUT_SEED)
    parser.add_argument("--api", default="http://localhost:8080")
    parser.add_argument("--timeout", type=float, default=600, help="seconds per alert")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--fresh", action="store_true", help="discard saved progress first")
    parser.add_argument("--no-load", action="store_true", help="the world is already loaded")
    args = parser.parse_args(argv)
    args.model = args.model or load_settings().model
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
