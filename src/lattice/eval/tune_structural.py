"""Tune the structural detectors' weights against labelled Elliptic2 subgraphs.

The tuning slice never shares a subgraph with the evaluation slice. It is drawn with its own
seed (`--seed`, default 7) from the subgraphs the evaluation slice (`--eval-seed`, default 2,
`--eval-subgraphs`, default 100, as `lattice.ingest.elliptic2` builds it) did not pick.

Each subgraph is scored offline on its own internal flows, the evidence a thorough
investigator would cite, so no stack or model is needed. Detector strengths do not depend on
the weights, so they are computed once and the grid search only recombines them. The best
weights maximise balanced accuracy (the mean of the flag rate on suspicious subgraphs and the
pass rate on licit ones); ties go to the weights nearest the current defaults.

    uv run python -m lattice.eval.tune_structural --dir path/to/elliptic2 --subgraphs 2000

The sample in tests/fixtures/elliptic2_sample has five subgraphs, all taken by the evaluation
slice. `--allow-overlap` tunes on them anyway, and the output says the result is not a
measurement.
"""

import argparse
import itertools
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

from lattice.graph.subgraph import EvidenceGraph
from lattice.ingest.elliptic2 import build_slice, choose_subgraphs, read_labels
from lattice.scoring.scorer import DEFAULT_THRESHOLD
from lattice.scoring.structural import STRUCTURAL_DETECTORS, STRUCTURAL_WEIGHTS

GRID = (0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.0)
TUNING_SEED = 7
EVAL_SEED = 2


@dataclass(frozen=True)
class Labelled:
    case_id: str
    suspicious: bool
    strengths: dict[str, float]


@dataclass(frozen=True)
class Fit:
    weights: dict[str, float]
    flagged_suspicious: int
    suspicious: int
    flagged_licit: int
    licit: int

    @property
    def recall(self) -> float:
        return self.flagged_suspicious / self.suspicious if self.suspicious else 0.0

    @property
    def false_positive_rate(self) -> float:
        return self.flagged_licit / self.licit if self.licit else 0.0

    @property
    def precision(self) -> float | None:
        flagged = self.flagged_suspicious + self.flagged_licit
        return self.flagged_suspicious / flagged if flagged else None

    @property
    def balanced_accuracy(self) -> float:
        return (self.recall + 1 - self.false_positive_rate) / 2


def measure(cases: list[Labelled], weights: dict[str, float],
            threshold: float = DEFAULT_THRESHOLD) -> Fit:
    def flags(case: Labelled) -> bool:
        score = 1 - math.prod(1 - min(1.0, weights[n] * s) for n, s in case.strengths.items())
        return score >= threshold

    suspicious = [c for c in cases if c.suspicious]
    licit = [c for c in cases if not c.suspicious]
    return Fit(dict(weights), sum(map(flags, suspicious)), len(suspicious),
               sum(map(flags, licit)), len(licit))


def search(cases: list[Labelled], threshold: float = DEFAULT_THRESHOLD,
           grid: tuple[float, ...] = GRID) -> Fit:
    names = sorted(STRUCTURAL_DETECTORS)

    def distance(weights: dict[str, float]) -> float:
        return sum(abs(weights[n] - STRUCTURAL_WEIGHTS[n]) for n in names)

    fits = (measure(cases, dict(zip(names, combo, strict=True)), threshold)
            for combo in itertools.product(grid, repeat=len(names)))
    return max(fits, key=lambda f: (round(f.balanced_accuracy, 9), -distance(f.weights)))


def labelled_cases(directory: Path, subgraphs: int, seed: int, eval_subgraphs: int,
                   eval_seed: int, allow_overlap: bool) -> tuple[list[Labelled], int]:
    """The tuning subgraphs, scored, and how many of them the evaluation slice also holds."""
    labels = read_labels(directory)
    held_out = set(choose_subgraphs(labels, eval_subgraphs, eval_seed))
    slice_ = build_slice(directory, subgraphs, neighbors=0, seed=seed,
                         exclude=() if allow_overlap else held_out)
    cases = []
    for case in slice_.manifest.cases:
        graph = EvidenceGraph.from_batch(slice_.batch, case.transfer_ids)
        strengths = {name: detect(graph).strength for name, detect in STRUCTURAL_DETECTORS.items()}
        cases.append(Labelled(case.case_id, case.category == "planted", strengths))
    overlap = sum(c.case_id.removeprefix("elliptic2-") in held_out for c in cases)
    return cases, overlap


def _line(label: str, fit: Fit) -> str:
    precision = "n/a" if fit.precision is None else f"{fit.precision:.0%}"
    return (f"{label}: flags {fit.flagged_suspicious}/{fit.suspicious} suspicious "
            f"(recall {fit.recall:.0%}), {fit.flagged_licit}/{fit.licit} licit "
            f"(false positives {fit.false_positive_rate:.0%}), precision {precision}, "
            f"balanced accuracy {fit.balanced_accuracy:.0%}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lattice.eval.tune_structural",
                                     description=__doc__.split("\n")[0])
    parser.add_argument("--dir", type=Path, required=True, help="the unzipped Elliptic2 folder")
    parser.add_argument("--subgraphs", type=int, default=2000, help="size of the tuning slice")
    parser.add_argument("--seed", type=int, default=TUNING_SEED, help="tuning seed")
    parser.add_argument("--eval-subgraphs", type=int, default=100)
    parser.add_argument("--eval-seed", type=int, default=EVAL_SEED)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--allow-overlap", action="store_true",
                        help="tune on evaluation subgraphs too (the five-subgraph sample only)")
    parser.add_argument("--out", type=Path, help="write the result as JSON")
    args = parser.parse_args(argv)
    if args.seed == args.eval_seed:
        parser.error("the tuning seed must differ from the evaluation seed")

    cases, overlap = labelled_cases(args.dir, args.subgraphs, args.seed, args.eval_subgraphs,
                                    args.eval_seed, args.allow_overlap)
    if not cases:
        print("no subgraphs left to tune on once the evaluation slice is held out; "
              "pass --allow-overlap for the sample", file=sys.stderr)
        return 1

    print(f"tuning on {len(cases)} subgraphs (seed {args.seed}); evaluation slice: seed "
          f"{args.eval_seed}, {args.eval_subgraphs} subgraphs")
    if overlap:
        print(f"WARNING: {overlap} of the tuning subgraphs are also in the evaluation slice; "
              "this result is a smoke test, not a measurement")
    print("\ndetector firing rate (strength > 0) by label:")
    for name in sorted(STRUCTURAL_DETECTORS):
        for label, group in (("suspicious", [c for c in cases if c.suspicious]),
                             ("licit", [c for c in cases if not c.suspicious])):
            fired = sum(c.strengths[name] > 0 for c in group)
            print(f"  {name:20} {label:10} {fired}/{len(group)}")

    current = measure(cases, STRUCTURAL_WEIGHTS, args.threshold)
    best = search(cases, args.threshold)
    print("\n" + _line("current weights", current))
    print(_line("best weights   ", best))
    print("\nLATTICE_DETECTOR_WEIGHTS=" + json.dumps(best.weights, sort_keys=True))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({
            "tuning_seed": args.seed, "eval_seed": args.eval_seed,
            "eval_subgraphs": args.eval_subgraphs, "subgraphs": len(cases), "overlap": overlap,
            "threshold": args.threshold, "current": current.weights, "best": best.weights,
            "best_balanced_accuracy": best.balanced_accuracy,
            "current_balanced_accuracy": current.balanced_accuracy,
        }, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
