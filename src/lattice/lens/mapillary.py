"""Real street photos along the car's London route, from Mapillary.

Mapillary holds street-level photos shared openly (CC BY-SA 4.0), many from dashcams. For every
5 m of the route this picks the best photo facing the car's way (and the best facing back, for
the rear camera): close to the road, pointing along it, recent, and from the same sequence as
the photo before where possible, so the view does not jump between photographers. It stores
only photo ids, positions and credits; the browser fetches the images themselves.

    uv run python -m lattice.lens.mapillary        # reads VITE_MAPILLARY_TOKEN from lens/.env.local
"""

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

API = "https://graph.mapillary.com/images"
FIELDS = "id,computed_geometry,computed_compass_angle,captured_at,is_pano,sequence,creator"
STEP = 5.0  # metres between route points that get a photo
NEAR = 14.0  # a photo further than this from the road is not of it
CONE = 40.0  # degrees a photo may point away from the direction of travel
HALF = 0.0007  # half-size, in degrees, of the box searched around each route point
AGENT = {"User-Agent": "lattice-lens-demo/1.0 (open-source demo; one-off fetch)"}


def _token(path: Path) -> str:
    token = os.environ.get("VITE_MAPILLARY_TOKEN", "")
    if not token and path.exists():
        for line in path.read_text().splitlines():
            if line.startswith("VITE_MAPILLARY_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"')
    if not token:
        raise SystemExit("No Mapillary token: set VITE_MAPILLARY_TOKEN in lens/.env.local")
    return token


def _get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={**AGENT, "Authorization": f"OAuth {token}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                return json.load(res)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 + attempt * 3)
                continue
            raise
    return {}


def _metres(lng: float, lat: float, lat0: float) -> tuple[float, float]:
    return lng * 111_320 * math.cos(math.radians(lat0)), lat * 110_540


def _pose(route: dict, s: float) -> tuple[float, float, float]:
    """(lng, lat, bearing) at `s` metres along the route."""
    pts, cum = route["route"], route["cumulative_m"]
    s %= route["length_m"]
    lo, hi = 0, len(cum) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (mid, hi) if cum[mid] <= s else (lo, mid)
    a, b = pts[lo], pts[hi]
    t = (s - cum[lo]) / max(cum[hi] - cum[lo], 1e-6)
    lng, lat = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
    ax, ay = _metres(a[0], a[1], lat)
    bx, by = _metres(b[0], b[1], lat)
    return lng, lat, (math.degrees(math.atan2(bx - ax, by - ay)) + 360) % 360


def fetch(route: dict, token: str) -> dict[str, dict]:
    """Every photo near the route, by id."""
    photos: dict[str, dict] = {}
    boxes = []
    for k in range(int(route["length_m"] // 40) + 1):
        lng, lat, _ = _pose(route, k * 40.0)
        boxes.append((lng - HALF * 1.6, lat - HALF, lng + HALF * 1.6, lat + HALF))
    for i, (w, s, e, n) in enumerate(boxes):
        query = urllib.parse.urlencode(
            {"fields": FIELDS, "bbox": f"{w},{s},{e},{n}", "limit": 2000}
        )
        for p in _get(f"{API}?{query}", token).get("data", []):
            if p.get("computed_geometry") and p.get("computed_compass_angle") is not None:
                photos[p["id"]] = p
        if i % 25 == 0:
            print(f"  searched {i + 1}/{len(boxes)} stretches, {len(photos)} photos so far")
    return photos


def choose(route: dict, photos: dict[str, dict], facing: float) -> list[dict]:
    """The best photo for each STEP of the route; `facing` 0 for forward, 180 for backward."""
    now = datetime.now(UTC).timestamp() * 1000
    lat0 = route["route"][0][1]
    flat = [p for p in photos.values() if not p.get("is_pano")]
    where = {p["id"]: _metres(*p["computed_geometry"]["coordinates"], lat0) for p in flat}
    cell = 20.0  # a grid of 20 m cells, so each point only looks at photos nearby
    grid: dict[tuple[int, int], list[dict]] = {}
    for p in flat:
        x, y = where[p["id"]]
        grid.setdefault((int(x // cell), int(y // cell)), []).append(p)
    chosen: list[dict] = []
    last_seq = None
    s = 0.0
    while s < route["length_m"]:
        lng, lat, bearing = _pose(route, s)
        want = (bearing + facing) % 360
        here = _metres(lng, lat, lat0)
        best, best_score = None, math.inf
        cx, cy = int(here[0] // cell), int(here[1] // cell)
        nearby = [p for i in (-1, 0, 1) for j in (-1, 0, 1) for p in grid.get((cx + i, cy + j), [])]
        for p in nearby:
            dx, dy = where[p["id"]][0] - here[0], where[p["id"]][1] - here[1]
            dist = math.hypot(dx, dy)
            if dist > NEAR:
                continue
            off = abs((p["computed_compass_angle"] - want + 540) % 360 - 180)
            if off > CONE:
                continue
            years = (now - p.get("captured_at", now)) / 3.156e10
            same = p.get("sequence") == last_seq
            score = dist + 0.35 * off + 1.5 * max(0.0, years) + (0 if same else 10)
            if score < best_score:
                best, best_score = p, score
        if best:
            last_seq = best.get("sequence")
            if not chosen or chosen[-1]["id"] != best["id"]:
                plng, plat = best["computed_geometry"]["coordinates"]
                chosen.append(
                    {
                        "s": round(s, 1),
                        "id": best["id"],
                        "lng": plng,
                        "lat": plat,
                        "angle": round(best["computed_compass_angle"], 1),
                        "seq": best.get("sequence"),
                        "by": (best.get("creator") or {}).get("username", ""),
                        "date": datetime.fromtimestamp(
                            best.get("captured_at", 0) / 1000, UTC
                        ).strftime("%Y-%m"),
                    }
                )
        s += STEP
    return chosen


def coverage(route: dict, chosen: list[dict]) -> float:
    """Share of the route within 25 m of a chosen photo."""
    if not chosen:
        return 0.0
    marks = sorted(c["s"] for c in chosen)
    covered = 0.0
    s = 0.0
    j = 0
    while s < route["length_m"]:
        while j + 1 < len(marks) and marks[j + 1] <= s:
            j += 1
        if abs(s - marks[j]) <= 25 or (j + 1 < len(marks) and abs(marks[j + 1] - s) <= 25):
            covered += STEP
        s += STEP
    return covered / route["length_m"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lattice.lens.mapillary", description=__doc__.split("\n")[0]
    )
    parser.add_argument("--route", type=Path, default=Path("lens/public/maps/london.json"))
    parser.add_argument("--env", type=Path, default=Path("lens/.env.local"))
    parser.add_argument("--out", type=Path, default=Path("lens/public/maps/london-mapillary.json"))
    args = parser.parse_args(argv)
    route = json.loads(args.route.read_text())
    token = _token(args.env)
    photos = fetch(route, token)
    front, rear = choose(route, photos, 0), choose(route, photos, 180)
    data = {
        "source": "Mapillary contributors, CC BY-SA 4.0",
        "step_m": STEP,
        "front": front,
        "rear": rear,
        "coverage": {
            "front": round(coverage(route, front), 3),
            "rear": round(coverage(route, rear), 3),
        },
    }
    args.out.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    cover = data["coverage"]
    print(f"{len(photos)} photos near the route; chose {len(front)} forward and {len(rear)} back.")
    print(f"Coverage: front {cover['front']:.0%}, rear {cover['rear']:.0%} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
