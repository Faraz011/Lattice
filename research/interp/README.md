# Inside the model: an attribution graph for one tool choice

This is a research showcase (U18, R23). It takes one tool choice a Lattice investigator made in
a recorded case and asks a small open model the same question as a multiple choice. It then
uses [circuit-tracer](https://github.com/safety-research/circuit-tracer) to build an
attribution graph for the answer. The UI shows a summary on its **Inside the model** page.

Read the result for what it is:

- It explains an **open model's** answer to a restated prompt. It does not explain the
  production investigator, which runs on a hosted model whose internals cannot be traced.
- It is never part of a verdict. The evidence circuit, the ledger and the risk scorer remain
  the system of record.
- Transcoders approximate the model. The panel reports how much of the answer's direct input
  comes from reconstruction error. A large share means the graph explains less.

## Files

| File | What it is |
| --- | --- |
| `step.json` | The recorded step: the brief, four lettered tools and the recorded answer. Committed, from `recordings/case_aa7780b9e6504f40.json` (peeling-chain investigator). |
| `tool_choice_attribution.ipynb` | Loads the model and transcoders, checks the model's own answer, builds and saves the graph, and writes the panel summary. |
| `graphs/` | Graph files written by the notebook. They are large and not committed. |
| `../../ui/public/interp/tool-choice.json` | The panel summary the UI loads (written by the notebook). |

## Reproducing it

### 1. Pick the step (any machine, in the Lattice environment)

```bash
uv run python -m lattice.interp.tool_choice --recording recordings/case_aa7780b9e6504f40.json --hypothesis peeling_chain
```

Or take a step from any saved case through the API:
`--case <case_id> --api http://localhost:8080`.

### 2. Run the notebook (a GPU machine)

| Model | Transcoders | Needs |
| --- | --- | --- |
| `Qwen/Qwen3-0.6B` (default) | `mwhanna/qwen3-0.6b-transcoders-lowl0` | Not gated. A few GB of GPU memory with CPU offloading; slow but possible on CPU. |
| `google/gemma-2-2b` | `gemma` (GemmaScope) | About 15 GB of GPU memory with offloading (Colab works), and a Hugging Face login with Gemma's licence accepted. |

Use a separate environment, so the heavy research dependencies stay out of the Lattice stack:

```bash
python -m venv .venv-interp
.venv-interp/Scripts/activate        # source .venv-interp/bin/activate on Linux or macOS
pip install torch --index-url https://download.pytorch.org/whl/cu124
git clone https://github.com/safety-research/circuit-tracer && pip install ./circuit-tracer
pip install jupyter pydantic
cd research/interp && jupyter notebook tool_choice_attribution.ipynb
```

The notebook adds the repository's `src/` to the path, so the panel summariser runs without
installing Lattice into this environment. Choose the model in cell 3. Step 4 shows the model's
own probabilities for each option. If the model does not favour the recorded answer, the graph
still explains the logit of that answer, and the panel shows the probabilities so a reader can
judge.

### 3. Show it in the UI

The notebook's last cell writes `ui/public/interp/tool-choice.json`. Rebuild or restart the UI,
then open **Inside the model** in the sidebar. To redo only the summary from an existing graph
file:

```bash
uv run python -m lattice.interp.graph_summary research/interp/graphs/<slug>.json
```

## Status

The extractor, summariser and UI panel are tested (`tests/unit/test_interp.py`, against a small
graph in circuit-tracer's file format). The notebook itself has not been run yet in this
repository: the development machine has a 4 GB GPU, and no model weights or transcoders were
downloaded. Run it on a GPU machine as described above, then commit the panel summary.
