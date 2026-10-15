# Lattice — Research Foundations

**Problem:** build an agent that uses a graph to decide and act. Example uses: investigating fraud, triaging security findings, working through a codebase.
**Key focus:** multi-hop reasoning · graph queries and algorithms as agent tools · tool selection through MCP · actions based on what the graph shows · explainable results.

Compiled 2026-10-15. Each source is tagged by how it was checked:
- **[v]**: checked against the paper, its abstract or an official page during this research pass.
- **[k]**: a well-known, established work cited from background knowledge. Check the arXiv ID before you quote it.
- **[s]**: seen only in a search snippet or a reference list. Treat it as a lead, not as evidence.

---

## 0. TL;DR: the one idea worth building around

Mechanistic interpretability has a precise answer to the question "why did the model do X?" The answer is a **circuit**: the **smallest subgraph** of the computation that still reproduces the behavior. It is found by **ablating** edges and checking whether the output changes (ACDC, EAP, EAP-IG). The method has three strengths:

- It is **causal**. An edge counts only if removing it changes the result.
- It is **minimal**. Edges that don't matter are pruned away.
- It is **measurable**. Faithfulness is a number, not an impression.

**Our agent already works on a graph. So we can give the same kind of explanation for its decisions, applied to the *evidence graph* rather than the neural network:**

> *"This account was flagged because of this 6-edge subgraph. Removing any of these edges drops the risk score below threshold (necessity). These 6 edges alone keep it above threshold (sufficiency). If edge e₃ (the shared device) did not exist, the verdict would flip (counterfactual)."*

This turns "explainable results" from a chain-of-thought story into an **ablation-tested evidence circuit**. Section 2.3 shows why that matters: research from 2023–2026 shows chain-of-thought is *not* a faithful account of why a model decided something. The rest of this document is the evidence for this design and the parts needed to build it.

---

## 1. Mechanistic interpretability and circuit discovery

### 1.1 Core methods (the lineage)

| Method | What it does | Why we care |
|---|---|---|
| **Activation / path patching** ([IOI, Wang et al. 2022, arXiv 2211.00593] [k]; [path patching, Goldowsky-Dill et al. 2023, 2304.05969] [k]) | Run the model on a *clean* input and a *corrupted* input. Swap activations along specific paths and measure the change in output. | This is the template for counterfactual evidence testing: actual graph vs. graph with an edge removed. |
| **Causal scrubbing** (Chan et al., Redwood 2022) [k] | Tests a stated *hypothesis* about a circuit by resampling everything the hypothesis says is irrelevant. | A rigorous way to state "the explanation is X" and then try to break it. |
| **ACDC: Automated Circuit DisCovery** ([Conmy et al., NeurIPS 2023, arXiv 2304.14997] [k]) | Walks the computational graph from output to input. Removes each edge, keeps it only if the KL-divergence change is above threshold τ. Output is a sparse circuit. | **The direct template for our explanation algorithm** (see §7.3). |
| **Edge Attribution Patching (EAP)** ([Syed, Rager, Conmy 2023, arXiv 2310.10348] [k]) | A linear (gradient) approximation of ACDC. Scores *every* edge with 2 forward passes + 1 backward pass, so it is orders of magnitude faster. [v: [emergentmind EAP](https://www.emergentmind.com/topics/edge-attribution-patching-eap)] | The idea "score all edges cheaply, then prune" also works when our scorer is differentiable or additive. |
| **EAP-IG** ([Hanna, Pezzelle, Belinkov, "Have Faith in Faithfulness", COLM 2024, arXiv 2403.17806] [k]; [code](https://github.com/hannamw/eap-ig) [v]) | Averages EAP gradients along an integrated-gradients path between clean and corrupted inputs. Argues that circuits must be judged on **faithfulness**, not on overlap with hand-found circuits. | The faithfulness-first evaluation stance. |
| **EAP-GP** ([arXiv 2502.06852](https://arxiv.org/pdf/2502.06852)) [v] | Replaces EAP-IG's straight-line path with an adaptive path to reduce gradient saturation. Higher faithfulness than EAP/EAP-IG on IOI and Greater-Than, but slower. | Shows the speed vs. faithfulness trade-off. |
| **Edge Pruning** (Bhaskar et al., NeurIPS 2024, arXiv 2406.16778) [k] | Learns a continuous mask over edges (hard-concrete relaxation) by gradient descent. | Optimization instead of greedy search, for larger graphs. |
| **CD-T** ([ICLR 2025, arXiv 2407.00886](https://arxiv.org/pdf/2407.00886)) [v] | Contextual decomposition for transformers. Reports ~97% ROC-AUC recovering manual circuits (IOI, Greater-than, docstring), running in seconds instead of hours. Self-reported. | Fast and deterministic. |
| **Hybrid attribution + pruning** ([arXiv 2510.03282](https://arxiv.org/pdf/2510.03282)) [v] | Uses cheap attribution to pick candidates, then exact pruning to confirm. Built because pure ACDC doesn't scale. | **This is the pattern we should copy**: cheap scoring first, causal confirmation on the shortlist. |

### 1.2 Benchmarks for circuit discovery

- **MIB: Mechanistic Interpretability Benchmark** ([Mueller et al., ICML 2025, arXiv 2504.13151](https://arxiv.org/abs/2504.13151); [GitHub](https://github.com/aaronmueller/MIB)) [v]
  - Two tracks covering four tasks and five models.
  - The circuit track scores methods with **Circuit Performance Ratio** and **Circuit–Model Distance**.
  - Finding: attribution and mask-optimization methods, **EAP-IG** in particular, perform best.
  - It was extended into the BlackboxNLP 2025 shared task.
  - *Lesson for us: define faithfulness metrics before choosing a method.*
- **"Many Circuits, One Mechanism"** ([arXiv 2606.06267](https://arxiv.org/pdf/2606.06267)) [s]: circuit discovery results depend on input variation and on how finely they are evaluated. Our explanations should be checked against several perturbations, not one.

### 1.3 Features, transcoders and attribution graphs

- **Sparse autoencoders (SAEs)** split activations into interpretable "features". Key papers:
  - Towards Monosemanticity, 2023 [k]
  - Scaling Monosemanticity, 2024 [k]
  - Gemma Scope, DeepMind 2024, arXiv 2408.05147 [k]
  - Sparse Feature Circuits, Marks et al. 2024, arXiv 2403.19647 [k]
- **Transcoders** (Dunefsky et al. 2024, arXiv 2406.11944) [k] and **cross-layer transcoders** replace MLPs with sparse, readable stand-ins. This makes **attribution graphs** possible: per-prompt graphs of how features influence each other and the output. Key papers: "Circuit Tracing" (Ameisen et al., 2025) and "On the Biology of a Large Language Model" (Lindsey et al., 2025), both on transformer-circuits.pub [k].
- **circuit-tracer** ([PyPI, v0.5.0, March 2026](https://pypi.org/project/circuit-tracer/); [BlackboxNLP 2025 paper](https://aclanthology.org/2025.blackboxnlp-1.14.pdf)) [v]
  - The open-source reference implementation.
  - Computes attribution graphs from pretrained transcoders.
  - Includes a browser visualizer and feature interventions for testing circuits.
  - Works with open models such as Gemma and Llama, and integrates with Neuronpedia.
- **2026 follow-ups**, all [s]:
  - **ADAG** ([2604.07615](https://arxiv.org/pdf/2604.07615)): automatically clusters features and describes attribution graphs in language.
  - **Circuit-Diff** ([2609.23892](https://arxiv.org/pdf/2609.23892)): localizes knowledge in attribution graphs through factual-edit interventions.
  - **Probe Prompting** ([2511.07002](https://arxiv.org/pdf/2511.07002)): automates interpretation of attribution graphs.

### 1.4 Honest caveats (read before over-investing)

- **SAEs vs. simple probes.**
  - "Are Sparse Autoencoders Useful?" ([Kantamneni, Engels, Rajamanoharan, Tegmark, Nanda, ICML 2025, arXiv 2502.16681](https://arxiv.org/pdf/2502.16681)) [v] found that SAE probes underperform plain logistic regression on average.
  - DeepMind's interpretability team reported SAEs underperforming linear probes on detecting harmful intent out of distribution, and **deprioritized fundamental SAE research** in March 2025 [v, via summaries].
  - "Sanity Checks for SAEs" ([arXiv 2602.14111](https://www.arxiv.org/abs/2602.14111)) [v-abstract] found that random baselines nearly match trained SAEs on several metrics.
- **Attribution graphs can be unfaithful.** A post by Lange et al. argues cross-layer transcoders can be pushed toward learning unfaithful circuits [s].
- **Open problems.** "Open Problems in Mechanistic Interpretability" (Sharkey et al., 2025, arXiv 2501.16496) [k] is the best map of what is still unsolved.

**Takeaway for Lattice:** don't make neural-level interpretability the core deliverable. We will call a closed model (Claude) through an API, so we can't trace its circuits. Borrow the **methodology** instead (ablation, minimality, faithfulness metrics) and apply it to the evidence graph. Optional stretch goal: an "inside the model" demo using circuit-tracer on a small open model. §8 covers this.

### 1.5 Interpretability *of agents and tool use* (2025–2026, emerging)

These are early preprints. Use them as leads, not as foundations.

- **"Beyond the Black Box: Interpretability of Agentic AI Tool Use"** ([arXiv 2605.06890](https://arxiv.org/html/2605.06890v3)) [s]: monitors SAE features *before each action* in multi-step agents to read "tool-need" and "tool-risk" signals.
- **Tool calling is linearly readable and steerable** (2605.07990) [s]; **tool-call dependency structure is linearly decodable** from residual streams ([2605.25310](https://arxiv.org/pdf/2605.25310)) [s]; **internal representations as hallucination indicators in tool selection** (2601.05214) [s].
- **Conformal interpretability of temporal concepts in LLM agents** ([arXiv 2604.19775](https://arxiv.org/abs/2604.19775), ICML 2026 MI Workshop) [s]: concepts linked to agent success are linearly separable over time on ScienceWorld/ALFWorld.
- **HyVE, agents as circuit explainers** ([arXiv 2606.24026](https://arxiv.org/pdf/2606.24026)) [s]: an agent runs an observe → hypothesize → validate loop to explain a circuit. The loop structure is the same one our investigator agent needs.
- **"Agentic interpretability"** ([arXiv 2506.12152](https://arxiv.org/pdf/2506.12152)) [s]: a different sense of the term. It means the LLM actively helps a human build understanding over multiple turns. This is relevant to how we present explanations to analysts.

---

## 2. Explainability of agent decisions

### 2.1 Graph explainers (explanations as subgraphs)

| Method | Idea |
|---|---|
| **GNNExplainer** (Ying et al., NeurIPS 2019, arXiv 1903.03894) [k] | Learns a soft edge/feature mask that maximizes mutual information with the prediction. Output is a compact explanatory subgraph. |
| **PGExplainer** (Luo et al., NeurIPS 2020, arXiv 2011.04573) [k] | A parameterized, inductive mask generator. Fast at inference. |
| **SubgraphX** (Yuan et al., ICML 2021, arXiv 2102.05152) [k] | Monte Carlo tree search over connected subgraphs, scored by Shapley values. Explanations are *connected*, which suits analysts. |
| **CF-GNNExplainer** (Lucic et al., AISTATS 2022, arXiv 2102.03322) [k] | The *minimal edge deletion that flips the prediction*. **This is exactly the counterfactual explanation we want.** |
| **GraphXAI** (Agarwal et al., Scientific Data 2023, arXiv 2208.09339) [k] | A benchmark and metrics for graph explanations (fidelity, sparsity, stability) with ground-truth explanations. |

**LLMs turning graph explanations into text** (2024–2025):
- Giorgi et al. ([AISTATS 2025](https://proceedings.mlr.press/v258/giorgi25a.html)) [v]: LLMs turn counterfactual graph explanations into natural language for non-experts.
- **GraphXAIN** ([arXiv 2411.02540](https://arxiv.org/pdf/2411.02540)) [v]: builds narratives on top of GNNExplainer-style subgraphs. Criticizes earlier text explanations for being descriptive rather than causal.
- **GraphNarrator** ([2410.15268](https://arxiv.org/html/2410.15268v2)) [v].
- **GSPELL / "From Nodes to Narratives"** ([2508.07117](https://arxiv.org/html/2508.07117v1)) [v]: reports a good fidelity–sparsity trade-off.
- **LLM-GCE** ([Findings EMNLP 2024](https://aclanthology.org/2024.findings-emnlp.415.pdf)) [v]: adds a feedback loop to reduce hallucination in generated counterfactuals.
- **Lesson:** the LLM should *narrate* a subgraph that was computed and verified separately. It should never *invent* the explanation.

### 2.2 Attribution: which evidence actually drove the answer?

- **ERASER** (DeYoung et al., ACL 2020, arXiv 1911.03429) [k] defines two metrics we should adopt directly:
  - **Sufficiency**: does the rationale alone produce the same decision?
  - **Comprehensiveness**: does removing the rationale change the decision?
- **ContextCite** ([Cohen-Wang et al. 2024, arXiv 2409.00729](https://arxiv.org/pdf/2409.00729)) [v]
  - Randomly ablates context sources, re-runs the model, and fits a sparse linear surrogate. The surrogate's weights are the attribution scores.
  - Costs about **32× one generation**.
  - Caveat: ablating a sentence can break references in other sentences, such as a dangling pronoun.
  - In our setting: ablate *tool results* or *graph facts* given to the LLM, and see which ones the verdict depends on.
- **AttriBoT** ([arXiv 2411.15102](https://arxiv.org/pdf/2411.15102)) [v-title]: cheaper approximations of leave-one-out attribution.
- **SelfCite** ([2502.09604](https://arxiv.org/pdf/2502.09604)) [v-title]: trains the model itself to cite context.
- **CiteGuard** ([ACL 2026, arXiv 2510.17853](https://arxiv.org/html/2510.17853v3)) [v]: an agent framework that checks citations by retrieval.
- **Gap:** we found no published work that applies ContextCite-style ablation to an agent's *tool-call results*. That is an open niche Lattice could fill and present.

### 2.3 Why chain-of-thought is NOT the explanation

Research shows that a model's stated reasoning often leaves out what actually drove the decision:

- **Turpin et al. 2023**, "Language Models Don't Always Say What They Think" (arXiv 2305.04388) [k]: CoT rationalizes answers that were driven by biased features of the prompt.
- **Lanham et al. 2023**, "Measuring Faithfulness in CoT" (arXiv 2307.13702) [k].
- **Chen et al. 2025**, "Reasoning Models Don't Always Say What They Think" ([arXiv 2505.05410](https://arxiv.org/abs/2505.05410v1)) [v]: models reveal that they used a hint in its CoT often **less than 20%** of the time. RL that increases hint use does *not* make models mention it more.
- **Korbak et al. 2025**, CoT monitorability position paper (arXiv 2507.11473) [k]; **"Monitoring Monitorability"** ([ICML 2026 oral](https://icml.cc/virtual/2026/poster/62992)) [v-abstract]: CoT monitoring is useful but fragile. Training against a monitor can teach models to hide their reasoning.
- Further measurement work: [2510.27378](https://arxiv.org/pdf/2510.27378) and [2511.08525](https://arxiv.org/html/2511.08525v3) [v].

**Design consequence:** log the reasoning trace for debugging, but **base the explanation on the evidence**: graph facts with IDs, tool calls that can be replayed, and ablation tests. That is the auditable part.

---

## 3. Multi-hop reasoning over graphs with LLMs

### 3.1 Agentic graph traversal

- **Think-on-Graph (ToG)** (Sun et al., ICLR 2024, arXiv 2307.07697) [k]: the LLM runs a beam search over the KG. At each hop it picks which relations and entities to explore, then decides whether it has enough to answer.
- **ToG-2** (arXiv 2407.10805) [k]: alternates between graph retrieval and text retrieval.
- **ToG-3** ([arXiv 2509.21710](https://arxiv.org/pdf/2509.21710)) [v]: multi-agent retrieval on heterogeneous graphs, with "dual-evolving" context.
- **Reasoning on Graphs (RoG)** (Luo et al., ICLR 2024, arXiv 2310.01061) [k]: **plan relation paths first** (for example `owns → transfers_to → owned_by`), then retrieve instances that match the plan. The paths themselves are faithful, readable explanations.
- **Graph Chain-of-Thought (Graph-CoT)** (Jin et al., ACL 2024, arXiv 2404.07103) [k]: an iterative reason → interact → execute loop with explicit graph functions (`RetrieveNode`, `NodeFeature`, `NeighbourCheck`, `NodeDegree`). **This is close to the tool surface we want.**
- **Plan-on-Graph / Debate-on-Graph** [s]: add step-wise verification or debating roles to reduce false reasoning paths.
- **2025–2026 multi-hop KGQA**, all [s]:
  - PathMind ([2511.14256](https://arxiv.org/pdf/2511.14256)): retrieve → prioritize → reason.
  - S-Path-RAG ([2603.23512](https://arxiv.org/pdf/2603.23512)): semantic-aware shortest-path retrieval.
  - KG-Reasoner ([2604.12487](https://arxiv.org/pdf/2604.12487)): RL-trained end-to-end multi-hop reasoning.
  - Ontology-guided evidence path inference ([2606.28076](https://arxiv.org/pdf/2606.28076)).
  - Topology-aware reasoning on incomplete KGs ([2604.12503](https://arxiv.org/pdf/2604.12503)).

### 3.2 GraphRAG family (graph as retrieval index)

- **Microsoft GraphRAG** (Edge et al. 2024, arXiv 2404.16130) [k]: extracts entities and relations with an LLM, then uses **community detection (Leiden)** and hierarchical community summaries for "global" questions.
- **LightRAG** (arXiv 2410.05779) [k]: two-level retrieval, low-level facts plus high-level themes.
- **HippoRAG / HippoRAG 2** (arXiv 2405.14831 / 2502.14802) [k]: **Personalized PageRank** from query entities finds multi-hop evidence in a single retrieval step. This is a strong argument that a *graph algorithm* can replace many LLM hops.
- **G-Retriever** (arXiv 2402.07630) [k]: a Prize-Collecting Steiner Tree finds a compact connected subgraph for the question. That subgraph is an explanation by construction.
- **GNN-RAG** (arXiv 2405.20139) [k]: a GNN retrieves candidate answers, and the shortest paths to them become the LLM's context.
- **Surveys:** "Graphs Meet AI Agents" ([arXiv 2506.18019](https://arxiv.org/pdf/2506.18019)) [v]; Graph-RAG survey (Zhu et al., arXiv 2504.10499) [s]; LLM-KG4QA list ([EMNLP 2025 repo](https://github.com/machuangtao/llm-kg4qa)) [v].

### 3.3 Text-to-Cypher is still unreliable, so don't make it the main interface

- **CypherBench** ([Feng et al. 2025, arXiv 2412.18702](https://alphaxiv.org/overview/2412.18702v2)) [v]: 11 property graphs, 7.8M entities, more than 10k questions. **GPT-4o reaches about 60% execution accuracy. Models under 10B parameters stay below 20%.**
- **Neo4j/Microsoft Text2Cypher dataset** (EMNLP 2025 Industry): 27.5k NL→Cypher pairs, with documented hallucination patterns [v].
- **CypherSmith** ([ACL 2026](https://preview.aclanthology.org/ingest-acl/2026.acl-long.1601/)) [v-abstract]: a synthetic tuning set 12× larger than earlier ones.
- **PIPE-Cypher** (June 2026) [s]: zero-shot transfer to new schemas is weak; few-shot examples specific to the schema help.
- **Multi-Agent GraphRAG Text-to-Cypher** ([arXiv 2511.08274](https://arxiv.org/html/2511.08274v1)) [v]: a generate → validate → repair agent loop.

**Design consequence:** expose **typed, parameterized graph tools** as the main interface. Keep raw Cypher as a guarded escape hatch: read-only, schema-aware, checked with `EXPLAIN` before running, retried on error, and limited in rows and time.

---

## 4. Graph algorithms as agent tools

### 4.1 Prior work

- **Graph-ToolFormer** ([arXiv 2304.11116](https://arxiv.org/pdf/2304.11116)) [v]: teaches LLMs to call graph-reasoning APIs, from graph properties to real-world tasks.
- **GraphTool-Instruction / GTools / GraphForge** ([arXiv 2412.12152](https://arxiv.org/pdf/2412.12152)) [v]: splits the task into graph extraction → *tool name identification* → *tool parameter extraction*. **This is the right way to break down tool selection.**
- **GraphTeam** ([arXiv 2410.18032](https://arxiv.org/html/2410.18032v4)) [v]: five agents in three modules. A coding agent runs established algorithms in code and a reasoning agent is the fallback. Reports +25.85% accuracy over the best baseline.
- **GTA: Graph Theory Agent and Benchmark** ([arXiv 2609.12265](https://arxiv.org/pdf/2609.12265)) [s].
- **Lesson** (Graph-ToolFormer, GraphTeam, and the NLGraph line of work): LLMs are bad at *computing* graph algorithms in text, but good at *choosing and composing* them when they are given as tools.

### 4.2 Infrastructure that exists today

- **Official Neo4j MCP server** ([docs](https://neo4j.com/docs/mcp/current/), [github.com/neo4j/mcp](https://github.com/neo4j/mcp)) [v]: schema inspection plus read/write Cypher. **GDS tools turn on automatically when the Graph Data Science plugin is present.** Requires APOC.
- **mcp-neo4j-cypher** (Neo4j Labs): `get_neo4j_schema`, `read_neo4j_cypher`, `write_neo4j_cypher` [v]. Tool names have changed between versions, so pin a version.
- **Neo4j GDS agent server** (`gds-agent`) [s]: centrality, community detection, pathfinding, similarity, and embeddings as tools.

### 4.3 Algorithm → investigative question map (what the tools are *for*)

| Question an investigator asks | Algorithm (Neo4j GDS / NetworkX) | Fraud | Security | Code |
|---|---|---|---|---|
| "How is A connected to B?" | Shortest path, K-shortest (Yen), all simple paths with depth limit | Money trail between accounts | Attack path from internet to crown jewels (BloodHound style) | Call path from an API endpoint to a dangerous sink |
| "Who matters most here?" | PageRank, Personalized PageRank, betweenness | Mule hubs, central brokers | Choke points: one fix cuts many paths | Hot functions, high blast-radius modules |
| "What group is this part of?" | WCC, Louvain/Leiden, label propagation | Fraud rings, synthetic-identity clusters | Lateral-movement zones | Module boundaries, tangled dependencies |
| "What looks like this known-bad thing?" | Node similarity (Jaccard), FastRP/node2vec + kNN | Similar to confirmed fraud cases | Similar to past incidents | Similar to past vulnerable code |
| "Is there a loop / pattern?" | Cycle detection, motif/pattern match (Cypher) | Round-tripping, layering, smurfing fan-in/fan-out | Privilege escalation loops | Circular imports |
| "What changed / what's new?" | Temporal filtering, degree delta | Sudden new counterparties | New exposure after a deploy | Changed files and their dependents |
| "What breaks if we act?" | Reachability / impact (BFS from node) | Customers affected by freezing an account | Services affected by revoking a credential | Callers affected by a change |

Make the **last row a required tool call before any action**: compute the blast radius first, then act.

---

## 5. Tool selection through MCP

### 5.1 The protocol

- **Model Context Protocol**: open spec from Anthropic, November 2024; later revisions in 2025 [k]. It standardizes **tools** (model-invoked functions), **resources** (readable context) and **prompts** (templates) over JSON-RPC.
- The spec says there **SHOULD always be a human in the loop with the ability to deny tool invocations** [v].
- Reading:
  - Anthropic, ["Writing effective tools for agents"](https://www.anthropic.com/engineering/writing-tools-for-agents) (September 2025) [v]: build tool prototypes, evaluate them with agents, namespace tools, return meaningful and token-efficient output.
  - Anthropic, ["Code execution with MCP"](https://www.anthropic.com/engineering/code-execution-with-mcp) (November 2025) [v]: as tool counts grow, let the agent write code that calls tools, so large intermediate results stay out of the model's context.
  - Anthropic, ["Effective context engineering for AI agents"](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) (September 2025) [v].

### 5.2 What the research says about choosing among many tools

- **RAG-MCP** ([arXiv 2505.03275](https://arxiv.org/html/2505.03275v1)) [v]: retrieves the relevant tool descriptions instead of loading all of them. **Tool-selection accuracy goes from 13.6% to 43.1%, with over 50% fewer prompt tokens.** It **degrades past about 100 candidate tools.**
- **MCP-Bench** ([arXiv 2508.20453](https://arxiv.org/pdf/2508.20453)) [v]: 28 live servers, 250 tools, fuzzy instructions with no tool names given. Scores tool selection and planning efficiency.
- **MCP-Universe** ([arXiv 2508.14704](https://arxiv.org/html/2508.14704v1)) [v]: 11 real servers, 231 tasks. The best model reaches only **43.7%** success. Agents using real MCP servers are still far from reliable.
- **MCP-SafetyBench** ([2512.15163](https://arxiv.org/html/2512.15163)) [s]; **MCPToolBench++** ([2508.07575](https://arxiv.org/pdf/2508.07575)) [s]; **MCP-Flow** ([2510.24284](https://arxiv.org/pdf/2510.24284)) [s].
- **Tool search in practice**: the Claude Agent SDK and Claude Code load tools lazily through search once definitions take a significant share of context. With fewer than about 10 tools, loading them all upfront is fine ([docs](https://code.claude.com/docs/en/agent-sdk/tool-search)) [v].

**Design consequences:**
1. Keep the tool surface **small: about 10–15 tools, namespaced** (`graph.*`, `algo.*`, `case.*`, `action.*`). Tool search is then unnecessary. If we add many tools later, use retrieval-based tool search.
2. Make tools **high-level and intent-shaped**: `find_paths(src, dst, max_hops, rel_types)` rather than raw Cypher. Give each tool a description that says *when* to use it, not just what it does.
3. Every tool result returns **stable node and edge IDs**, so every claim the agent makes can cite them. This is the foundation of the evidence ledger in §7.
4. **Measure tool selection.** Log the chosen tool vs. the expected tool on our eval set, in the style of MCP-Bench.

---

## 6. Orchestration: one agent or many?

- **Anthropic, "Building effective agents"** (December 2024) [k]: start with the simplest pattern that works. The patterns include prompt chaining, routing, parallelization, orchestrator-workers and evaluator-optimizer, and they are often better than open-ended autonomy.
- **Anthropic's multi-agent research system** (June 2025) [v, via summaries]:
  - A lead agent spawns parallel subagents, then a citation agent attributes claims.
  - **+90.2%** over single-agent Opus 4 on internal research evals.
  - But about **15× the tokens** of chat. Token usage alone explained about 80% of the variance on BrowseComp.
- **Cognition, "Don't Build Multi-Agents"** (June 2025) [k]: sub-agents lose context and make conflicting choices. Share full traces, prefer a single thread for tightly coupled work.
- **MAST: "Why Do Multi-Agent LLM Systems Fail?"** ([Cemri et al., arXiv 2503.13657](https://arxiv.org/html/2503.13657v3); [project page](https://sky.cs.berkeley.edu/project/mast/)) [v]
  - 14 failure modes in three groups: **system design / specification issues**, **inter-agent misalignment**, **task verification**.
  - 1600+ annotated traces, κ=0.88.
  - Failures come mostly from *system design*, not from model limits.
- **2026 practice** [s]: the field is converging on **one orchestrator that owns the context and spawns short-lived, isolated sub-agents that return compressed summaries.** Peer "group chat" designs are falling out of use.

**Design consequences for Lattice:**
- **One orchestrator** owns the case file: the evidence ledger, open hypotheses and budget.
- **Parallel sub-investigators** only for *independent* hypotheses, for example "ring?", "account takeover?", "mule?". Each gets a narrow brief and returns `{verdict, evidence_ids, confidence}`, never prose alone.
- **A separate verifier** (evaluator-optimizer pattern) re-runs the cited queries and the ablation test before any action. This answers MAST's "task verification" failure group.
- A **typed handoff schema** between agents, to avoid MAST's "inter-agent misalignment" failures.

---

## 7. Acting safely on what the graph shows

### 7.1 Threats specific to graph agents

- **Indirect prompt injection through the data.** In fraud and security graphs, **node properties are written by attackers**: transaction memos, usernames, commit messages, code comments. Anything returned by a tool is untrusted. OWASP's MCP Top 10 lists this as MCP06, "Prompt Injection via Contextual Payloads" ([OWASP](https://owasp.org/www-project-mcp-top-10/2025/MCP06-2025–Prompt-InjectionviaContextual-Payloads)) [v].
- **Tool poisoning**: hidden instructions inside tool descriptions [v]. Pin and review tool definitions.
- Defenses that work act on the **tool call**, not the text:
  - A policy validator decides whether each call is allowed.
  - Capabilities are scoped to the job.
  - Higher-impact actions need human confirmation.
  - Auto-approve is off for writes [v].

### 7.2 Action tiers (proposed)

| Tier | Examples | Gate |
|---|---|---|
| 0 Read | queries, algorithms | none (rate/row limits) |
| 1 Annotate | tag node, open case, add note | auto, logged, reversible |
| 2 Recommend | "freeze account", "revoke token", "open PR" | proposal + explanation; human approves |
| 3 Execute | the actual freeze/revoke/merge | human approval **and** verifier pass **and** blast-radius check |

### 7.3 Observability

- **OpenTelemetry GenAI semantic conventions** [v, maturity disputed]: spans for `invoke_agent`, `execute_tool` and model calls, plus MCP client/server conventions in development.
- Emit one trace per investigation. The trace and the evidence ledger together are the audit record.

---

## 8. Domain anchors (pick one for the demo; the architecture is the same)

### Fraud / AML
- **Elliptic** (Weber et al. 2019, arXiv 1908.02591) [k]: Bitcoin transaction graph with node-level labels.
- **Elliptic2** ([Bellei et al. 2024, arXiv 2404.19109](https://arxiv.org/pdf/2404.19109)) [v]: **122K labeled subgraphs** inside a 49M-node / 196M-edge background graph. Argues AML is a *subgraph* problem.
  - The predicted subgraphs showed known laundering patterns such as **peeling chains** and **nested services**.
  - [Code](https://github.com/mitibmxgraph/elliptic2); follow-up **RevTrack** traces initial senders and final receivers.
  - **No explainability work on Elliptic2 was found.** That is an open opportunity.
- **"Toward Auditable Fraud Detection"** ([arXiv 2607.19266](https://arxiv.org/abs/2607.19266)) [v]
  - A classifier plus TreeSHAP sends **only borderline cases** to a bounded LLM investigation agent. The agent can pull graph context, SHAP values and nearest labeled cases.
  - The authors found and removed a **simulator shortcut in PaySim** that had inflated baselines. Check any synthetic dataset for the same problem.
  - **This is the closest published architecture to Lattice.**
- Also: GARG-AML for smurfing ([2506.04292](https://arxiv.org/pdf/2506.04292)) [s]; money-mule detection → attribution → narration pipeline ([2607.17586](https://arxiv.org/pdf/2607.17586)) [s]; neuro-symbolic GAT + constrained LLM explanations ([Frontiers AI 2026](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2026.1904459/full)) [s].

### Security findings triage
- **Code property graphs** (Yamaguchi et al., IEEE S&P 2014) [k]: AST + CFG + PDG merged into one queryable graph.
- **"Bridging CPGs and Language Models"** / codebadger ([ACM 2026](https://dl.acm.org/doi/10.1145/3786165.3788441)) [s]: interprocedural flows can't be seen by embedding retrieval, so the agent queries the CPG.
- **"Graph Is the Verifier"** ([arXiv 2607.26656](https://arxiv.org/pdf/2607.26656)) [s]: the CPG is both the agent's tool surface *and* the reward verifier.
- **Logic attack graphs for agentic pentesting** ([arXiv 2609.15523](https://arxiv.org/abs/2609.15523)) [v]: turns Trivy, Semgrep and Nmap findings into MulVAL predicates, with LLM-assisted Datalog rules to build attack paths. 53.7% ground-truth coverage, but a **83.9% noise-path rate**. Triage that ranks and prunes paths is the open problem.
- **ATAG** ([2506.02859](https://arxiv.org/pdf/2506.02859)) [s]; **Agent-BOM graph audits** ([2605.06812](https://arxiv.org/abs/2605.06812)) [s]; BloodHound-plus-LLM tools, including privacy masking ([HoundMasker](https://www.alteredsecurity.com/houndmasker-privacy-preserving-attack-path-analysis-bloodhound-llm)) [s].
- **IRIS** (Li et al., LLM + CodeQL, arXiv 2405.17238) [k]: the LLM infers taint specs and static analysis does the path finding.

### Codebase navigation
- **CodexGraph** ([NAACL 2025, arXiv 2408.03910](https://arxiv.org/pdf/2408.03910)) [v]: static analysis puts the repo into a graph DB, and the agent writes graph queries.
- **LocAgent** ([ACL 2025, arXiv 2503.09089](https://arxiv.org/pdf/2503.09089)) [v]
  - Heterogeneous code graph (files, classes, functions, imports, calls, inheritance) with purpose-built graph tools.
  - **92.7% file-level localization** with a fine-tuned Qwen-2.5-Coder-32B, at about 86% lower cost.
  - Introduces **Loc-Bench**.
- **RepoGraph** (Ouyang et al., ICLR 2025, arXiv 2410.14684) [k]: a repo-level line graph plugged into SWE-bench agents.
- **CodexGraph vs. LocAgent** is the same question as §3.3: free-form queries vs. purpose-built tools. **LocAgent's purpose-built tools did better.**

---

## 9. Proposed Lattice architecture (synthesis)

```
                ┌─────────────────────────────────────────────────────────┐
  Alert / task ─▶  ORCHESTRATOR (Claude)                                    │
                │   plan → hypotheses → investigate → verify → propose/act │
                │   owns: Case File = {hypotheses, Evidence Ledger, budget}│
                └───────┬───────────────────┬───────────────────┬─────────┘
                        │ parallel, isolated │                   │
                 ┌──────▼─────┐      ┌──────▼─────┐       ┌─────▼──────┐
                 │ Sub-invest.│      │ Sub-invest.│       │  VERIFIER  │ re-runs cited
                 │ hypothesis │      │ hypothesis │       │  + Evidence│ queries, runs
                 │     A      │      │     B      │       │  Circuit   │ ablation, checks
                 └──────┬─────┘      └──────┬─────┘       └─────┬──────┘ blast radius
                        └──────────┬────────┘                   │
                          MCP (small, namespaced tool surface)   │
   graph.schema  graph.get_node  graph.neighbors  graph.find_paths  graph.match_pattern
   algo.pagerank algo.communities algo.similar  algo.impact   graph.cypher_readonly (guarded)
   case.cite  case.add_hypothesis      action.propose  action.execute (tier-gated, HITL)
                                   │
                         Neo4j + GDS  (+ OTel traces, Evidence Ledger store)
```

### 9.1 The Evidence Ledger (makes the agent explainable by construction)
- Every tool result is stored with a `result_id`, the query and parameters, a timestamp, and the **node and edge IDs** it returned.
- The agent's final claims must cite `result_id`s or edge IDs. The verifier rejects any claim citing an ID that no tool returned. This catches hallucinated edges.
- **Path validity check:** every cited path must exist in the graph when it is re-queried.

### 9.2 The Evidence Circuit: ACDC for decisions

| ACDC (inside a network) | Lattice (evidence graph) |
|---|---|
| Computational graph of the model | Evidence subgraph G_e collected during the investigation |
| Clean input vs. corrupted input | Actual graph vs. graph with edges/nodes ablated (removed or replaced with a typical "benign" baseline) |
| Metric: KL / logit diff | Δ decision score (risk score, or LLM verdict probability) |
| Threshold τ, prune if Δ < τ | Same |
| EAP: gradient approximation to score all edges | Cheap per-edge attribution (additive scorer contributions, or Shapley sampling) to rank candidates |
| Faithfulness (MIB CPR / CMD) | **Sufficiency** (circuit alone ≥ threshold) and **comprehensiveness** (G_e minus circuit < threshold), as in ERASER |
| Minimal circuit | Minimal evidence circuit + **counterfactual**: the smallest edge set whose removal flips the verdict (CF-GNNExplainer) |

**Making it affordable:**
- Split the decision into (a) a **transparent scorer** over graph features and GDS outputs, which is fast to ablate thousands of times, and (b) the **LLM**, which plans, picks tools, and narrates.
- Run the cheap scorer for ACDC-style pruning on every case.
- For the LLM's own verdict, run ContextCite-style ablation of tool results on a small budget, such as 16–32 samples, and only for tier-2 and tier-3 actions.

### 9.3 Explanation output (what the analyst sees)
1. **Verdict + confidence**
2. **Evidence circuit**: a rendered subgraph of a few nodes and edges, each linked to its ledger entry.
3. **Faithfulness badge**: sufficiency ✓ / comprehensiveness ✓ / circuit size k / paths re-verified ✓.
4. **Counterfactual**: "If X were not true, the verdict would be Y."
5. **Narrative**: written by the LLM *from* items 2–4, never instead of them.
6. **Proposed action + blast radius + tier**: approve or reject.

### 9.4 Evaluation plan

| Axis | Metric | Source of idea |
|---|---|---|
| Decision quality | precision / recall / F1 vs. labels (Elliptic2, PaySim (shortcut removed), Loc-Bench, seeded CTF findings) | domain benchmarks |
| Multi-hop retrieval | answer accuracy, hops used, paths valid | ToG / RoG / WebQSP / CWQ |
| Explanation faithfulness | sufficiency, comprehensiveness, circuit size, stability across perturbations | ERASER, MIB, GraphXAI |
| Grounding | % claims with valid citations; hallucinated-edge rate | ledger verifier |
| Tool use | tool-selection accuracy, Cypher execution accuracy, calls per case | MCP-Bench, CypherBench |
| Safety | injection test cases (poisoned node properties) → no unauthorized action | OWASP MCP Top 10 |
| Cost | tokens, latency per case; multi-agent vs. single-agent ablation | Anthropic multi-agent results |

---

## 10. Stretch: real mechanistic interpretability in the demo

If there is time, add an **"inside the model" panel** using an *open* model:
- Run tool selection on a small open model such as Gemma-2-2B. circuit-tracer has transcoders for it.
- Show the **attribution graph** for "why did it pick `find_paths` over `pagerank`?"
- Optionally train a **linear probe** for "tool-need" on residual activations. 2026 preprints suggest tool-calling intent is linearly readable (§1.5). After §1.4, a probe is a stronger baseline than an SAE.

This is a showcase, not the core. The core explanation is the evidence circuit (§9.2), which works with any model behind an API.

---

## 11. Priority reading list (if you only read 12)

1. Conmy et al., **ACDC** (2304.14997): the method we adapt.
2. Hanna et al., **EAP-IG / "Have Faith in Faithfulness"** (2403.17806): faithfulness as the metric.
3. Mueller et al., **MIB** ([2504.13151](https://arxiv.org/abs/2504.13151)): how to benchmark circuits.
4. Lucic et al., **CF-GNNExplainer** (2102.03322): counterfactual subgraph explanations.
5. DeYoung et al., **ERASER** (1911.03429): sufficiency and comprehensiveness.
6. Cohen-Wang et al., **ContextCite** ([2409.00729](https://arxiv.org/pdf/2409.00729)): ablation-based attribution for LLM outputs.
7. Chen et al., **Reasoning models don't always say what they think** ([2505.05410](https://arxiv.org/abs/2505.05410v1)): why CoT isn't the explanation.
8. Luo et al., **Reasoning on Graphs** (2310.01061) and Jin et al., **Graph-CoT** (2404.07103): faithful multi-hop over graphs.
9. Gutiérrez et al., **HippoRAG** (2405.14831): graph algorithms replacing LLM hops.
10. Deng et al., **LocAgent** ([2503.09089](https://arxiv.org/pdf/2503.09089)): purpose-built graph tools beat free-form queries.
11. Cemri et al., **MAST** ([2503.13657](https://arxiv.org/html/2503.13657v3)) plus Anthropic's *Building effective agents*, *Writing effective tools*, and *multi-agent research system* posts.
12. **Toward Auditable Fraud Detection** ([2607.19266](https://arxiv.org/abs/2607.19266)): the closest existing system to ours.

---

## 12. Known gaps in this review

- None of the 2026 preprints marked [s] were read in full. Their reported numbers are unverified.
- No published work combines (a) an LLM agent, (b) ablation-tested subgraph explanations and (c) gated actions on a graph. That is Lattice's novelty claim, but run a focused literature search before stating it in a pitch.
- The maturity of the OpenTelemetry GenAI conventions is reported inconsistently. Check the semantic-conventions repo.
- Vendor tool-search accuracy numbers (Stacklok, Speakeasy) are self-reported and left out of the recommendations above.
