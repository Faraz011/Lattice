"""Condense a circuit-tracer graph file into the small JSON the UI's interpretability panel shows.

circuit-tracer's `create_graph_files` writes a graph with `metadata` (prompt tokens), `nodes`
(features, error nodes, token embeddings and output logits, each with a layer, a token position
and an influence score) and weighted `links`. The panel needs much less: the option
probabilities, and the features that most directly drive the chosen answer, each with its
layer, the token it sits on, and its label when the feature has one.

    uv run python -m lattice.interp.graph_summary research/interp/graphs/<slug>.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from lattice.interp.tool_choice import ToolChoiceStep

PANEL = Path(__file__).resolve().parents[3] / "ui" / "public" / "interp" / "tool-choice.json"
TOP_FEATURES = 12


class OptionProbability(BaseModel):
    letter: str
    tool: str
    probability: float | None


class Feature(BaseModel):
    node_id: str
    layer: str
    token: str
    label: str
    effect: float  # direct link weight into the chosen answer's logit
    influence: float | None


class PanelSummary(BaseModel):
    slug: str
    model: str
    prompt: str
    recorded_tool: str
    chosen_letter: str
    options: list[OptionProbability]
    features: list[Feature]
    error_share: float  # share of direct effect from reconstruction error nodes
    nodes: int
    links: int


def _logit_letter(node: dict[str, Any]) -> str | None:
    # Logit nodes are labelled like: Output " B" (p=0.412)
    clerp = node.get("clerp", "")
    if '"' not in clerp:
        return None
    return clerp.split('"')[1].strip() or None


def _probability(node: dict[str, Any]) -> float | None:
    if node.get("token_prob"):
        return float(node["token_prob"])
    clerp = node.get("clerp", "")
    if "p=" in clerp:
        return float(clerp.split("p=")[1].rstrip(")"))
    return None


def summarise(graph: dict[str, Any], step: ToolChoiceStep, top: int = TOP_FEATURES) -> PanelSummary:
    meta = graph["metadata"]
    tokens: list[str] = meta.get("prompt_tokens", [])
    nodes = {n["node_id"]: n for n in graph["nodes"]}
    logits = {letter: n for n in graph["nodes"]
              if n.get("feature_type") == "logit" and (letter := _logit_letter(n))}
    chosen = step.target.strip()
    target = logits.get(chosen)

    direct: dict[str, float] = {}
    if target is not None:
        for link in graph["links"]:
            if link["target"] == target["node_id"]:
                direct[link["source"]] = direct.get(link["source"], 0.0) + link["weight"]

    def token_at(node: dict[str, Any]) -> str:
        idx = node.get("ctx_idx", -1)
        return tokens[idx] if 0 <= idx < len(tokens) else "?"

    features = sorted(
        (Feature(node_id=src, layer=str(nodes[src].get("layer", "?")), token=token_at(nodes[src]),
                 label=nodes[src].get("clerp", "") or "(no label)", effect=round(weight, 4),
                 influence=nodes[src].get("influence"))
         for src, weight in direct.items()
         if src in nodes and nodes[src].get("feature_type") not in ("mlp reconstruction error",)),
        key=lambda f: -abs(f.effect),
    )[:top]
    total = sum(abs(w) for w in direct.values()) or 1.0
    errors = sum(abs(w) for src, w in direct.items()
                 if nodes.get(src, {}).get("feature_type") == "mlp reconstruction error")
    return PanelSummary(
        slug=meta.get("slug", ""),
        model=meta.get("scan", ""),
        prompt=meta.get("prompt", step.prompt),
        recorded_tool=step.recorded_tool,
        chosen_letter=chosen,
        options=[OptionProbability(letter=o.letter, tool=o.tool,
                                   probability=_probability(logits[o.letter])
                                   if o.letter in logits else None)
                 for o in step.options],
        features=features,
        error_share=round(errors / total, 4),
        nodes=len(graph["nodes"]),
        links=len(graph["links"]),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lattice.interp.graph_summary",
                                     description=__doc__.split("\n")[0])
    parser.add_argument("graph", type=Path, help="a graph JSON from create_graph_files")
    parser.add_argument("--step", type=Path,
                        default=Path(__file__).resolve().parents[3] / "research" / "interp"
                        / "step.json")
    parser.add_argument("--out", type=Path, default=PANEL)
    args = parser.parse_args(argv)

    step = ToolChoiceStep.model_validate_json(args.step.read_text())
    summary = summarise(json.loads(args.graph.read_text()), step)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(summary.model_dump_json(indent=2) + "\n")
    print(f"panel summary written to {args.out}: {len(summary.features)} features, "
          f"chosen {summary.chosen_letter} ({summary.recorded_tool})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
