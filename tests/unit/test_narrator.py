"""The narrator may only mention IDs from the circuit report; otherwise the template speaks."""

from pydantic_ai import ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from test_detectors import Builder, peeling

from lattice.agents.narrator import allowed_ids, mentioned_ids, narrate, template_narrative
from lattice.agents.runtime import AgentRuntime
from lattice.config import Settings
from lattice.explain.report import build_report
from lattice.scoring.scorer import Scorer


def settings() -> Settings:
    return Settings(_env_file=None, neo4j_uri="bolt://x", neo4j_user="n", neo4j_password="p",
                    redis_url="redis://x", approver_token="t", gemini_api_key="k")


def report():
    b = Builder()
    peeling(b, hops=5)
    return build_report(b.graph(), Scorer())


class AlwaysExhausted:
    async def acquire(self, timeout):
        return False


def replying(*texts: str) -> FunctionModel:
    replies = iter(texts)

    def script(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(next(replies))])

    return FunctionModel(script)


def test_the_template_mentions_only_report_ids_and_states_the_decision():
    r = report()

    text = template_narrative(r)

    assert mentioned_ids(text) <= allowed_ids(r)
    assert "peeling_chain" in text
    assert f"{r.circuit.full_score:.2f}" in text
    assert r.counterfactuals.counterfactuals[0].removed[0] in text


def test_ids_are_found_in_prose():
    text = "Funds moved via tx_1 from a0 to acct_ab12 and used_device:acct_1:dev_2."

    assert mentioned_ids(text) == {"tx_1", "acct_ab12", "used_device:acct_1:dev_2"}


async def test_a_model_narrative_citing_only_report_ids_is_used():
    r = report()
    edge = r.circuit.circuit_edges[0]

    narrative = await narrate(AgentRuntime(settings(), mcp_url=None), "case_1", r,
                              model=replying(f"The chain moves money through {edge}."))

    assert narrative.source == "model"
    assert edge in narrative.text


async def test_a_narrative_citing_a_foreign_id_is_regenerated():
    r = report()
    edge = r.circuit.circuit_edges[0]

    narrative = await narrate(AgentRuntime(settings(), mcp_url=None), "case_1", r,
                              model=replying("It went through tx_invented.",
                                             f"It went through {edge}."))

    assert narrative.source == "model"
    assert "tx_invented" not in narrative.text


async def test_a_narrator_that_keeps_inventing_ids_is_replaced_by_the_template():
    r = report()

    narrative = await narrate(AgentRuntime(settings(), mcp_url=None), "case_1", r,
                              model=replying("See tx_fake1.", "See tx_fake2.", "See tx_fake3."))

    assert narrative.source == "template"
    assert narrative.text == template_narrative(r)


async def test_an_exhausted_rate_budget_falls_back_to_the_template():
    r = report()
    runtime = AgentRuntime(settings(), mcp_url=None, limiter=AlwaysExhausted())

    narrative = await narrate(runtime, "case_1", r, model=replying("unused"))

    assert narrative.source == "template"
