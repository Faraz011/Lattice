"""The orchestrator's one model call: choose which hypotheses to investigate (KTD11).

The model sees only a structural summary of the seed account (counts, amounts, ages, kinds),
never memos or names, so injected text cannot steer which hypotheses get tested.
"""

from typing import get_args

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

from lattice.agents.investigator import GUIDES
from lattice.agents.runtime import AgentRuntime
from lattice.agents.schemas import Typology

# Used whenever the model's choice is unusable: the three broadest typologies.
DEFAULT_HYPOTHESES = ["peeling_chain", "fan_in_structuring", "rapid_layering"]


class HypothesisChoice(BaseModel):
    hypotheses: list[Typology] = Field(min_length=2, max_length=4,
                                       description="Two to four typologies from the catalog.")
    rationale: str = Field(description="One sentence on why these, from the summary.")


def build_prompt(summary: str) -> str:
    catalog = "\n".join(f"- {name}: {GUIDES[name].split('.')[0]}." for name in get_args(Typology))
    return f"""\
Structural summary of the alerted account:
{summary}

Typology catalog:
{catalog}

Choose the two to four typologies investigators should test.
"""


async def choose_hypotheses(
    runtime: AgentRuntime, case_id: str, summary: str, model: Model | None = None
) -> list[str]:
    outcome = await runtime.run(
        "orchestrator", case_id, build_prompt(summary), HypothesisChoice,
        lambda reason, status="partial": None, model=model, step_budget=3,
    )
    if outcome.output is None:
        return list(DEFAULT_HYPOTHESES)
    chosen = list(dict.fromkeys(outcome.output.hypotheses))
    return chosen if len(chosen) >= 2 else list(DEFAULT_HYPOTHESES)
