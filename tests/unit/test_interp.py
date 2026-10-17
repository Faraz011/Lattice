"""The tool-choice step for circuit tracing, and the panel summary of a circuit-tracer graph."""

import json
from pathlib import Path

import pytest

from lattice.interp.graph_summary import summarise
from lattice.interp.tool_choice import build_step, first_choice, step_from_recording

GRAPH = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "interp"
                    / "tiny_graph.json").read_text())


def called(tool, hypothesis):
    return {"type": "tool_called", "data": {"tool": tool, "hypothesis": hypothesis}}


EVENTS = [
    {"type": "hypotheses_chosen", "data": {"hypotheses": ["fan_out", "peeling_chain"]}},
    called("graph_get_node", "fan_out"),
    called("graph_match_pattern", "fan_out"),
    called("graph_get_node", "peeling_chain"),
    called("graph_neighbors", "peeling_chain"),
]


def test_the_first_real_choice_skips_the_seed_lookup():
    assert first_choice(EVENTS) == ("fan_out", "graph_match_pattern")
    assert first_choice(EVENTS, "peeling_chain") == ("peeling_chain", "graph_neighbors")
    assert first_choice([called("graph_get_node", "open")]) == ("open", "graph_get_node")
    assert first_choice([]) is None


def test_the_step_is_a_lettered_choice_that_includes_the_recorded_tool():
    step = build_step("case_1", "acct_seed", "peeling_chain", "graph_match_pattern")

    assert [o.letter for o in step.options] == ["A", "B", "C", "D"]
    assert step.target == " C"
    assert "C) graph_match_pattern" in step.prompt
    assert step.prompt.endswith("Answer:")
    assert "peeling chain" in step.prompt and "acct_seed" in step.prompt


def test_a_tool_outside_the_menu_is_still_offered():
    step = build_step("case_1", "acct_seed", "open", "graph_cypher_readonly")

    assert "graph_cypher_readonly" in [o.tool for o in step.options]
    assert len(step.options) == 4
    assert "every laundering pattern" in step.prompt


def test_a_recording_without_tool_calls_is_refused():
    with pytest.raises(ValueError, match="no tool calls"):
        step_from_recording({"case_id": "case_1", "events": []})


def test_the_summary_ranks_features_by_direct_effect_on_the_chosen_answer():
    step = build_step("case_1", "acct_seed", "peeling_chain", "graph_match_pattern")

    summary = summarise(GRAPH, step)

    assert summary.chosen_letter == "C" and summary.recorded_tool == "graph_match_pattern"
    assert [f.node_id for f in summary.features] == ["12_4400_3", "20_77_5"]
    top = summary.features[0]
    assert (top.layer, top.token, top.label, top.effect) == ("12", " chain",
                                                               "laundering shapes", 0.5)
    assert summary.features[1].label == "(no label)"
    assert summary.error_share == 0.3  # 0.3 of |0.5| + |-0.2| + |0.3|
    probabilities = {o.letter: o.probability for o in summary.options}
    assert probabilities == {"A": 0.201, "B": None, "C": 0.612, "D": None}
    assert (summary.nodes, summary.links, summary.model) == (6, 5, "qwen3-0.6b")


def test_a_graph_without_the_chosen_logit_has_no_features_rather_than_failing():
    step = build_step("case_1", "acct_seed", "peeling_chain", "algo_pagerank")  # letter D

    summary = summarise(GRAPH, step)

    assert summary.features == []
    assert summary.chosen_letter == "D"
