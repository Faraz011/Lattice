"""A small ReLU network, trained with Adam, and exported with labelled neurons.

The network is kept small enough to draw every neuron. Two things keep its neurons readable:
an L1 penalty on hidden activations (few neurons fire for any one input), and labels computed
after training from what each neuron fires on (`label_neurons`).
"""

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Feature:
    id: str
    label: str  # shown on the trace device, e.g. "light is red"
    description: str = ""
    low_label: str = ""  # what a low value means, e.g. "near the light" for a distance


@dataclass
class MLP:
    sizes: list[int]
    weights: list[np.ndarray] = field(default_factory=list)  # each (out, in)
    biases: list[np.ndarray] = field(default_factory=list)

    @classmethod
    def init(cls, sizes: list[int], seed: int) -> "MLP":
        rng = np.random.default_rng(seed)
        net = cls(sizes)
        for n_in, n_out in zip(sizes, sizes[1:], strict=False):
            net.weights.append(rng.normal(0, np.sqrt(2 / n_in), (n_out, n_in)))
            net.biases.append(np.zeros(n_out))
        return net

    def forward(self, x: np.ndarray) -> list[np.ndarray]:
        """Activations of every layer, the input first and the logits last."""
        acts = [x]
        for i, (w, b) in enumerate(zip(self.weights, self.biases, strict=True)):
            z = acts[-1] @ w.T + b
            acts.append(z if i == len(self.weights) - 1 else np.maximum(z, 0))
        return acts

    def predict(self, x: np.ndarray) -> np.ndarray:
        return self.forward(x)[-1].argmax(axis=1)


def _softmax(z: np.ndarray) -> np.ndarray:
    e = np.exp(z - z.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


def train(net: MLP, x: np.ndarray, y: np.ndarray, *, epochs: int = 60, batch: int = 128,
          lr: float = 3e-3, l1: float = 1e-3, decay: float = 1e-4, seed: int = 0,
          class_weight: np.ndarray | None = None, output_bias: bool = True,
          dropout: float = 0.0) -> MLP:
    """Cross-entropy with an L1 penalty on hidden activations, Adam, mini-batches.

    With `output_bias=False` the logits have no bias: when no hidden neuron fires, no decision
    is favoured, so every decision has to come from neurons that fire for a reason. That keeps
    a default answer (say, braking whenever nothing says go) out of the network, where a trace
    could only explain it as an absence.

    `dropout` switches each hidden neuron off at random during training. A network that cannot
    count on any one neuron grows redundant routes to the same decision: the backup routes the
    tracer looks for.
    """
    rng = np.random.default_rng(seed)
    params = [*net.weights, *net.biases]
    m = [np.zeros_like(p) for p in params]
    v = [np.zeros_like(p) for p in params]
    weight = class_weight if class_weight is not None else np.ones(net.sizes[-1])
    step = 0
    for _ in range(epochs):
        order = rng.permutation(len(x))
        for start in range(0, len(x), batch):
            idx = order[start:start + batch]
            acts = _forward_dropout(net, x[idx], dropout, rng) if dropout else net.forward(x[idx])
            probs = _softmax(acts[-1])
            onehot = np.eye(net.sizes[-1])[y[idx]]
            w = weight[y[idx]][:, None]
            grad = (probs - onehot) * w / len(idx)
            grads_w, grads_b = [], []
            for layer in range(len(net.weights) - 1, -1, -1):
                grads_w.insert(0, grad.T @ acts[layer] + decay * net.weights[layer])
                grads_b.insert(0, grad.sum(axis=0))
                if layer == 0:
                    break
                back = grad @ net.weights[layer]
                back += l1 * np.sign(acts[layer]) / len(idx)  # sparse hidden activity
                grad = back * (acts[layer] > 0)
            step += 1
            for i, g in enumerate([*grads_w, *grads_b]):
                m[i] = 0.9 * m[i] + 0.1 * g
                v[i] = 0.999 * v[i] + 0.001 * g * g
                params[i] -= lr * (m[i] / (1 - 0.9 ** step)) / (
                    np.sqrt(v[i] / (1 - 0.999 ** step)) + 1e-8)
            if not output_bias:
                net.biases[-1][:] = 0
    return net


def _forward_dropout(net: MLP, x: np.ndarray, p: float,
                     rng: np.random.Generator) -> list[np.ndarray]:
    """Forward pass with inverted dropout on the hidden layers (training only)."""
    acts = [x]
    for i, (w, b) in enumerate(zip(net.weights, net.biases, strict=True)):
        z = acts[-1] @ w.T + b
        if i == len(net.weights) - 1:
            acts.append(z)
        else:
            keep = (rng.random(z.shape) >= p) / (1 - p)
            acts.append(np.maximum(z, 0) * keep)
    return acts


def label_neurons(net: MLP, x: np.ndarray, inputs: list[Feature], outputs: list[Feature],
                  top: int = 2, concepts: dict[str, np.ndarray] | None = None) -> list[dict]:
    """Name each hidden neuron by the inputs it fires with and the decision it pushes toward.

    With `concepts` (named true/false facts about each row, such as "pedestrian in the path"),
    the label is the concept the neuron's activation tracks best, and `concepts` lists the top
    ones with their correlation. Otherwise the label comes from the inputs.

    `fires_on` is the inputs most correlated with the neuron's activation over the data;
    `pushes` is the output its activation raises most, through the rest of the network with
    the other neurons held at their average. Neither is used by the tracer: they are only the
    words next to a neuron.
    """
    acts = net.forward(x)
    out = []
    for layer in range(1, len(net.sizes) - 1):
        a = acts[layer]
        for j in range(a.shape[1]):
            col = a[:, j]
            active = float((col > 0).mean())
            entry = {"id": f"h{layer}_{j}", "layer": layer, "index": j, "active": active}
            if active < 0.005 or col.std() < 1e-6:
                out.append({**entry, "dead": True, "fires_on": [], "pushes": None,
                            "label": "never fires"})
                continue
            corr = []
            for k, feat in enumerate(inputs):
                xs = x[:, k]
                c = 0.0 if xs.std() < 1e-9 else float(np.corrcoef(xs, col)[0, 1])
                corr.append((c, feat))
            corr.sort(key=lambda t: -abs(t[0]))
            fires = [{"feature": f.id, "corr": round(c, 2)} for c, f in corr[:top]
                     if abs(c) > 0.15]
            push = _push(net, acts, layer, j)
            words = [f.label if c > 0 else (f.low_label or f"not {f.label}")
                     for c, f in corr[:top] if abs(c) > 0.15]
            label = ", ".join(words) or "mixed inputs"
            ranked = []
            if concepts:
                for name, truth in concepts.items():
                    t = truth.astype(float)
                    c = 0.0 if t.std() < 1e-9 else float(np.corrcoef(t, col)[0, 1])
                    ranked.append((c, name))
                ranked.sort(key=lambda r: -r[0])
                best_c, best = ranked[0]
                second_c, second = ranked[1] if len(ranked) > 1 else (0.0, "")
                if best_c > 0.2:
                    # A neuron that tracks two concepts nearly as well is named for both: it is
                    # polysemantic, and saying so is more honest than picking one.
                    label = f"{best} or {second}" if second_c > max(0.3, best_c / 2) else best
                else:
                    worst_c, worst = min(ranked)
                    label = f"on unless {worst}" if worst_c < -0.2 else label
            out.append({**entry, "dead": False, "fires_on": fires,
                        "concepts": [{"concept": n, "corr": round(c, 2)} for c, n in ranked[:3]],
                        "pushes": outputs[int(np.argmax(push))].id, "label": label})
    return out


def neuron_profiles(net: MLP, x: np.ndarray, describe, top: int = 6, bins: int = 16) -> dict:
    """What each hidden neuron fires for, the way interpretability tools show a feature: the
    training situations that excite it most, in words, and a histogram of its activations.

    `describe` turns one input row into a short description. Situations with the same
    description are shown once, at their strongest.
    """
    acts = net.forward(x)
    out = {}
    for layer in range(1, len(net.sizes) - 1):
        a = acts[layer]
        for j in range(a.shape[1]):
            col = a[:, j]
            on = col[col > 0]
            examples, seen = [], set()
            for i in np.argsort(-col):
                if col[i] <= 0 or len(examples) >= top:
                    break
                text = describe(x[i])
                if text in seen:
                    continue
                seen.add(text)
                examples.append({"text": text, "act": round(float(col[i]), 3)})
            hi = float(on.max()) if on.size else 1.0
            counts, edges = np.histogram(on, bins=bins, range=(0.0, hi)) if on.size else (
                np.zeros(bins, dtype=int), np.linspace(0, 1, bins + 1))
            out[f"h{layer}_{j}"] = {
                "examples": examples,
                "hist": {"max": round(hi, 3), "counts": counts.tolist()},
                "active": round(float((col > 0).mean()), 4),
            }
    return out


def _push(net: MLP, acts: list[np.ndarray], layer: int, j: int) -> np.ndarray:
    """How much one unit of neuron j raises each logit, from the layer's average state."""
    base = acts[layer].mean(axis=0)
    bumped = base.copy()
    bumped[j] += 1.0

    def run(h: np.ndarray) -> np.ndarray:
        for i in range(layer, len(net.weights)):
            h = h @ net.weights[i].T + net.biases[i]
            if i < len(net.weights) - 1:
                h = np.maximum(h, 0)
        return h

    return run(bumped) - run(base)


def export(net: MLP, *, name: str, title: str, inputs: list[Feature], outputs: list[Feature],
           neurons: list[dict], metrics: dict, notes: str, data: np.ndarray) -> dict:
    """The JSON the browser loads: weights by layer, plus the words for each neuron.

    `means` holds each layer's average activation over the training data (inputs first). The
    tracer switches an input off by putting its average in its place (zero is not a neutral
    value for a distance), and a hidden neuron off by setting it to zero.
    """
    acts = net.forward(data)
    return {
        "means": [np.round(a.mean(axis=0), 5).tolist() for a in acts[:-1]],
        "name": name,
        "title": title,
        "notes": notes,
        "sizes": net.sizes,
        "inputs": [vars(f) for f in inputs],
        "outputs": [vars(f) for f in outputs],
        "layers": [{"W": np.round(w, 5).tolist(), "b": np.round(b, 5).tolist()}
                   for w, b in zip(net.weights, net.biases, strict=True)],
        "neurons": neurons,
        "metrics": metrics,
    }


def accuracy(net: MLP, x: np.ndarray, y: np.ndarray) -> float:
    return float((net.predict(x) == y).mean())
