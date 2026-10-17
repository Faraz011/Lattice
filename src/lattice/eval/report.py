"""The R21 evaluation report: the Success Criteria and the run statistics, per agent mode.

R21 asks for decision accuracy, recall of planted edges by supporting evidence, sufficiency and
comprehensiveness rates, the hallucinated-citation rate, tool-call statistics, and cost and
latency per case. Each appears per mode, so single-agent and multi-agent runs on the same alerts
can be compared side by side.
"""

import statistics
from collections import Counter
from dataclasses import dataclass

from lattice.eval.metrics import AlertOutcome, Metrics, compute


@dataclass(frozen=True)
class Subset:
    seed: int
    of: int
    reason: str  # which limit a full run would exceed
    alert_ids: list[str]


@dataclass(frozen=True)
class Pricing:
    per_million_in: float = 0.0
    per_million_out: float = 0.0

    @property
    def known(self) -> bool:
        return bool(self.per_million_in or self.per_million_out)

    def cost(self, outcome: AlertOutcome) -> float:
        return (outcome.total("input_tokens") * self.per_million_in
                + outcome.total("output_tokens") * self.per_million_out) / 1_000_000


@dataclass(frozen=True)
class ModeStats:
    mode: str
    cases: int
    metrics: Metrics
    accuracy: float | None
    citing_cases: int
    hallucinating_cases: int
    rejected_citations: int
    tool_calls: Counter
    requests_by_role: Counter
    cached: int
    requests: list[int]
    input_tokens: list[int]
    output_tokens: list[int]
    seconds: list[float]
    costs: list[float]


def mode_stats(mode: str, outcomes: list[AlertOutcome], pricing: Pricing) -> ModeStats:
    judged = [o for o in outcomes if o.role in ("planted", "decoy")]
    correct = sum(o.flagged == o.expected_suspicious for o in judged)
    tools: Counter = Counter()
    by_role: Counter = Counter()
    for o in outcomes:
        tools.update(o.tool_calls)
        for role, counts in o.usage.items():
            by_role[role] += counts.get("requests", 0)
    return ModeStats(
        mode=mode,
        cases=len(outcomes),
        metrics=compute(outcomes),
        accuracy=correct / len(judged) if judged else None,
        citing_cases=sum(o.suspicious is not None for o in outcomes),
        hallucinating_cases=sum(o.rejected_citations > 0 for o in outcomes),
        rejected_citations=sum(o.rejected_citations for o in outcomes),
        tool_calls=tools,
        requests_by_role=by_role,
        cached=sum(o.total("cached") for o in outcomes),
        requests=[o.total("requests") for o in outcomes],
        input_tokens=[o.total("input_tokens") for o in outcomes],
        output_tokens=[o.total("output_tokens") for o in outcomes],
        seconds=[o.seconds for o in outcomes if o.seconds is not None],
        costs=[pricing.cost(o) for o in outcomes],
    )


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _spread(values: list[float], fmt: str = "{:.0f}") -> str:
    """mean / median / max, or n/a."""
    if not values:
        return "n/a"
    return " / ".join(fmt.format(v) for v in
                      (statistics.mean(values), statistics.median(values), max(values)))


def _row(label: str, cells: list[str]) -> str:
    return f"| {label} | " + " | ".join(cells) + " |"


def render_report(outcomes: list[AlertOutcome], *, model: str, world: str,
                  modes: tuple[str, ...], subset: Subset | None, pricing: Pricing) -> str:
    stats = [mode_stats(m, [o for o in outcomes if o.mode == m], pricing) for m in modes]
    alerts = sorted({o.alert_id for o in outcomes})
    lines = [f"# Evaluation report ({model})", "",
             f"- {world}; {len(alerts)} alerts, modes: {', '.join(modes)}.",
             f"- Model: `{model}`. Each case ran through the API, MCP server and workers."]
    if subset is None:
        lines.append("- Every alert in the world was run.")
    else:
        lines.append(
            f"- Subset: {len(subset.alert_ids)} of {subset.of} alerts, stratified by kind with "
            f"seed {subset.seed}, because {subset.reason}. The alerts are listed at the end.")
    lines.append("- Rates use planted and decoy alerts; injection pairs are checked for "
                 "agreement. A case with no verdict counts as not flagged.")

    header = "| Criterion | " + " | ".join(s.mode for s in stats) + " | Target |"
    divider = "| --- |" + " --- |" * (len(stats) + 1)
    lines += ["", "## Success Criteria", "", header, divider]
    for i, target in enumerate(stats[0].metrics.targets):
        cells = []
        for s in stats:
            t = s.metrics.targets[i]
            value = t.value if isinstance(t.value, int) else _pct(t.value)
            cells.append(f"{value} ({t.verdict})")
        lines.append(_row(target.name, cells) + f" {target.goal} |")

    lines += ["", "## Run statistics (R21)", "", header.replace("Target", "Notes"), divider]
    lines += [
        _row("Decision accuracy", [_pct(s.accuracy) for s in stats]) + " planted flagged and "
        "decoys not flagged |",
        _row("Sufficient circuits", [f"{s.metrics.sufficient} of {s.metrics.circuits}"
                                     for s in stats]) + " circuit alone keeps the verdict |",
        _row("Comprehensive circuits", [f"{s.metrics.comprehensive} of {s.metrics.circuits}"
                                        for s in stats]) + " rest falls below threshold |",
        _row("Cases citing IDs no tool returned",
             [f"{s.hallucinating_cases} of {s.citing_cases} ({s.rejected_citations} IDs)"
              for s in stats]) + " dropped by the verifier before the verdict |",
        _row("Unledgered IDs in final verdicts", [str(s.metrics.unledgered) for s in stats])
        + " must be 0 |",
        _row("Tool calls per case", [_spread(
            [sum(o.tool_calls.values()) for o in outcomes if o.mode == s.mode])
            for s in stats]) + " mean / median / max |",
        _row("Model requests per case", [_spread(s.requests) for s in stats])
        + " mean / median / max, cache hits excluded |",
        _row("Cache hits", [str(s.cached) for s in stats]) + " responses reused, no cost |",
        _row("Input tokens per case", [_spread(s.input_tokens) for s in stats])
        + " mean / median / max |",
        _row("Output tokens per case", [_spread(s.output_tokens) for s in stats])
        + " mean / median / max |",
        _row("Seconds per case", [_spread(s.seconds) for s in stats]) + " mean / median / max |",
        _row("Cost per case", [_spread(s.costs, "${:.4f}") if pricing.known else "not priced"
                               for s in stats])
        + (" from the given token prices |" if pricing.known else " pass --price-in/--price-out |"),
    ]

    lines += ["", "### Tool calls by tool", "", "| Tool | " + " | ".join(s.mode for s in stats)
              + " |", "| --- |" + " --- |" * len(stats)]
    for tool in sorted(set().union(*(s.tool_calls for s in stats))):
        lines.append(_row(tool, [str(s.tool_calls.get(tool, 0)) for s in stats]))
    lines += ["", "### Model requests by role", "", "| Role | " + " | ".join(s.mode for s in stats)
              + " |", "| --- |" + " --- |" * len(stats)]
    for role in sorted(set().union(*(s.requests_by_role for s in stats))):
        lines.append(_row(role, [str(s.requests_by_role.get(role, 0)) for s in stats]))

    if len(stats) == 2:
        lines += ["", "## Mode comparison", ""] + _comparison(*stats, outcomes)

    lines += ["", "## Cases", "",
              "| Alert | Kind | Role | Mode | Status | Flagged | Score | Precision | Recall "
              "| Rejected | Tool calls | Requests | Seconds |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for o in sorted(outcomes, key=lambda o: (o.alert_id, o.mode)):
        flagged = "no verdict" if o.suspicious is None else ("yes" if o.suspicious else "no")
        lines.append(
            f"| {o.alert_id} | {o.case_kind} | {o.role} | {o.mode} | {o.status or o.error} | "
            f"{flagged} | {'' if o.score is None else f'{o.score:.2f}'} | "
            f"{_pct(o.precision()) if o.circuit_edges else ''} | "
            f"{_pct(o.recall()) if o.role == 'planted' and o.flagged else ''} | "
            f"{o.rejected_citations} | {sum(o.tool_calls.values())} | {o.total('requests')} | "
            f"{'' if o.seconds is None else f'{o.seconds:.0f}'} |")
    if subset is not None:
        lines += ["", "## Subset", "", ", ".join(subset.alert_ids)]
    return "\n".join(lines) + "\n"


def _comparison(a: ModeStats, b: ModeStats, outcomes: list[AlertOutcome]) -> list[str]:
    """Where the two modes ended the same alert differently, and what each cost."""
    by_alert: dict[str, dict[str, AlertOutcome]] = {}
    for o in outcomes:
        by_alert.setdefault(o.alert_id, {})[o.mode] = o
    differ = [(alert, runs) for alert, runs in sorted(by_alert.items())
              if a.mode in runs and b.mode in runs
              and (runs[a.mode].suspicious, runs[a.mode].status)
              != (runs[b.mode].suspicious, runs[b.mode].status)]
    mean = lambda xs: statistics.mean(xs) if xs else 0  # noqa: E731
    lines = [
        f"Both modes ran on {sum(1 for r in by_alert.values() if len(r) == 2)} alerts. They "
        f"ended {len(differ)} differently (a different flag or a different case status).",
        "",
        f"- Accuracy: {a.mode} {_pct(a.accuracy)}, {b.mode} {_pct(b.accuracy)}.",
        f"- Model requests per case: {a.mode} {mean(a.requests):.0f}, "
        f"{b.mode} {mean(b.requests):.0f}.",
        f"- Seconds per case: {a.mode} {mean(a.seconds):.0f}, {b.mode} {mean(b.seconds):.0f}.",
    ]
    for alert, runs in differ:
        first, second = runs[a.mode], runs[b.mode]
        lines.append(f"- {alert} ({first.case_kind}, {first.role}): {a.mode} "
                     f"{'flagged' if first.flagged else 'not flagged'} "
                     f"({first.status or first.error}), {b.mode} "
                     f"{'flagged' if second.flagged else 'not flagged'} "
                     f"({second.status or second.error}).")
    return lines
