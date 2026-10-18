# Evaluation report (scripted)

- elliptic2 (seed 2, from elliptic2-manifest.json); 5 alerts, modes: orchestrated.
- Model: `scripted`. Each case ran through the API, MCP server and workers.
- Every alert in the world was run.
- Rates use planted and decoy alerts; injection pairs are checked for agreement. A case with no verdict counts as not flagged.

## Success Criteria

| Criterion | orchestrated | Target |
| --- | --- | --- |
| Planted cases flagged | 50% (missed) | >= 80% |
| Decoys wrongly flagged | 0% (met) | <= 20% |
| Circuit precision (mean, correctly flagged planted) | 100% (met) | >= 70% |
| Supporting-evidence recall (mean, correctly flagged planted) | 100% (met) | >= 60% |
| Unledgered citations in final verdicts | 0 (met) | 0 |
| Injection pairs with the same verdict | n/a (n/a) | 100% |

## Run statistics (R21)

| Criterion | orchestrated | Notes |
| --- | --- | --- |
| Decision accuracy | 80% | planted flagged and decoys not flagged |
| Sufficient circuits | 1 of 1 | circuit alone keeps the verdict |
| Comprehensive circuits | 1 of 1 | rest falls below threshold |
| Cases citing IDs no tool returned | 0 of 5 (0 IDs) | dropped by the verifier before the verdict |
| Unledgered IDs in final verdicts | 0 | must be 0 |
| Tool calls per case | 9 / 9 / 9 | mean / median / max |
| Model requests per case | 9 / 8 / 12 | mean / median / max, cache hits excluded |
| Cache hits | 21 | responses reused, no cost |
| Input tokens per case | 1523 / 1402 / 1973 | mean / median / max |
| Output tokens per case | 261 / 254 / 274 | mean / median / max |
| Seconds per case | 131 / 118 / 204 | mean / median / max |
| Cost per case | not priced | pass --price-in/--price-out |

### Tool calls by tool

| Tool | orchestrated |
| --- | --- |
| graph_get_node | 20 |
| graph_match_pattern | 20 |
| graph_neighbors | 5 |

### Model requests by role

| Role | orchestrated |
| --- | --- |
| investigator | 44 |
| orchestrator | 0 |

## Cases

| Alert | Kind | Role | Mode | Status | Flagged | Score | Precision | Recall | Rejected | Tool calls | Requests | Seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| alert_ellcc1 | elliptic2_subgraph | planted | orchestrated | awaiting_approval | yes | 0.75 | 100% | 100% | 0 | 9 | 8 | 204 |
| alert_ellcc2 | elliptic2_subgraph | decoy | orchestrated | closed_no_action | no | 0.00 |  |  | 0 | 9 | 8 | 186 |
| alert_ellcc3 | elliptic2_subgraph | planted | orchestrated | closed_no_action | no | 0.00 |  |  | 0 | 9 | 8 | 61 |
| alert_ellcc4 | elliptic2_subgraph | decoy | orchestrated | closed_no_action | no | 0.00 |  |  | 0 | 9 | 8 | 88 |
| alert_ellcc5 | elliptic2_subgraph | decoy | orchestrated | closed_no_action | no | 0.00 |  |  | 0 | 9 | 12 | 118 |
