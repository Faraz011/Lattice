"""ContextCite-style attribution over tool results, with scripted judges (no model, no graph)."""

import random

from lattice.explain.llm_attribution import (
    MIN_SAMPLES,
    Source,
    SourceWeight,
    agreement,
    attribute,
    judge_prompt,
    lasso,
    sample_masks,
)


def sources(n: int, edges: dict[int, list[str]] | None = None) -> list[Source]:
    edges = edges or {}
    return [Source(result_id=f"led_{i}", tool="graph_match_pattern", text=f"[led_{i}] facts",
                   edges=edges.get(i, [])) for i in range(n)]


def judge_on(index: int, calls: list[list[int]] | None = None):
    """A model whose verdict depends on one source only."""
    async def judge(kept):
        if calls is not None:
            calls.append(kept)
        return 0.9 if index in kept else 0.1
    return judge


async def test_the_source_the_verdict_depends_on_gets_the_top_weight():
    result = await attribute(sources(6), judge_on(2), samples=16, seed=1)

    assert result.status == "complete"
    assert result.sources[0].result_id == "led_2"
    assert result.sources[0].weight > 0.6
    assert all(abs(s.weight) < 0.05 for s in result.sources[1:])
    assert result.full_probability == 0.9


async def test_the_sample_budget_is_respected():
    calls: list[list[int]] = []

    result = await attribute(sources(5), judge_on(0, calls), samples=16, seed=3)

    assert len(calls) == 16 + 1  # every ablation, plus the full context once
    assert result.samples == 16 and result.budget == 16


async def test_when_the_limiter_runs_dry_part_way_it_fits_on_what_it_has():
    calls = 0

    async def limited(kept):
        nonlocal calls
        calls += 1
        if calls > 11:  # the shared budget allows eleven calls
            return None
        return 0.9 if 1 in kept else 0.1

    result = await attribute(sources(4), limited, samples=16, seed=2)

    assert result.status == "partial"
    assert result.samples == 10
    assert calls == 12  # it stops at the first refusal instead of retrying
    assert result.sources[0].result_id == "led_1"
    assert "10 of 16" in result.note


async def test_too_few_samples_is_reported_instead_of_a_noisy_fit():
    calls = 0

    async def nearly_dry(kept):
        nonlocal calls
        calls += 1
        return None if calls > 3 else 0.5

    result = await attribute(sources(4), nearly_dry, samples=16, seed=2)

    assert result.status == "insufficient"
    assert result.sources == []
    assert f"at least {MIN_SAMPLES}" in result.note


async def test_with_no_sources_nothing_is_spent():
    calls: list[list[int]] = []

    result = await attribute([], judge_on(0, calls), samples=16, seed=1)

    assert result.status == "skipped" and calls == []


def test_the_surrogate_recovers_known_weights():
    rng = random.Random(0)
    xs = [[float(rng.random() < 0.5) for _ in range(4)] for _ in range(40)]
    ys = [0.1 + 0.5 * x[0] + 0.3 * x[3] for x in xs]

    intercept, weights = lasso(xs, ys, alpha=0.001)

    assert abs(weights[0] - 0.5) < 0.02 and abs(weights[3] - 0.3) < 0.02
    assert abs(weights[1]) < 0.02 and abs(weights[2]) < 0.02
    assert abs(intercept - 0.1) < 0.02


def test_masks_are_reproducible_from_the_seed():
    assert sample_masks(5, 8, seed="case_1") == sample_masks(5, 8, seed="case_1")
    assert sample_masks(5, 8, seed="case_1") != sample_masks(5, 8, seed="case_2")


async def test_agreement_with_the_scorer_circuit():
    held = sources(4, edges={1: ["tx_a"], 3: ["tx_b"]})

    leans_on_circuit = await attribute(held, judge_on(1), samples=16, seed=1,
                                       circuit_edges=["tx_a", "tx_b"])
    leans_elsewhere = await attribute(held, judge_on(0), samples=16, seed=1,
                                      circuit_edges=["tx_a", "tx_b"])

    assert leans_on_circuit.agreement == 0.5  # top-2 sources: led_1 (circuit) and one other
    assert leans_on_circuit.sources[0].circuit_edges == ["tx_a"]
    assert leans_elsewhere.sources[0].result_id == "led_0"
    assert agreement([SourceWeight(result_id="x", tool="t", weight=1.0)]) is None


def test_the_judge_sees_only_the_kept_sources():
    prompt = judge_prompt("An alert was raised on acct_1.", sources(3), kept=[0, 2])

    assert "[led_0]" in prompt and "[led_2]" in prompt and "[led_1]" not in prompt
    assert "(no tool results)" in judge_prompt("brief", sources(3), kept=[])
