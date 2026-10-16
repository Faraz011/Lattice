# Lattice UI

The analyst console: pick an alert, watch the agents investigate, read the evidence circuit and
decide on the proposed action.

```bash
npm install
npm run dev          # http://localhost:5173, talks to the API at VITE_API_URL (default :8080)
npm test             # component and state tests (Vitest)
npm run build && npm run check:bundle   # the approver token must never be in the bundle
```

The API's `LATTICE_CORS_ORIGINS` must include the UI's origin. To run the whole flow without a
model key, start the workers with `LATTICE_MODEL=scripted`: a fixed, non-LLM policy that calls
the real tools, so the verifier, circuit and approval gate behave as they do with a real model.

The approver token is typed into the approval panel at runtime and kept in this tab's session
storage. It is never a `VITE_` variable.

## Layout

- `src/api.ts`: REST calls and the live event stream (EventSource reconnects by itself).
- `src/caseState.ts`: one view of a case, folded from its events; live mode overlays the stored
  case record, replay mode uses the recorded events and snapshot alone.
- `src/useCase.ts`: the live and replay hooks.
- `src/components/`: the alert list, stage bar and hypothesis lanes, graph (Cytoscape), edge
  inspector, verdict, narrative, counterfactuals, and approval and review panels.
