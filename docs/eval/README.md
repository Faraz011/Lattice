# Evaluating Lattice

Two commands measure the Success Criteria through the running stack (API, MCP server and
workers). Start the stack first: `docker compose --profile app up -d --build`, with
`LATTICE_MODEL=scripted` in front for an offline run.

| | Pre-submission check (U19) | Evaluation harness (U15) |
| --- | --- | --- |
| Command | `uv run python -m lattice.eval.fixture_check` | `uv run python -m lattice.eval.harness` |
| World | held-out fixture world, seed 4242 | demo world, seed 2026 |
| Alerts | 12, stratified: every typology, every decoy kind, one injection pair | all 66, or a seeded stratified subset that fits today's quota |
| Modes | multi-agent | single-agent and multi-agent on the same alerts |
| Report | Success Criteria | Success Criteria plus the R21 statistics, per mode |

Neither world is the fixture world (seed 7) the scorer was tuned on.

## What the harness reports

For each mode:

- **Success Criteria:** planted cases flagged, decoys wrongly flagged, circuit precision,
  supporting-evidence recall, unledgered citations, and injection-pair agreement.
- **Decision accuracy:** planted cases flagged and decoys not flagged, over both.
- **Circuit quality:** how many circuits are sufficient on their own, and how many are
  comprehensive.
- **Hallucinated citations:** cases whose agents cited IDs no tool returned, which the verifier
  dropped before the verdict.
- **Tool calls:** by tool, and per case.
- **Model usage:** requests by role, cache hits, and input and output tokens per case. Each
  worker records these in Redis per case, and the API serves them at `/cases/{id}/usage`.
- **Cost per case:** pass `--price-in` and `--price-out` (dollars per million tokens) for the
  model you ran.
- **Latency per case.**

When both modes ran, a comparison lists every alert they ended differently: a different flag
or a different case status.

## Budget, subsets and resuming

- Both tools estimate the model requests they need before starting. The estimate comes from the
  step budgets: up to 55 requests for a multi-agent case and 16 for a single-agent one. Today's
  remaining quota comes from the API (`/budget`), which reads the same Redis as the workers.
- The fixture check refuses to start when the quota is short.
- The harness instead runs the largest stratified subset that fits both today's request quota
  and the API's daily case cap (`LATTICE_MAX_CASES_PER_DAY`; each alert starts one case per
  mode). It picks one alert of each kind in turn, keeps injection pairs together, and uses a
  fixed seed (`--subset-seed`), so the same seed always picks the same alerts. The report states
  the subset, says which limit caused it, and lists the alerts. A resumed run keeps the subset
  it started with.
- Each finished case is saved under `data/`, so a run that stops (a case cap, a closed laptop)
  resumes where it left off. `--fresh` starts over.
- Each measured case is closed afterwards (its proposal rejected, or its review cleared), so
  the open-case cap never stops a long run.

## Results so far

- [fixture-check-seed-4242-scripted.md](fixture-check-seed-4242-scripted.md): the 12-alert check
  with the scripted model.
- [harness-demo-2026-scripted.md](harness-demo-2026-scripted.md): the demo-world harness with
  the scripted model, both modes.

The scripted runs measure the tools, ledger, verifier, scorer and circuit end to end. They do
not measure how well a language model investigates. Rerun both commands with
`--model google:gemini-flash-latest` (and the workers on that model) before quoting agent
results.

## Real data: an Elliptic2 slice

[Elliptic2](https://www.elliptic.co/elliptic2) is a Bitcoin graph of about 49M clusters with
about 122K labelled subgraphs. Downloading it needs a registration with Elliptic, so the
download is a manual step. Unzip the files into a folder, then:

```bash
uv run python -m lattice.ingest.elliptic2 --dir path/to/elliptic2 --subgraphs 100 --load
uv run python -m lattice.eval.harness --manifest data/elliptic2-manifest.json --modes orchestrated
```

What the slice contains:

- A seeded, label-balanced sample of subgraphs.
- Their member clusters as accounts, and each member's flows in the background graph (one hop,
  capped by `--neighbors`).
- One alert per subgraph, on its best-connected member. The alert text never reveals the label.
- A manifest that keeps the labels out of Neo4j: suspicious subgraphs are `planted` and licit
  ones `decoy`.

The CSVs are streamed, so memory follows the slice and not the 196M-edge background. IDs carry
`ell` (for example `acct_ell1234`), so they never collide with generated data.

### What to expect

Elliptic2's flow features are anonymised, so the slice has no amounts and no timestamps.

- Structural investigation works: neighbours, paths, cycles, fan-in and fan-out by counterparty
  count, PageRank, communities and blast radius.
- The risk scorer's detectors all need amounts and times. They contribute zero, so the scorer
  never flags an Elliptic2 case and no evidence circuit is drawn.
- When investigators find a structural pattern (a cycle, say), the verifier reports that the
  investigators and the scorer disagree and sends the case for review.
- Licit subgraphs close correctly, while suspicious ones are missed. A run on the sample in
  `tests/fixtures/elliptic2_sample` shows exactly this: 60% decision accuracy, and the one
  cycle sent for review.

Flagging real Elliptic2 cases needs a structural scorer: detectors that work on counts and
shapes without amounts or times, tuned against Elliptic2's labels. That is follow-up work.
