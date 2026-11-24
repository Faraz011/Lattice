# Backup routes: greedy circuit vs route search (demo world, seed 2026)

- Planted cases: 47; flagged on their planted evidence plus 30 noise edges: 47.
- Mean greedy circuit: 5.8 edges, mean sufficiency 0.75.
- Cases with a second body of evidence (`redundant`): 6 of 47. The circuit alone shows only one route for these.
- Freezes: 292 accounts sit on a greedy circuit, so each looks essential from the circuit alone. Counting backup routes, 108 of them really stop the case; 184 would leave it standing.
- Showcase cases with planted parallel routes: 2. Planted routes recovered: 4 of 4; inferred roles correct: 18 of 18.

| Case | Kind | Circuit edges | Sufficiency | Redundant | Routes found | Accounts on circuit | Really essential | Planted routes recovered | Roles correct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| planted-peeling_chain-01 | peeling_chain | 7 | 0.75 | no | 1 | 8 | 2 |  |  |
| planted-peeling_chain-02 | peeling_chain | 7 | 0.75 | no | 1 | 8 | 2 |  |  |
| planted-peeling_chain-03 | peeling_chain | 7 | 0.75 | no | 1 | 8 | 4 |  |  |
| planted-peeling_chain-04 | peeling_chain | 7 | 0.75 | no | 1 | 8 | 2 |  |  |
| planted-peeling_chain-05 | peeling_chain | 7 | 0.75 | no | 1 | 8 | 2 |  |  |
| planted-peeling_chain-06 | peeling_chain | 7 | 0.75 | no | 1 | 8 | 4 |  |  |
| planted-fan_in_structuring-01 | fan_in_structuring | 9 | 0.62 | no | 1 | 10 | 1 |  |  |
| planted-fan_in_structuring-01-twin | fan_in_structuring | 9 | 0.62 | no | 1 | 10 | 1 |  |  |
| planted-fan_in_structuring-02 | fan_in_structuring | 9 | 0.62 | no | 1 | 10 | 1 |  |  |
| planted-fan_in_structuring-03 | fan_in_structuring | 9 | 0.62 | yes | 1 | 10 | 1 |  |  |
| planted-fan_in_structuring-04 | fan_in_structuring | 9 | 0.62 | no | 1 | 10 | 1 |  |  |
| planted-fan_in_structuring-05 | fan_in_structuring | 9 | 0.62 | no | 1 | 10 | 1 |  |  |
| planted-fan_in_structuring-06 | fan_in_structuring | 9 | 0.62 | yes | 1 | 10 | 1 |  |  |
| planted-fan_out-01 | fan_out | 9 | 0.67 | no | 1 | 10 | 2 |  |  |
| planted-fan_out-02 | fan_out | 9 | 0.67 | no | 1 | 10 | 2 |  |  |
| planted-fan_out-03 | fan_out | 9 | 0.67 | no | 1 | 10 | 2 |  |  |
| planted-fan_out-04 | fan_out | 9 | 0.67 | no | 1 | 10 | 2 |  |  |
| planted-fan_out-05 | fan_out | 9 | 0.67 | no | 1 | 10 | 2 |  |  |
| planted-fan_out-06 | fan_out | 9 | 0.67 | no | 1 | 10 | 2 |  |  |
| planted-round_trip-01 | round_trip | 4 | 1.00 | no | 1 | 4 | 4 |  |  |
| planted-round_trip-02 | round_trip | 3 | 1.00 | no | 1 | 3 | 3 |  |  |
| planted-round_trip-03 | round_trip | 4 | 1.00 | no | 1 | 4 | 4 |  |  |
| planted-round_trip-04 | round_trip | 5 | 1.00 | no | 1 | 5 | 5 |  |  |
| planted-round_trip-05 | round_trip | 4 | 1.00 | no | 1 | 4 | 4 |  |  |
| planted-round_trip-06 | round_trip | 5 | 1.00 | no | 1 | 5 | 5 |  |  |
| planted-rapid_layering-01 | rapid_layering | 4 | 0.67 | no | 1 | 5 | 3 |  |  |
| planted-rapid_layering-02 | rapid_layering | 4 | 0.67 | no | 1 | 5 | 3 |  |  |
| planted-rapid_layering-03 | rapid_layering | 4 | 0.67 | no | 1 | 5 | 4 |  |  |
| planted-rapid_layering-04 | rapid_layering | 4 | 0.67 | no | 1 | 5 | 4 |  |  |
| planted-rapid_layering-05 | rapid_layering | 4 | 0.67 | no | 1 | 5 | 3 |  |  |
| planted-rapid_layering-06 | rapid_layering | 4 | 0.67 | no | 1 | 5 | 3 |  |  |
| planted-shared_device-01 | shared_device | 6 | 0.60 | no | 1 | 4 | 1 |  |  |
| planted-shared_device-02 | shared_device | 6 | 0.60 | no | 1 | 4 | 1 |  |  |
| planted-shared_device-03 | shared_device | 6 | 0.60 | no | 1 | 4 | 1 |  |  |
| planted-shared_device-03-twin | shared_device | 6 | 0.60 | no | 1 | 4 | 1 |  |  |
| planted-shared_device-04 | shared_device | 6 | 0.60 | yes | 1 | 4 | 1 |  |  |
| planted-shared_device-05 | shared_device | 6 | 0.60 | yes | 1 | 4 | 1 |  |  |
| planted-shared_device-06 | shared_device | 6 | 0.60 | no | 1 | 4 | 1 |  |  |
| planted-exit_via_mixer-01 | exit_via_mixer | 2 | 1.00 | no | 1 | 3 | 3 |  |  |
| planted-exit_via_mixer-02 | exit_via_mixer | 2 | 1.00 | no | 1 | 3 | 3 |  |  |
| planted-exit_via_mixer-03 | exit_via_mixer | 2 | 1.00 | no | 1 | 3 | 3 |  |  |
| planted-exit_via_mixer-04 | exit_via_mixer | 2 | 1.00 | no | 1 | 3 | 3 |  |  |
| planted-exit_via_mixer-05 | exit_via_mixer | 2 | 1.00 | no | 1 | 3 | 3 |  |  |
| planted-exit_via_mixer-06 | exit_via_mixer | 2 | 1.00 | no | 1 | 3 | 3 |  |  |
| planted-exit_via_mixer-06-twin | exit_via_mixer | 2 | 1.00 | no | 1 | 3 | 3 |  |  |
| planted-parallel_mules-01 | parallel_mules | 4 | 0.67 | yes | 2 | 5 | 0 | 2 of 2 | 9 of 9 |
| planted-parallel_mules-02 | parallel_mules | 4 | 0.67 | yes | 2 | 5 | 0 | 2 of 2 | 9 of 9 |

Scored offline with the deterministic scorer, no model. Each case's evidence is its planted edges plus 30 random background transfers, seeded by case. A column for the research search (the backup-aware search on GPT-2) belongs here once it runs on these cases.
