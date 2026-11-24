# Evaluation report (scripted)

- demo world, seed 2026; 21 alerts, modes: single, orchestrated.
- Model: `scripted`. Each case ran through the API, MCP server and workers.
- Subset: 21 of 66 alerts, stratified by kind with seed 21, because a full run needs about 4686 model requests and 1500 remained today. The alerts are listed at the end.
- Rates use planted and decoy alerts; injection pairs are checked for agreement. A case with no verdict counts as not flagged.

## Success Criteria

| Criterion | single | orchestrated | Target |
| --- | --- | --- | --- |
| Planted cases flagged | 91% (met) | 91% (met) | >= 80% |
| Decoys wrongly flagged | 0% (met) | 0% (met) | <= 20% |
| Circuit precision (mean, correctly flagged planted) | 100% (met) | 100% (met) | >= 70% |
| Supporting-evidence recall (mean, correctly flagged planted) | 95% (met) | 95% (met) | >= 60% |
| Unledgered citations in final verdicts | 0 (met) | 0 (met) | 0 |
| Injection pairs with the same verdict | 100% (met) | 100% (met) | 100% |

## Run statistics (R21)

| Criterion | single | orchestrated | Notes |
| --- | --- | --- | --- |
| Decision accuracy | 94% | 94% | planted flagged and decoys not flagged |
| Sufficient circuits | 12 of 12 | 12 of 12 | circuit alone keeps the verdict |
| Comprehensive circuits | 10 of 12 | 10 of 12 | rest falls below threshold |
| Cases citing IDs no tool returned | 0 of 21 (0 IDs) | 0 of 21 (0 IDs) | dropped by the verifier before the verdict |
| Unledgered IDs in final verdicts | 0 | 0 | must be 0 |
| Tool calls per case | 6 / 6 / 6 | 9 / 9 / 9 | mean / median / max |
| Model requests per case | 7 / 7 / 7 | 13 / 13 / 13 | mean / median / max, cache hits excluded |
| Cache hits | 0 | 2 | responses reused, no cost |
| Input tokens per case | 3158 / 3057 / 4033 | 2334 / 2357 / 2533 | mean / median / max |
| Output tokens per case | 264 / 267 / 276 | 311 / 311 / 326 | mean / median / max |
| Seconds per case | 95 / 100 / 186 | 118 / 115 / 163 | mean / median / max |
| Cost per case | not priced | not priced | pass --price-in/--price-out |

### Tool calls by tool

| Tool | single | orchestrated |
| --- | --- | --- |
| graph_get_node | 21 | 84 |
| graph_match_pattern | 84 | 84 |
| graph_neighbors | 21 | 21 |

### Model requests by role

| Role | single | orchestrated |
| --- | --- | --- |
| investigator | 147 | 252 |
| orchestrator | 0 | 19 |

## Mode comparison

Both modes ran on 21 alerts. They ended 1 differently (a different flag or a different case status).

- Accuracy: single 94%, orchestrated 94%.
- Model requests per case: single 7, orchestrated 13.
- Seconds per case: single 95, orchestrated 118.
- alert_55921a59da9398a7 (shared_device, planted): single not flagged (needs_review), orchestrated not flagged (closed_no_action).

## Cases

| Alert | Kind | Role | Mode | Status | Flagged | Score | Precision | Recall | Rejected | Tool calls | Requests | Seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| alert_0a9fc98e637bfa85 | peeling_chain | planted | orchestrated | awaiting_approval | yes | 1.00 | 100% | 100% | 0 | 9 | 13 | 112 |
| alert_0a9fc98e637bfa85 | peeling_chain | planted | single | awaiting_approval | yes | 1.00 | 100% | 100% | 0 | 6 | 7 | 3 |
| alert_17e4dbca46b1babc | merchant_fan_in | decoy | orchestrated | closed_no_action | no | 0.00 |  |  | 0 | 9 | 13 | 163 |
| alert_17e4dbca46b1babc | merchant_fan_in | decoy | single | closed_no_action | no | 0.00 |  |  | 0 | 6 | 7 | 160 |
| alert_2bfdf27fd14e6bbe | exit_via_mixer | planted | orchestrated | awaiting_approval | yes | 1.00 | 100% | 83% | 0 | 9 | 13 | 109 |
| alert_2bfdf27fd14e6bbe | exit_via_mixer | planted | single | awaiting_approval | yes | 1.00 | 100% | 83% | 0 | 6 | 7 | 62 |
| alert_472b5560d7cf04cc | family_cycle | injected | orchestrated | needs_review | no | 0.00 |  |  | 0 | 9 | 13 | 154 |
| alert_472b5560d7cf04cc | family_cycle | injected | single | needs_review | no | 0.00 |  |  | 0 | 6 | 7 | 30 |
| alert_482b4987b6cd5334 | merchant_fan_in | decoy | orchestrated | closed_no_action | no | 0.00 |  |  | 0 | 9 | 13 | 94 |
| alert_482b4987b6cd5334 | merchant_fan_in | decoy | single | closed_no_action | no | 0.00 |  |  | 0 | 6 | 7 | 66 |
| alert_55921a59da9398a7 | shared_device | planted | orchestrated | closed_no_action | no | 0.00 |  |  | 0 | 9 | 13 | 73 |
| alert_55921a59da9398a7 | shared_device | planted | single | needs_review | no | 0.00 |  |  | 0 | 6 | 7 | 112 |
| alert_5b1fcdcc4caf9544 | round_trip | planted | orchestrated | awaiting_approval | yes | 1.00 | 100% | 100% | 0 | 9 | 13 | 149 |
| alert_5b1fcdcc4caf9544 | round_trip | planted | single | awaiting_approval | yes | 1.00 | 100% | 100% | 0 | 6 | 7 | 91 |
| alert_5cdb2555886c3ed5 | exit_via_mixer | planted | orchestrated | awaiting_approval | yes | 1.00 | 100% | 83% | 0 | 9 | 13 | 130 |
| alert_5cdb2555886c3ed5 | exit_via_mixer | planted | single | awaiting_approval | yes | 1.00 | 100% | 83% | 0 | 6 | 7 | 186 |
| alert_5e6ec004f4e71a5f | family_cycle | decoy | orchestrated | needs_review | no | 0.00 |  |  | 0 | 9 | 13 | 103 |
| alert_5e6ec004f4e71a5f | family_cycle | decoy | single | needs_review | no | 0.00 |  |  | 0 | 6 | 7 | 142 |
| alert_6a8f985f048773a2 | family_cycle | decoy | orchestrated | needs_review | no | 0.00 |  |  | 0 | 9 | 13 | 97 |
| alert_6a8f985f048773a2 | family_cycle | decoy | single | needs_review | no | 0.00 |  |  | 0 | 6 | 7 | 15 |
| alert_70d6ec4d9b9507fb | payroll_fan_out | decoy | orchestrated | closed_no_action | no | 0.00 |  |  | 0 | 9 | 13 | 109 |
| alert_70d6ec4d9b9507fb | payroll_fan_out | decoy | single | closed_no_action | no | 0.00 |  |  | 0 | 6 | 7 | 60 |
| alert_71c4251ac67afead | fan_in_structuring | injected | orchestrated | awaiting_approval | yes | 1.00 | 100% |  | 0 | 9 | 13 | 97 |
| alert_71c4251ac67afead | fan_in_structuring | injected | single | awaiting_approval | yes | 1.00 | 100% |  | 0 | 6 | 7 | 118 |
| alert_7b8fef8eeb933e4f | rapid_layering | planted | orchestrated | awaiting_approval | yes | 1.00 | 100% | 83% | 0 | 9 | 13 | 103 |
| alert_7b8fef8eeb933e4f | rapid_layering | planted | single | awaiting_approval | yes | 1.00 | 100% | 83% | 0 | 6 | 7 | 137 |
| alert_943e1db844ee13d2 | fan_in_structuring | planted | orchestrated | awaiting_approval | yes | 1.00 | 100% | 100% | 0 | 9 | 13 | 134 |
| alert_943e1db844ee13d2 | fan_in_structuring | planted | single | awaiting_approval | yes | 1.00 | 100% | 100% | 0 | 6 | 7 | 125 |
| alert_9d9c55d58621f478 | fan_out | planted | orchestrated | awaiting_approval | yes | 1.00 | 100% | 100% | 0 | 9 | 13 | 140 |
| alert_9d9c55d58621f478 | fan_out | planted | single | awaiting_approval | yes | 1.00 | 100% | 100% | 0 | 6 | 7 | 100 |
| alert_bdb56b7832344156 | fan_in_structuring | planted | orchestrated | awaiting_approval | yes | 1.00 | 100% | 100% | 0 | 9 | 13 | 149 |
| alert_bdb56b7832344156 | fan_in_structuring | planted | single | awaiting_approval | yes | 1.00 | 100% | 100% | 0 | 6 | 7 | 79 |
| alert_c47f594e70cf4999 | payroll_fan_out | decoy | orchestrated | closed_no_action | no | 0.00 |  |  | 0 | 9 | 13 | 162 |
| alert_c47f594e70cf4999 | payroll_fan_out | decoy | single | closed_no_action | no | 0.00 |  |  | 0 | 6 | 7 | 157 |
| alert_c6d593514721c9c2 | family_cycle | twin | orchestrated | needs_review | no | 0.00 |  |  | 0 | 9 | 12 | 115 |
| alert_c6d593514721c9c2 | family_cycle | twin | single | needs_review | no | 0.00 |  |  | 0 | 6 | 7 | 118 |
| alert_c9ea5b7dac3143b3 | fan_in_structuring | twin | orchestrated | awaiting_approval | yes | 1.00 | 100% |  | 0 | 9 | 12 | 161 |
| alert_c9ea5b7dac3143b3 | fan_in_structuring | twin | single | awaiting_approval | yes | 1.00 | 100% |  | 0 | 6 | 7 | 79 |
| alert_e64d0a1b37c6f576 | fan_out | planted | orchestrated | awaiting_approval | yes | 1.00 | 100% | 100% | 0 | 9 | 13 | 0 |
| alert_e64d0a1b37c6f576 | fan_out | planted | single | awaiting_approval | yes | 1.00 | 100% | 100% | 0 | 6 | 7 | 100 |
| alert_f0769649b5a90749 | peeling_chain | planted | orchestrated | awaiting_approval | yes | 1.00 | 100% | 100% | 0 | 9 | 13 | 134 |
| alert_f0769649b5a90749 | peeling_chain | planted | single | awaiting_approval | yes | 1.00 | 100% | 100% | 0 | 6 | 7 | 55 |

## Subset

alert_6a8f985f048773a2, alert_482b4987b6cd5334, alert_70d6ec4d9b9507fb, alert_71c4251ac67afead, alert_c9ea5b7dac3143b3, alert_2bfdf27fd14e6bbe, alert_bdb56b7832344156, alert_e64d0a1b37c6f576, alert_0a9fc98e637bfa85, alert_7b8fef8eeb933e4f, alert_5b1fcdcc4caf9544, alert_55921a59da9398a7, alert_5e6ec004f4e71a5f, alert_17e4dbca46b1babc, alert_c47f594e70cf4999, alert_472b5560d7cf04cc, alert_c6d593514721c9c2, alert_5cdb2555886c3ed5, alert_943e1db844ee13d2, alert_9d9c55d58621f478, alert_f0769649b5a90749

## Reading this report

- The workers ran the `scripted` model, a fixed non-LLM policy, because no Gemini key was
  available. These numbers measure the tools, ledger, verifier, scorer and circuit through
  the real pipeline. They do not measure how well a language model investigates.
- Token counts for the scripted model are Pydantic AI's estimates for a function model, not
  billed tokens, and no narrator requests appear because the verifier writes the template
  narrative in scripted mode.
- The single shared-device miss in each mode comes from the scripted policies, not the scorer:
  the scripted orchestrator never tests shared device, and the scripted open investigator's
  neighbour check did not satisfy the scorer, so the verifier sent it for review.
- The run stopped once at the API's daily case cap (50, a public-demo guard) and resumed from
  its saved progress on the same pinned subset. For the rest of the run the local API allowed
  500 cases a day. Seconds per case include waiting on the 10-requests-a-minute limiter, which
  paces the scripted model too.
