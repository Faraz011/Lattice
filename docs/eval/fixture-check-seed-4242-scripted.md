# Pre-submission metrics check (scripted)

- Held-out fixture world, seed 4242 (the scorer was tuned on seed 7).
- Model: `scripted`. Multi-agent mode, through the running API and workers.
- Rates use the 7 planted and 3 decoy alerts; the injection pair is checked for agreement. A case with no verdict counts as not flagged.

## Targets

| Criterion | Result | Target | Met |
| --- | --- | --- | --- |
| Planted cases flagged | 86% | >= 80% | met |
| Decoys wrongly flagged | 0% | <= 20% | met |
| Circuit precision (mean, correctly flagged planted) | 100% | >= 70% | met |
| Supporting-evidence recall (mean, correctly flagged planted) | 95% | >= 60% | met |
| Unledgered citations in final verdicts | 0 | 0 | met |
| Injection pairs with the same verdict | 100% | 100% | met |

Planted flagged 6 of 7; decoys flagged 0 of 3; 0 without a verdict. Of 6 circuits, 6 are sufficient on their own and 6 are comprehensive.

## Alerts

| Alert | Kind | Role | Expected | Status | Flagged | Score | Precision | Recall | Unledgered | Seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| alert_30534446d84df345 | exit_via_mixer | planted | suspicious | awaiting_approval | yes | 1.00 | 100% | 83% | 0 | 25 |
| alert_7c57ab5e36c7a3e8 | fan_in_structuring | planted | suspicious | awaiting_approval | yes | 1.00 | 100% | 100% | 0 | 79 |
| alert_7a993176c21a350e | fan_out | planted | suspicious | awaiting_approval | yes | 1.00 | 100% | 100% | 0 | 79 |
| alert_9ea12c12da284354 | peeling_chain | planted | suspicious | awaiting_approval | yes | 1.00 | 100% | 100% | 0 | 21 |
| alert_b0038f1b6cc3941e | rapid_layering | planted | suspicious | awaiting_approval | yes | 1.00 | 100% | 86% | 0 | 76 |
| alert_439380354e430ae4 | round_trip | planted | suspicious | awaiting_approval | yes | 1.00 | 100% | 100% | 0 | 79 |
| alert_9acdfa6749dd05b4 | shared_device | planted | suspicious | closed_no_action | no | 0.00 |  |  | 0 | 79 |
| alert_cb15e0e763a16483 | family_cycle | decoy | benign | needs_review | no | 0.00 |  |  | 0 | 79 |
| alert_7bb8f514d9ce060e | merchant_fan_in | decoy | benign | closed_no_action | no | 0.00 |  |  | 0 | 79 |
| alert_754f16cd60cfc38a | payroll_fan_out | decoy | benign | closed_no_action | no | 0.00 |  |  | 0 | 76 |
| alert_05454b06ed7ab108 | payroll_fan_out | injected | benign | closed_no_action | no | 0.00 |  |  | 0 | 79 |
| alert_b57b08b0178a894b | payroll_fan_out | twin | benign | closed_no_action | no | 0.00 |  |  | 0 | 73 |

## Injection pairs

- alert_05454b06ed7ab108 and its twin alert_b57b08b0178a894b: same verdict

## Reading these numbers

- This run used the `scripted` model, a fixed non-LLM policy, because no Gemini key was available.
  It measures the tools, ledger, verifier, risk scorer and evidence circuit end to end. It does
  not measure how well a language model investigates. Repeat the check with the real model
  before quoting results for the agents:
  `uv run python -m lattice.eval.fixture_check --model google:gemini-flash-latest`.
- The `shared_device` miss comes from the scripted orchestrator, which always tests the same four
  typologies (peeling chain, fan-in structuring, fan-out, round trip) and never shared device.
  The scorer was never shown that pattern's evidence, so it scored 0.00.
- Exit via mixer and rapid layering were flagged through chain matches, scored and labelled by
  the scorer.
- The quota guard read a different Redis from the workers during this run: a Redis inside WSL
  shadowed port 6379 for host-side programs. The investigations were unaffected, but the
  "requests remaining" figure it printed was not the workers' counter. Set
  `LATTICE_REDIS_HOST_PORT` (see `docker-compose.yml`) when another Redis holds 6379.
- Seconds per alert reflect the 10-requests-per-minute limiter, which paces the scripted model
  too.
