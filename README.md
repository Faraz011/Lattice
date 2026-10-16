# Lattice

AML investigation agents that act on a Neo4j transaction graph. An orchestrator fans each alert
out to investigators, one per laundering pattern. They work through typed MCP graph tools, and
a verifier scores what they cite. Every flagged verdict comes with its evidence circuit: the
smallest set of transfers that keeps the decision. Freezes and escalations wait for a person to
approve them.

```bash
cp .env.example .env
docker compose --profile app up -d --build    # UI at http://localhost:8081
```

- `LATTICE_MODEL=scripted` runs the whole flow without a model key.
- [docs/deploy.md](docs/deploy.md) covers scaling, the Render blueprint and its cost.
- [docs/plans](docs/plans) holds the design.

Development: `docker compose up -d` (Neo4j and Redis only), `uv run pytest`, and `npm test` in
`ui/`.
