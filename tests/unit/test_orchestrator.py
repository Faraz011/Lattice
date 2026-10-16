"""Hypothesis selection and the orchestrator handler, with scripted models and stand-ins."""

from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from lattice.agents.orchestrator import DEFAULT_HYPOTHESES, choose_hypotheses
from lattice.agents.runtime import AgentRuntime
from lattice.config import Settings
from lattice.queue.jobs import Job
from lattice.workers.orchestrator_worker import make_handler


def settings() -> Settings:
    return Settings(_env_file=None, neo4j_uri="bolt://x", neo4j_user="n", neo4j_password="p",
                    redis_url="redis://x", approver_token="t", gemini_api_key="k")


def choosing(*hypotheses: str) -> FunctionModel:
    def script(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(
            info.output_tools[0].name,
            {"hypotheses": list(hypotheses), "rationale": "large inbound then outbound"},
        )])
    return FunctionModel(script)


SUMMARY = "account acct_seed (person, opened 2023-01-01): 1 inbound, 12 outbound transfers"


async def test_the_model_picks_two_to_four_catalog_hypotheses():
    picked = await choose_hypotheses(AgentRuntime(settings(), mcp_url=None), "case_1", SUMMARY,
                                     model=choosing("peeling_chain", "fan_out", "round_trip"))

    assert picked == ["peeling_chain", "fan_out", "round_trip"]


async def test_an_unknown_typology_falls_back_to_the_default_set():
    picked = await choose_hypotheses(AgentRuntime(settings(), mcp_url=None), "case_1", SUMMARY,
                                     model=choosing("peeling_chain", "time_travel"))

    assert picked == DEFAULT_HYPOTHESES


async def test_too_few_hypotheses_fall_back_to_the_default_set():
    picked = await choose_hypotheses(AgentRuntime(settings(), mcp_url=None), "case_1", SUMMARY,
                                     model=choosing("fan_out"))

    assert picked == DEFAULT_HYPOTHESES


async def test_duplicates_are_removed_while_keeping_order():
    picked = await choose_hypotheses(AgentRuntime(settings(), mcp_url=None), "case_1", SUMMARY,
                                     model=choosing("fan_out", "fan_out", "round_trip"))

    assert picked == ["fan_out", "round_trip"]


# --- the handler with stand-ins -----------------------------------------------------------


class FakeCases:
    def __init__(self, status="received"):
        self.case = {"id": "case_1", "alert_id": "alert_1", "seed_account_id": "acct_seed",
                     "alert_reason": "many outbound transfers", "status": status}
        self.moves: list[str] = []

    async def get(self, case_id):
        return self.case

    async def transition(self, case_id, target, reason):
        self.moves.append(target)
        self.case["status"] = target
        return self.case


class FakeFanIn:
    def __init__(self):
        self.opened = None

    async def open(self, case_id, expected, deadline_s):
        self.opened = (case_id, expected, deadline_s)


class Recorder:
    def __init__(self):
        self.items = []

    async def enqueue(self, job):
        self.items.append(job)

    async def publish(self, case_id, kind, data):
        self.items.append((kind, data))


async def test_the_handler_fans_out_one_distinct_brief_per_hypothesis():
    cases, fanin, queue, events = FakeCases(), FakeFanIn(), Recorder(), Recorder()

    async def summarise(case):
        return SUMMARY

    async def choose(case, summary):
        return ["peeling_chain", "fan_out", "round_trip"]

    handle = make_handler(cases, fanin, queue, events, summarise, choose, deadline_s=120)
    await handle(Job.new("investigate", "case_1", {"alert_id": "alert_1"}))

    briefs = [job.payload["brief"] for job in queue.items]
    assert [b["hypothesis"] for b in briefs] == ["peeling_chain", "fan_out", "round_trip"]
    assert all(b["seed_account_id"] == "acct_seed" for b in briefs)
    assert all(job.type == "hypothesis" and not job.payload["single_agent"]
               for job in queue.items)
    assert fanin.opened == ("case_1", ["peeling_chain", "fan_out", "round_trip"], 120)
    assert cases.moves == ["planning", "investigating"]
    assert ("hypotheses_chosen", {"hypotheses": ["peeling_chain", "fan_out", "round_trip"],
                                  "summary": SUMMARY}) in events.items


async def test_a_case_already_being_investigated_is_not_fanned_out_twice():
    cases = FakeCases(status="verifying")
    queue = Recorder()

    async def never(*args):
        raise AssertionError("should not be called")

    await make_handler(cases, FakeFanIn(), queue, Recorder(), never, never, deadline_s=60)(
        Job.new("investigate", "case_1", {}))

    assert queue.items == []
