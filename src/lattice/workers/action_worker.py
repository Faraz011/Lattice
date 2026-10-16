"""Action executor role: the only component that executes actions (R17, KTD9).

It re-checks the policy for every job, so an execution job that bypassed the approval route is
refused and the refusal is recorded on the case.
"""

from lattice.cases.actions import ActionStore
from lattice.cases.policy import execution_refusal
from lattice.cases.store import CaseStore
from lattice.cases.views import record_case
from lattice.graph.client import GraphClient
from lattice.queue.events import EventStream
from lattice.queue.jobs import Job
from lattice.queue.streams import Handler

ALREADY_FINAL = ("executed", "refused", "rejected")


def make_handler(graph: GraphClient, events: EventStream) -> Handler:
    actions, cases = ActionStore(graph), CaseStore(graph)

    async def handle(job: Job) -> None:
        action = await actions.get(job.payload["action_id"])
        refusal = execution_refusal(action)
        if refusal:
            if action["status"] not in ALREADY_FINAL:
                await actions.mark_refused(action, refusal)
            await events.publish(job.case_id, "action_refused",
                                 {"action_id": action["id"], "reason": refusal})
            await record_case(graph, events, job.case_id)
            return

        executed = await actions.mark_executed(action)
        case = await cases.get(action["case_id"])
        if action["tier"] >= 2 and case["status"] == "awaiting_approval":
            await cases.transition(case["id"], "actioned", executed["outcome"])
        await events.publish(job.case_id, "action_executed",
                             {"action_id": action["id"], "outcome": executed["outcome"]})
        await record_case(graph, events, job.case_id)

    return handle


async def build_handler(ctx) -> Handler:
    graph = GraphClient.from_settings(ctx.settings)  # lives as long as the worker process
    return make_handler(graph, ctx.events)
