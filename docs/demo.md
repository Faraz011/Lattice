# The freeze demo: "what if we freeze this account?" (5 minutes, hackathon panel)

One method explains both an AML evidence graph and a neural network: find the smallest set of
evidence that keeps a decision, then search again for the backup routes that also keep it.
In Lattice that answers the question an investigator actually asks before freezing an
account: will this stop the activity?

## Setup (before the panel)

```bash
docker compose up -d neo4j redis
uv run python -m lattice.datagen.cli --world demo --load
LATTICE_MODEL=scripted docker compose --profile app up -d --build   # UI on http://localhost:8081
```

Use the scripted model for a demo that can't fail on a rate limit, or a Gemini key for real
agents. Run both showcase alerts once beforehand, so their replays exist as a fallback
(every verdict is saved as a replay).

Verification takes about 2.5 minutes per case. The LLM attribution asks the judge 16 times,
and those calls wait on the 10-a-minute rate limit even with the scripted model. For a live
run in front of the panel, either open the cases you ran beforehand, or start the stack with
`LATTICE_LLM_ATTRIBUTION_SAMPLES=0` to skip that panel; verification then takes seconds.

| Alert | Case | Why |
| --- | --- | --- |
| `alert_b5b2e6b091b6cd4e` | planted-parallel_mules-01 | The star: two parallel mule routes, one planted as a backup. |
| `alert_98a112c495f0c6a9` | planted-rapid_layering-01 | The contrast: one route, so most freezes stop it. |

## The five minutes

1. **The alert (30 s).** Open `alert_b5b2e6b091b6cd4e`, "large inbound split across new
   accounts". Agents fan out, one per laundering pattern, and the graph grows from what their
   tools return. Every edge they cite is checked against the tool-call ledger.
2. **The explanation (45 s).** The verdict: rapid layering, score 1.00. The numbered red edges
   are the evidence circuit, the 4 transfers that on their own keep the flag. Most tools stop
   here: "these transfers explain the alert".
3. **The freeze (90 s), the moment.** Under "What if we freeze an account?", freeze a mule on
   the red circuit. Reading the circuit alone, the case should collapse. It doesn't: the score
   stays at 0.67, the frozen account is marked, and a dashed route, B1–B4, lights up. The money
   still reaches the collector through a second mule chain. "No single account here is
   essential." Then open the contrast alert and freeze a mule in the middle of the chain (the
   third, `acct_eaf60e`): "The case no longer flags. This account is essential." Only the 3
   middle mules are; freezing an account at either end leaves a chain long enough to flag.
4. **Explanation size (30 s).** Drag "How much explanation do you want?". Below the minimal
   size, the strongest transfers alone don't flag; at it, they do; above it, you see how much
   of the full score each extra transfer adds.
5. **Roles (30 s).** "2 independent routes prove this case": originator, mules, collector,
   read from the flow of funds, not from labels. Within a route every hop needs the previous
   one (AND); the routes are backups for each other (OR).
6. **The SAR draft (30 s).** "Read draft": the circuit, the backup route, the roles and the
   freeze assessments, written only from computed facts.
7. **Credibility (45 s).** Sidebar, "Same method on GPT-2": the same search on a neural
   network, against Edge Pruning. Then the numbers sheet below.

## The numbers sheet

[`docs/eval/backup-routes-demo-2026.md`](eval/backup-routes-demo-2026.md), regenerated with
`uv run python -m lattice.eval.backup_routes --out docs/eval/backup-routes-demo-2026.md`. On
the 47 planted cases of the demo world:

- **Circuit membership is not essentiality.** 292 accounts sit on a greedy circuit, so a reader
  of the circuit alone would expect each freeze to stop the case. Only 108 of them do; 184
  would leave it standing, because the remaining evidence rebuilds a sufficient set.
- The two showcase cases: planted routes recovered 4 of 4, inferred roles correct 18 of 18,
  and 0 of 5 circuit accounts essential, against 3–4 of 5 on single-route rapid layering.

## The GPT-2 credibility panel

Lattice does not compute these numbers; they come from the research code. Drop them in
`ui/public/research/credibility.json` and rebuild the UI:

```json
{
  "title": "Same method, on a neural network",
  "summary": "The backup-aware circuit search recovers the published IOI circuit in GPT-2 small.",
  "model": "GPT-2 small",
  "rows": [
    {"measure": "KL to the full model (lower is better)", "ours": "0.55", "baseline": "0.50",
     "baseline_name": "Edge Pruning", "note": "about a third of the compute"},
    {"measure": "Score with the main path ablated", "ours": "0.27", "baseline": "0.04",
     "baseline_name": "Edge Pruning", "note": "a working backup path"}
  ],
  "source": "the research notebook and commit the numbers come from",
  "caveat": "Optional: anything a reviewer should know."
}
```

Verify every number against its source before the panel. The page shows exactly what the file
says.

## What to say if asked

- **The scorer is rules, not a neural network.** The search and the backup objective only need
  a scorer to call, so they carry over unchanged. A gradient pre-filter matters only for
  neural scorers.
- **"Freeze" here is a what-if on the evidence.** It removes every transfer the account took
  part in and rescores. It answers whether the remaining evidence still proves the activity,
  which for a collector can differ from whether money can still move. Real freezes still go
  through the approval gate.
- **Backup routes are proven only where they were planted.** On real data (Elliptic2) there is
  no ground truth: the routes can be shown, not proven to be the real ones.
- **The investigators must cite both routes.** The scorer only sees cited evidence, so the
  chain tool returns maximal paths, and two routes out of one account are both reported.
