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
- The priced detectors (peeling chain, structuring, round trip and the rest) need amounts and
  times, so they contribute zero. The scorer's structural detectors
  (`src/lattice/scoring/structural.py`) take over whenever the cited evidence has no priced
  flows at all:

  | Detector | Fires on | Strength | Weight |
  | --- | --- | --- | --- |
  | `structural_cycle` | a loop through 3 to 6 accounts back to the start | 1.0 | 0.75 |
  | `structural_fan_out` | one account paying many distinct counterparties | (n - 4) / 8 | 0.3 |
  | `structural_fan_in` | one account paid by many distinct counterparties | (n - 4) / 8 | 0.3 |
  | `structural_dense` | 4+ accounts with most possible links among them | (density - 0.5) / 0.4 | 0.6 |

  A cycle flags on its own. A fan never does, even fanning both ways (exchanges and services
  are hubs). A two-account back-and-forth is not a cycle. `LATTICE_STRUCTURAL_DETECTORS`
  (`auto`, `always`, `never`) overrides the gate, and `LATTICE_DETECTOR_WEIGHTS` the weights.
  The synthetic worlds are fully priced, so their scores do not change.
- The scorer still sees only what investigators cite. A subgraph whose shape no investigator
  reports cannot be flagged.

### Results on the sample

[harness-elliptic2-sample-scripted.md](harness-elliptic2-sample-scripted.md): the five-subgraph
sample in `tests/fixtures/elliptic2_sample`, orchestrated mode, scripted model.

- 2 of 5 cases suspicious, 3 licit. Flagged: 1 (cc1, the loop 1 -> 2 -> 3 -> 1, score 0.75).
  Precision 1 of 1 flagged; recall 1 of 2 suspicious; 0 of 3 licit flagged. Decision accuracy
  80%, up from 60% before the structural detectors.
- cc1's circuit is exactly the three loop edges: sufficient, comprehensive, and each single
  edge is a counterfactual.
- Missed: cc3 (cluster 6 paying 7 and 8, fed by 9). The scripted investigators cite nothing
  there. Their fan-out check asks for 8 counterparties and their chain check needs times, so
  the evidence graph is empty and no detector can fire. A model investigator that cites the
  small fan would still score it below the threshold: a three-way fan is weak evidence.
- Five subgraphs are a smoke test, not a measurement. The tuning run below had to use the same
  five, so these numbers are not independent of the weights.

### Tuning the structural weights

```bash
uv run python -m lattice.eval.tune_structural --dir path/to/elliptic2 --subgraphs 2000
```

The tuning slice is drawn with its own seed (`--seed`, default 7) from the subgraphs the
evaluation slice (`--eval-seed 2`, `--eval-subgraphs 100`, as the ingest above builds it) did
not pick, so tuning never sees an evaluation subgraph. Each subgraph is scored offline on its
internal flows. The tool prints each detector's firing rate by label, the current and best
weights by balanced accuracy, and a `LATTICE_DETECTOR_WEIGHTS` line to apply.

The weights above are priors. The real dataset was not available here, and the sample's five
subgraphs all belong to the evaluation slice, so the only tuning run used `--allow-overlap`
(which the output flags as a smoke test). On the sample, only the cycle detector separates the
labels (1 of 2 suspicious, 0 of 3 licit); the fan and dense weights are untested. Rerun the
tuner on the full download before quoting Elliptic2 results.
