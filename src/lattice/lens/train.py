"""Train both demo networks and write what the browser loads.

    uv run --group lens python -m lattice.lens.train

writes `lens/public/models/driving.json`, `lens/public/models/aml.json` and
`lens/public/episodes/aml.json`. Every run with the same seeds writes the same files.
"""

import argparse
import json
import math
import random
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

from lattice.datagen import decoys, typologies
from lattice.datagen.background import build_background
from lattice.datagen.builder import WINDOW_START, WorldBuilder, days
from lattice.datagen.manifest import CaseRecord
from lattice.lens import aml, driving
from lattice.lens.mlp import MLP, accuracy, export, label_neurons, neuron_profiles, train

OUT = Path("lens/public")
EPISODE_SEED = 4242


def _profiled(neurons: list[dict], profiles: dict) -> list[dict]:
    return [n | profiles.get(n["id"], {}) for n in neurons]


def train_driving() -> dict:
    x, y = driving.dataset(60_000, seed=1)
    xt, yt = driving.dataset(10_000, seed=2)
    net = train(MLP.init([len(driving.INPUTS), 16, 8, len(driving.OUTPUTS)], seed=0), x, y,
                epochs=160, output_bias=False, dropout=0.1)
    return export(
        net, name="driving", title="Self-driving car", inputs=driving.INPUTS,
        outputs=driving.OUTPUTS,
        neurons=_profiled(label_neurons(net, x[:20_000], driving.INPUTS, driving.OUTPUTS,
                                        concepts=driving.concepts(x[:20_000])),
                          neuron_profiles(net, x[:20_000], driving.describe)),
        metrics={"agreement_with_expert": round(accuracy(net, xt, yt), 4),
                 "test_situations": len(yt)},
        notes="Imitates a rule-based expert driver over 60,000 sampled situations.", data=x,
    ) | {"physics": driving.PHYSICS, "groups": driving.GROUPS}


def train_aml() -> dict:
    x, y = aml.dataset(list(range(100, 112)))
    xt, yt = aml.dataset(list(range(200, 204)))
    counts = np.bincount(y, minlength=len(aml.OUTPUTS))
    weight = len(y) / (len(counts) * np.maximum(counts, 1))
    net = train(MLP.init([len(aml.INPUTS), 10, 8, len(aml.OUTPUTS)], seed=0), x, y,
                epochs=300, class_weight=weight)
    pred = net.predict(xt)
    recall = {f.id: round(float((pred[yt == c] == c).mean()), 3)
              for c, f in enumerate(aml.OUTPUTS) if (yt == c).any()}
    return export(
        net, name="aml", title="AML account check", inputs=aml.INPUTS, outputs=aml.OUTPUTS,
        neurons=_profiled(label_neurons(net, x, aml.INPUTS, aml.OUTPUTS),
                          neuron_profiles(net, x, aml.describe)),
        metrics={"accuracy": round(accuracy(net, xt, yt), 4), "recall": recall,
                 "test_accounts": len(yt)},
        notes="Trained on 12 synthetic worlds with planted laundering; tested on 4 others.",
        data=x,
    ) | {
        # What the tracer compares a flagged account with: the average clear account.
        "reference": np.round(x[y == aml.CLASS["clear"]].mean(axis=0), 5).tolist(),
    }


def _case(p, category: str) -> CaseRecord:
    return CaseRecord(case_id=f"{category}-{p.kind}", category=category, kind=p.kind,
                      expected_verdict="suspicious" if category == "planted" else "benign",
                      seed_account_id=p.seed_account_id, alert_id="", account_ids=p.account_ids,
                      transfer_ids=p.transfer_ids, device_ids=p.device_ids, roles=p.roles,
                      routes=p.routes)


def episode() -> dict:
    """A small bank over two weeks: a two-route mule ring, a round trip, structuring, a decoy."""
    rng = random.Random(EPISODE_SEED)
    b = WorldBuilder(EPISODE_SEED)
    build_background(b, random.Random(EPISODE_SEED), persons=45, businesses=5)
    start = WINDOW_START + days(40)
    planted = [
        (typologies.parallel_mules, 1.0), (typologies.round_trip, 3.5),
        (typologies.fan_in_structuring, 6.0), (typologies.shared_device, 8.5),
    ]
    cases = [_case(fn(b, rng, start + days(at)), "planted") for fn, at in planted]
    cases.append(_case(decoys.family_cycle(b, rng, start + days(5)), "decoy"))
    ledger = aml.Ledger.from_batch(b.batch)

    end = start + days(13)
    txs = sorted((t for t in b.batch.transfers if t.ts and start <= t.ts <= end),
                 key=lambda t: t.ts)
    involved = {a for c in cases for a in c.account_ids}
    # Keep the cases whole and enough everyday traffic to hide them in, not all of it.
    background = [t for t in txs if t.src not in involved and t.dst not in involved]
    keep_bg = set(t.id for t in random.Random(1).sample(background, min(160, len(background))))
    txs = [t for t in txs if t.id in keep_bg or t.src in involved or t.dst in involved]
    accounts = {a for t in txs for a in (t.src, t.dst)}

    steps, last, seen = [], {}, set()
    for t in txs:
        seen |= {t.src, t.dst}
        changed = {}
        for a in seen:
            f = [round(v, 4) for v in aml.account_features(ledger, a, t.ts)]
            if last.get(a) != f:
                changed[a] = last[a] = f
        steps.append({"t": t.ts.isoformat(), "tx": {"id": t.id, "src": t.src, "dst": t.dst,
                      "amount": round(t.amount, 2), "channel": t.channel},
                      "features": changed})
    by_id = {a.id: a for a in b.batch.accounts}
    customers = {c.id: c for c in b.batch.customers}
    shared = {a: sorted(aml_shared & accounts)
              for a in accounts if (aml_shared := ledger.devices.get(a, set()) & accounts)}
    return {
        "title": "A small bank, two weeks",
        "start": start.isoformat(), "end": end.isoformat(),
        "accounts": [_place(a, by_id[a].kind, customers[by_id[a].customer_id].name,
                            by_id[a].country) for a in sorted(accounts)],
        "shared_devices": shared,
        "steps": steps,
        # The answer key, for the presenter only: the network never sees it.
        "cases": [{"kind": c.kind, "category": c.category, "accounts": c.account_ids,
                   "seed": c.seed_account_id} for c in cases],
    }


# Each country's banking city, and its currency. Accounts are scattered around their city.
CITIES = {
    "GB": ("London", -0.1276, 51.5072, "GBP"), "DE": ("Frankfurt", 8.6821, 50.1109, "EUR"),
    "FR": ("Paris", 2.3522, 48.8566, "EUR"), "NL": ("Amsterdam", 4.9041, 52.3676, "EUR"),
    "ES": ("Madrid", -3.7038, 40.4168, "EUR"), "IT": ("Milan", 9.19, 45.4642, "EUR"),
    "PL": ("Warsaw", 21.0122, 52.2297, "PLN"), "IE": ("Dublin", -6.2603, 53.3498, "EUR"),
    "PT": ("Lisbon", -9.1393, 38.7223, "EUR"), "SE": ("Stockholm", 18.0686, 59.3293, "SEK"),
}


def _place(account: str, kind: str, owner: str, country: str) -> dict:
    """An account's home: its country's city, a spot near it, a masked IBAN-style number."""
    city, lng, lat, currency = CITIES.get(country, CITIES["GB"])
    rng = random.Random(account)
    angle, radius = rng.uniform(0, 6.283), rng.uniform(0.004, 0.05)  # about 0.5 to 5 km
    return {"id": account, "kind": kind, "owner": owner, "country": country, "city": city,
            "currency": currency,
            "iban": f"{country}{rng.randint(10, 99)} •••• {account[-4:].upper()}",
            "lng": round(lng + radius * 1.6 * math.cos(angle), 5),
            "lat": round(lat + radius * math.sin(angle), 5)}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    print(f"wrote {path} ({path.stat().st_size // 1024} KB)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lattice.lens.train", description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--only", choices=["driving", "aml", "episode"], action="append",
                        help="build only these (repeatable); default: all three")
    args = parser.parse_args(argv)
    only = set(args.only or ["driving", "aml", "episode"])
    started = datetime.now()
    if "driving" in only:
        drive = train_driving()
        print("driving: agreement with the expert", drive["metrics"]["agreement_with_expert"])
        _write(args.out / "models" / "driving.json", drive)
    if "aml" in only:
        model = train_aml()
        print("aml: accuracy", model["metrics"]["accuracy"], "recall", model["metrics"]["recall"])
        _write(args.out / "models" / "aml.json", model)
    if "episode" in only:
        ep = episode()
        print("episode:", len(ep["accounts"]), "accounts,", len(ep["steps"]), "transfers")
        _write(args.out / "episodes" / "aml.json", ep)
    print("done in", (datetime.now() - started).seconds, "s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
