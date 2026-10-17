"""One recorded investigator step, framed for circuit tracing on a small open model (U18, R23).

An attribution graph explains one next-token prediction. So the tool choice an investigator
made in a recorded case is restated as a short multiple-choice prompt: the brief, a handful of
lettered tools (always including the one it picked), and "Answer:". The letter of the recorded
tool is the logit to explain. The notebook in research/interp runs this prompt through
circuit-tracer.

This is a showcase of the method on an open model, not an explanation of the production
model's choice (a hosted model's internals cannot be traced) and never part of a verdict.

    uv run python -m lattice.interp.tool_choice --recording recordings/<case>.json
    uv run python -m lattice.interp.tool_choice --api http://localhost:8080 --case <case_id>
"""

import argparse
import asyncio
import json
import string
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

OUT = Path(__file__).resolve().parents[3] / "research" / "interp" / "step.json"

# Short, plain descriptions: a small model reads these, not the full MCP schema.
MENU: dict[str, str] = {
    "graph_neighbors": "list the transfers and devices around an account",
    "graph_find_paths": "trace money paths between two accounts",
    "graph_match_pattern": "test a laundering shape (chain, fan-in, fan-out, cycle)",
    "algo_pagerank": "rank which accounts are most central around an account",
    "algo_similar": "find accounts that pay the same counterparties",
    "graph_get_node": "look up one account's details",
    "algo_communities": "find the group an account belongs to",
    "algo_impact": "count the accounts and customers affected by acting on an account",
}
OPTIONS = 4


class Option(BaseModel):
    letter: str
    tool: str
    description: str


class ToolChoiceStep(BaseModel):
    case_id: str
    hypothesis: str
    seed_account_id: str
    recorded_tool: str
    options: list[Option]
    prompt: str
    target: str  # the letter to attribute, with its leading space as a tokenizer sees it


def first_choice(events: list[dict[str, Any]],
                 hypothesis: str | None = None) -> tuple[str, str] | None:
    """(hypothesis, tool) of the first tool an investigator called (the one testing
    `hypothesis`, if given), skipping a lookup of the seed account itself, which every
    investigation starts with."""
    calls = [e["data"] for e in events if e["type"] == "tool_called"
             and (hypothesis is None or e["data"].get("hypothesis") == hypothesis)]
    for data in calls:
        if data.get("tool") != "graph_get_node":
            return data.get("hypothesis", "open"), data["tool"]
    return (calls[0].get("hypothesis", "open"), calls[0]["tool"]) if calls else None


def menu_for(recorded: str) -> list[Option]:
    """The recorded tool plus the first others in MENU, in MENU order, lettered A, B, ..."""
    tools = [t for t in MENU if t != recorded][: OPTIONS - 1]
    tools.append(recorded)
    tools.sort(key=lambda t: list(MENU).index(t) if t in MENU else len(MENU))
    return [Option(letter=string.ascii_uppercase[i], tool=t,
                   description=MENU.get(t, t.replace("_", " ")))
            for i, t in enumerate(tools)]


def build_step(case_id: str, seed: str, hypothesis: str, recorded: str) -> ToolChoiceStep:
    options = menu_for(recorded)
    pattern = "every laundering pattern" if hypothesis == "open" else hypothesis.replace("_", " ")
    lines = [
        "An anti-money-laundering investigator is examining an alert.",
        f"The alert was raised on account {seed}. The investigator is testing for {pattern}.",
        "Which tool should the investigator call first?",
        *(f"{o.letter}) {o.tool}: {o.description}" for o in options),
        "Answer:",
    ]
    target = next(o.letter for o in options if o.tool == recorded)
    return ToolChoiceStep(case_id=case_id, hypothesis=hypothesis, seed_account_id=seed,
                          recorded_tool=recorded, options=options, prompt="\n".join(lines),
                          target=f" {target}")


def step_from_recording(recording: dict[str, Any],
                        hypothesis: str | None = None) -> ToolChoiceStep:
    choice = first_choice(recording["events"], hypothesis)
    if choice is None:
        raise ValueError(f"case {recording['case_id']} recorded no tool calls"
                         + (f" for {hypothesis}" if hypothesis else ""))
    hypothesis, tool = choice
    snapshot = recording.get("snapshot") or {}
    seed = (snapshot.get("case") or {}).get("seed_account_id", "the seed account")
    return build_step(recording["case_id"], seed, hypothesis, tool)


async def _from_api(api: str, case_id: str) -> dict[str, Any]:
    import httpx

    async with httpx.AsyncClient(base_url=api, timeout=30) as http:
        response = await http.get(f"/cases/{case_id}/recording")
        response.raise_for_status()
        return response.json()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lattice.interp.tool_choice",
                                     description=__doc__.split("\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--recording", type=Path, help="an exported recording JSON file")
    source.add_argument("--case", help="a case ID to fetch from the API's saved recording")
    parser.add_argument("--hypothesis", help="take the step of this hypothesis's investigator")
    parser.add_argument("--api", default="http://localhost:8080")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    recording = (json.loads(args.recording.read_text()) if args.recording
                 else asyncio.run(_from_api(args.api, args.case)))
    step = step_from_recording(recording, args.hypothesis)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(step.model_dump_json(indent=2) + "\n")
    print(step.prompt)
    print(f"\nrecorded choice: {step.recorded_tool} ({step.target.strip()}); "
          f"written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
