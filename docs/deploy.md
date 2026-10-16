# Deploying Lattice

Every role runs from one image (`Dockerfile`), picked by its command: `lattice api`,
`lattice mcp`, `lattice worker <role>`, `lattice seed`. Locally that is Docker Compose; on Render,
one service per role from `render.yaml`.

## Locally with Docker Compose

```bash
cp .env.example .env                      # set LATTICE_NEO4J_PASSWORD and LATTICE_APPROVER_TOKEN
docker compose --profile app up -d --build
```

- The UI is at http://localhost:8081 and the API at http://localhost:8080.
- `seed` loads the demo world into an empty database, imports `recordings/*.json`, and exits.
  The API waits for it.
- Two investigators start by default. Change that with
  `docker compose --profile app up -d --scale investigator=4`. Replicas share one queue, and a
  job held by a replica that dies is picked up by another once it has been idle for
  `LATTICE_JOB_IDLE_TIMEOUT_S`.
- Without a model key, add `LATTICE_MODEL=scripted` in front of the command. A fixed, non-LLM
  policy then drives the real tools, verifier and approval gate.
- `docker compose up -d` without the profile starts only Neo4j and Redis. That is what local
  development and the test suite use.

The end-to-end check runs against this stack:

```bash
uv run python -m lattice.datagen.cli --world fixture --load
LATTICE_MODEL=scripted docker compose --profile app up -d --build
uv run pytest -m compose
```

It has two tests:

- A planted peeling chain reaches `awaiting_approval` within five minutes, with a circuit, a
  blast radius and a saved recording.
- Killing an investigator container mid-case still yields a verdict.

## On Render

`render.yaml` is a Render Blueprint. It was checked against Render's published schema
(`https://render.com/schema/render.yaml.json`). Render's own validation runs when the Blueprint
is applied.

1. Push the branch to GitHub, then in Render choose **New → Blueprint** and pick the repository.
2. When Render asks for `LATTICE_GEMINI_API_KEY`, paste the key. For an offline demo, set
   `LATTICE_MODEL` to `scripted` in the `lattice-shared` group instead.
3. Apply. The API's pre-deploy step runs `lattice seed --if-empty`.
4. Open the `lattice-shared` environment group and copy `LATTICE_APPROVER_TOKEN`. Approvers type
   it into the UI. It is never built into the UI.
5. Check the two public addresses. The Blueprint assumes Render names the services
   `lattice-api.onrender.com` and `lattice-ui.onrender.com`. If Render adds a suffix, update
   `VITE_API_URL` on `lattice-ui` (then redeploy it) and `LATTICE_CORS_ORIGINS` on
   `lattice-api`.

### What runs where

| Service | Render type | Plan | Notes |
| --- | --- | --- | --- |
| `lattice-neo4j` | Private service | Standard (2 GB) | Wrapper image in `deploy/neo4j` with APOC and GDS, 10 GB disk at `/data` |
| `lattice-redis` | Key Value | Starter | `noeviction`, so queued jobs and fan-in state are never dropped |
| `lattice-mcp` | Private service | Starter | MCP tool server, reachable only on the private network |
| `lattice-api` | Web service | Starter | Public API and SSE; health check `/health` |
| `lattice-orchestrator` | Background worker | Starter | Also runs the sweeper |
| `lattice-investigator` | Background worker | Starter × 2 | Scale with `numInstances` |
| `lattice-verifier` | Background worker | Starter | Writes the template narrative when `LATTICE_MODEL=scripted` |
| `lattice-action` | Background worker | Starter | The only role that executes actions (simulated) |
| `lattice-ui` | Static site | Free | Built from `ui/` |

Neo4j's free cloud tier has no GDS (KTD14), so the graph runs as its own container here too.
The password is generated once in `lattice-shared`. The wrapper image turns it into
`NEO4J_AUTH`, so the database and the app roles always agree on it.

### Expected monthly cost (for sign-off)

These are from Render's published plans as of October 2026: Starter $7, Standard $25, and disks
at $0.25 per GB. The Key Value Starter price is unconfirmed: check it at
https://render.com/pricing before applying. Billing is prorated by the second, so suspending the
services after the demo stops the compute charges.

| Line | Monthly |
| --- | --- |
| Neo4j, Standard private service | $25.00 |
| Neo4j disk, 10 GB | $2.50 |
| Key Value, Starter | about $10 (confirm) |
| MCP server, Starter private service | $7.00 |
| API, Starter web service | $7.00 |
| Workers: orchestrator, 2 investigators, verifier, action (5 × Starter) | $35.00 |
| UI, static site | $0 |
| **Total** | **about $86.50 a month**, plus model usage |

Ways to spend less:

- Run one investigator (−$7).
- Shrink the disk to 5 GB (−$1.25). The demo world needs well under 1 GB.
- Suspend everything between demos.

The Gemini cost depends on the key's tier and is capped by `LATTICE_LLM_REQUESTS_PER_DAY` and
`LATTICE_MAX_CASES_PER_DAY`. A workspace on a paid Render team plan adds that plan's per-seat fee.

### Known limits

- The approver token is shared by everyone who approves. Rotating it means changing it in
  `lattice-shared` and redeploying the API.
- A public UI lets anyone start investigations. The case caps (`LATTICE_MAX_ACTIVE_CASES`,
  `LATTICE_MAX_CASES_PER_DAY`) bound what that can cost.
