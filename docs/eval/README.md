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
