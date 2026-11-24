"""Which tool results the LLM's verdict leans on (U17): ContextCite-style ablation of the ledger.

The scorer circuit (U12) explains the risk score. This explains the *language model's*
judgement, which is a different question, because a model's stated reasoning is not a reliable
account of what drove it (Turpin et al. 2023; Chen et al. 2025).

Method (Cohen-Wang et al. 2024, ContextCite), applied to an agent's tool results:

1. Each ledgered tool result the case relied on becomes one context source, written as
   structured facts only (the tool, its parameters, and the transfers and accounts it returned).
   Memos and other free text are left out, so injected text cannot steer the ablation.
2. A judge call reads one keep-or-drop mask of those sources at a time and gives the
   probability that the activity is money laundering. Masks are random, keeping each source
   with probability 1/2, plus one run with every source.
3. A sparse linear surrogate (lasso) fitted to (mask, probability) pairs gives each source's
   weight: how much keeping it moves the judgement.

The sample count is a fixed budget, and every call goes through the shared rate limiter and
response cache. When the limiter runs dry part way, the surrogate is fitted on the samples
collected, or skipped below a minimum. Weights are compared with the scorer circuit: does the
model lean on the same tool results that hold the circuit's edges?
"""

import random
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from lattice.graph.client import GraphClient

MIN_SAMPLES = 8
MAX_FACTS_PER_SOURCE = 12

# A judge reads the kept sources and returns P(laundering), or None when it could not run.
Judge = Callable[[list[int]], Awaitable[float | None]]


class SourceWeight(BaseModel):
    result_id: str
    tool: str
    weight: float
    circuit_edges: list[str] = Field(default_factory=list)


class LLMAttribution(BaseModel):
    status: Literal["complete", "partial", "insufficient", "skipped"]
    samples: int
    budget: int
    full_probability: float | None = None
    sources: list[SourceWeight] = Field(default_factory=list)
    # Of the k sources weighted highest (k = sources holding circuit edges), the share that
    # hold circuit edges: 1.0 means the model leans where the scorer's proof is.
    agreement: float | None = None
    note: str | None = None


# --- sources ---------------------------------------------------------------------------------


class Source(BaseModel):
    result_id: str
    tool: str
    text: str
    edges: list[str]


async def load_sources(graph: GraphClient, case_id: str, result_ids: Sequence[str],
                       max_sources: int) -> list[Source]:
    """The case's ledger entries as context blocks of structured facts, in call order."""
    rows = await graph.read(
        """
        MATCH (l:LedgerEntry {case_id: $case_id}) WHERE l.result_id IN $ids
        RETURN l.result_id AS result_id, l.tool AS tool, l.params AS params,
               l.rel_ids AS rel_ids, l.node_ids AS node_ids
        ORDER BY l.ts
        """,
        case_id=case_id, ids=list(result_ids),
    )
    rows = rows[:max_sources]
    tx_ids = sorted({r for row in rows for r in row["rel_ids"] or [] if r.startswith("tx_")})
    transfers = {
        t["id"]: t for t in await graph.read(
            """
            MATCH (a:Account)-[t:TRANSFER]->(b:Account) WHERE t.id IN $ids
            RETURN t.id AS id, a.id AS src, b.id AS dst, t.amount AS amount, t.ts AS ts
            """,
            ids=tx_ids,
        )
    }
    node_ids = sorted({n for row in rows for n in row["node_ids"] or [] if n.startswith("acct_")})
    accounts = {
        a["id"]: a for a in await graph.read(
            "MATCH (a:Account) WHERE a.id IN $ids RETURN a.id AS id, a.kind AS kind",
            ids=node_ids,
        )
    }
    sources = []
    for row in rows:
        facts = []
        for rel in (row["rel_ids"] or [])[:MAX_FACTS_PER_SOURCE]:
            t = transfers.get(rel)
            if t is not None:
                amount = f" {t['amount']:,.2f}" if t["amount"] is not None else ""
                when = f" at {t['ts'].to_native().isoformat()}" if t["ts"] is not None else ""
                facts.append(f"transfer {t['id']}: {t['src']} -> {t['dst']}{amount}{when}")
            elif rel.startswith("used_device:"):
                _, account, device = rel.split(":")
                facts.append(f"{account} used device {device}")
        for node in (row["node_ids"] or [])[:MAX_FACTS_PER_SOURCE]:
            if node in accounts:
                facts.append(f"account {node} is a {accounts[node]['kind']} account")
        extra = len(row["rel_ids"] or []) - MAX_FACTS_PER_SOURCE
        if extra > 0:
            facts.append(f"... and {extra} more relationships")
        text = (f"[{row['result_id']}] {row['tool']}({row['params']}) returned:\n"
                + ("\n".join(f"- {f}" for f in facts) if facts else "- nothing relevant"))
        sources.append(Source(result_id=row["result_id"], tool=row["tool"], text=text,
                              edges=list(row["rel_ids"] or [])))
    return sources


def judge_prompt(brief: str, sources: list[Source], kept: list[int]) -> str:
    blocks = [sources[i].text for i in kept]
    body = "\n\n".join(blocks) if blocks else "(no tool results)"
    return (f"{brief}\n\nTool results available to you:\n\n{body}\n\n"
            "How likely is it that this activity is money laundering?")


# --- sampling and the surrogate --------------------------------------------------------------


def sample_masks(sources: int, samples: int, seed: int | str) -> list[list[bool]]:
    rng = random.Random(seed)
    return [[rng.random() < 0.5 for _ in range(sources)] for _ in range(samples)]


def lasso(xs: list[list[float]], ys: list[float], alpha: float = 0.01,
          rounds: int = 500) -> tuple[float, list[float]]:
    """Intercept and weights minimising mean squared error + alpha * |w|_1 (coordinate descent)."""
    n, p = len(xs), len(xs[0]) if xs else 0
    if n == 0 or p == 0:
        return (sum(ys) / n if n else 0.0), [0.0] * p
    means = [sum(row[j] for row in xs) / n for j in range(p)]
    y_mean = sum(ys) / n
    xc = [[row[j] - means[j] for j in range(p)] for row in xs]
    yc = [y - y_mean for y in ys]
    norms = [sum(row[j] ** 2 for row in xc) / n for j in range(p)]
    w = [0.0] * p
    residual = list(yc)
    for _ in range(rounds):
        biggest = 0.0
        for j in range(p):
            if norms[j] == 0:
                continue
            rho = sum(xc[i][j] * (residual[i] + xc[i][j] * w[j]) for i in range(n)) / n
            new = (max(abs(rho) - alpha, 0.0) * (1 if rho > 0 else -1)) / norms[j]
            if new != w[j]:
                delta = new - w[j]
                for i in range(n):
                    residual[i] -= xc[i][j] * delta
                biggest = max(biggest, abs(delta))
                w[j] = new
        if biggest < 1e-9:
            break
    intercept = y_mean - sum(w[j] * means[j] for j in range(p))
    return intercept, w


def agreement(weights: list[SourceWeight]) -> float | None:
    holding = sum(1 for s in weights if s.circuit_edges)
    if holding == 0:
        return None
    top = sorted(weights, key=lambda s: (-s.weight, s.result_id))[:holding]
    return sum(1 for s in top if s.circuit_edges) / holding


async def attribute(sources: list[Source], judge: Judge, samples: int, seed: int | str,
                    circuit_edges: Sequence[str] = ()) -> LLMAttribution:
    """Run the judge on the full context and `samples` ablations; fit the surrogate."""
    if not sources or samples <= 0:
        return LLMAttribution(status="skipped", samples=0, budget=samples,
                              note="no tool results to attribute" if not sources else None)
    full = await judge(list(range(len(sources))))
    masks, ys = [], []
    for mask in sample_masks(len(sources), samples, seed):
        y = await judge([i for i, keep in enumerate(mask) if keep])
        if y is None:
            break  # the shared budget ran out; fit on what was collected
        masks.append(mask)
        ys.append(y)

    complete = len(masks) == samples and full is not None
    if len(masks) < MIN_SAMPLES:
        return LLMAttribution(
            status="insufficient", samples=len(masks), budget=samples, full_probability=full,
            note=f"only {len(masks)} of {samples} samples ran before the model budget ran out; "
                 f"at least {MIN_SAMPLES} are needed")
    _, weights = lasso([[1.0 if keep else 0.0 for keep in mask] for mask in masks], ys)
    circuit = set(circuit_edges)
    ranked = sorted(
        (SourceWeight(result_id=s.result_id, tool=s.tool, weight=round(weights[i], 4),
                      circuit_edges=[e for e in s.edges if e in circuit])
         for i, s in enumerate(sources)),
        key=lambda s: (-s.weight, s.result_id))
    return LLMAttribution(
        status="complete" if complete else "partial", samples=len(masks), budget=samples,
        full_probability=full, sources=ranked, agreement=agreement(ranked),
        note=None if complete else f"{len(masks)} of {samples} samples ran before the model "
                                   "budget ran out")


# --- the judge on the agent runtime -----------------------------------------------------------


class Judgement(BaseModel):
    suspicious: bool
    probability: float = Field(ge=0, le=1,
                               description="Probability that this activity is money laundering.")


def runtime_judge(runtime: Any, case_id: str, brief: str, sources: list[Source]) -> Judge:
    """A judge that asks the model, through the shared limiter and cache, as role `judge`."""

    async def judge(kept: list[int]) -> float | None:
        outcome = await runtime.run("judge", case_id, judge_prompt(brief, sources, kept),
                                    Judgement, lambda reason, status="partial": None,
                                    step_budget=1)
        return outcome.output.probability if outcome.output is not None else None

    return judge


async def attribute_case(graph: GraphClient, runtime: Any, case: dict[str, Any],
                         cited_result_ids: Sequence[str], circuit_edges: Sequence[str],
                         samples: int, max_sources: int) -> LLMAttribution:
    """Attribute a case's verdict over the tool results it cited and those holding the circuit.

    Sources that returned circuit edges come first, so a cap on sources never drops them.
    """
    holding = await graph.read(
        """
        MATCH (l:LedgerEntry {case_id: $c})
        WHERE any(r IN l.rel_ids WHERE r IN $edges)
        RETURN l.result_id AS id
        """,
        c=case["id"], edges=list(circuit_edges),
    )
    preferred = [r["id"] for r in holding]
    ids = list(dict.fromkeys([*preferred, *cited_result_ids]))[:max_sources]
    sources = await load_sources(graph, case["id"], ids, max_sources)
    brief = f"An alert was raised on account {case['seed_account_id']}."
    return await attribute(sources, runtime_judge(runtime, case["id"], brief, sources), samples,
                           seed=case["id"], circuit_edges=circuit_edges)
