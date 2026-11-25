"""Real street photos along the car's London route, from Mapillary.

Mapillary holds street-level photos shared openly (CC BY-SA 4.0), many from dashcams. For every
5 m of the route this picks the best photo facing the car's way (and the best facing back, for
the rear camera): close to the road, pointing along it, recent, and from the same sequence as
the photo before where possible, so the view does not jump between photographers. It stores
only photo ids, positions and credits; the browser fetches the images themselves.

    uv run python -m lattice.lens.mapillary        # reads VITE_MAPILLARY_TOKEN from lens/.env.local
"""

import argparse
import base64
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
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


def sun_elevation(lat: float, lng: float, when_ms: float) -> float:
    """The sun's elevation in degrees at a place and moment (NOAA's approximation)."""
    d = datetime.fromtimestamp(when_ms / 1000, UTC)
    hour = d.hour + d.minute / 60 + d.second / 3600
    g = 2 * math.pi / 365 * (d.timetuple().tm_yday - 1 + (hour - 12) / 24)
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    solar_minutes = hour * 60 + eqtime + 4 * lng
    hour_angle = math.radians(solar_minutes / 4 - 180)
    phi = math.radians(lat)
    cos_zenith = (math.sin(phi) * math.sin(decl)
                  + math.cos(phi) * math.cos(decl) * math.cos(hour_angle))
    return 90 - math.degrees(math.acos(max(-1.0, min(1.0, cos_zenith))))


def lighting(photo: dict) -> str:
    """'day' with the sun up, 'night' once it is well down, 'dusk' in between."""
    lng, lat = photo["computed_geometry"]["coordinates"]
    elevation = sun_elevation(lat, lng, photo.get("captured_at", 0))
    return "day" if elevation > 0 else "night" if elevation < -5 else "dusk"


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


def sequence_speeds(photos: dict[str, dict], lat0: float) -> dict[str, float]:
    """Each sequence's median speed in m/s, from the time and distance between its photos.

    A camera on a car moves at driving speed; a phone carried on the pavement moves at walking
    speed. The car's camera view should come from the first kind.
    """
    by_seq: dict[str, list[dict]] = {}
    for p in photos.values():
        if p.get("sequence") and p.get("captured_at"):
            by_seq.setdefault(p["sequence"], []).append(p)
    speeds = {}
    for seq, items in by_seq.items():
        items.sort(key=lambda p: p["captured_at"])
        steps = []
        for a, b in zip(items, items[1:], strict=False):
            dt = (b["captured_at"] - a["captured_at"]) / 1000
            if 0.2 < dt < 30:
                ax, ay = _metres(*a["computed_geometry"]["coordinates"], lat0)
                bx, by = _metres(*b["computed_geometry"]["coordinates"], lat0)
                steps.append(math.hypot(bx - ax, by - ay) / dt)
        if steps:
            steps.sort()
            speeds[seq] = steps[len(steps) // 2]
    return speeds


def choose(route: dict, photos: dict[str, dict], facing: float, light: str = "day") -> list[dict]:
    """The best photo for each STEP of the route; `facing` 0 for forward, 180 for backward.

    Preferred: taken from a moving vehicle (its sequence moves at driving speed), in the
    carriageway rather than on the pavement, pointing along the road, recent, and from the same
    sequence as the photo before.
    """
    now = datetime.now(UTC).timestamp() * 1000
    lat0 = route["route"][0][1]
    speeds = sequence_speeds(photos, lat0)
    flat = [p for p in photos.values() if not p.get("is_pano") and lighting(p) == light]
    where = {p["id"]: _metres(*p["computed_geometry"]["coordinates"], lat0) for p in flat}
    cell = 20.0  # a grid of 20 m cells, so each point only looks at photos nearby
    grid: dict[tuple[int, int], list[dict]] = {}
    for p in flat:
        x, y = where[p["id"]]
        grid.setdefault((int(x // cell), int(y // cell)), []).append(p)
    chosen: list[dict] = []
    last_seq = None
    last_time = None
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
            speed = speeds.get(p.get("sequence"), 0.0)
            walking = 0 if speed >= 3.5 else 30 if speed >= 1.5 else 60  # not from a vehicle
            pavement = 4 * max(0.0, dist - 6)  # off the carriageway
            # The same drive where possible; failing that, a photo from about the same day, so
            # the weather, the season and the light stay the same from photo to photo.
            days_apart = (abs(p.get("captured_at", 0) - last_time) / 8.64e7
                          if last_time else 0.0)
            switch = 0 if same else 22 + min(20.0, days_apart / 30)
            score = (dist + pavement + 0.35 * off + 3 * max(0.0, years) + walking + switch)
            if score < best_score:
                best, best_score = p, score
        if best:
            last_seq = best.get("sequence")
            last_time = best.get("captured_at")
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


KEEP = {  # Mapillary's detection classes worth boxing, by what we call them
    "object--vehicle--car": "car", "object--vehicle--bus": "bus",
    "object--vehicle--truck": "truck", "object--vehicle--motorcycle": "motorcycle",
    "object--vehicle--other-vehicle": "vehicle", "object--vehicle--caravan": "vehicle",
    "human--person--individual": "person", "human--rider--bicyclist": "cyclist",
    "human--rider--motorcyclist": "rider",
}


def _kind(value: str) -> str | None:
    if value.startswith("object--traffic-light--") and "pedestrians" not in value:
        return "light"
    return KEEP.get(value)


def _points(coords) -> list[list[float]]:
    """Every [x, y] in a geometry's nested coordinate lists."""
    if coords and isinstance(coords[0], (int, float)):
        return [coords]
    return [p for c in coords for p in _points(c)]


def detections(photo_id: str, token: str) -> list[dict]:
    """Mapillary's own detections in one photo: vehicles, people and traffic lights, as boxes
    with corners as fractions of the image (x right, y down)."""
    import mapbox_vector_tile

    url = f"https://graph.mapillary.com/{photo_id}/detections?fields=value,geometry"
    try:
        found = _get(url, token).get("data", [])
    except (OSError, ValueError):
        return []
    boxes = []
    for det in found:
        kind = _kind(det.get("value", ""))
        if not kind or not det.get("geometry"):
            continue
        tile = mapbox_vector_tile.decode(base64.b64decode(det["geometry"]),
                                         default_options={"y_coord_down": True})
        for layer in tile.values():
            extent = layer.get("extent", 4096)
            for feature in layer.get("features", []):
                points = _points(feature["geometry"]["coordinates"])
                if not points:
                    continue
                xs = [p[0] / extent for p in points]
                ys = [p[1] / extent for p in points]
                box = [min(xs), min(ys), max(xs), max(ys)]
                w, h = box[2] - box[0], box[3] - box[1]
                small = w < 0.008 or h < 0.015 or (kind != "light" and w * h < 0.0006)
                if not small and w < 0.9:
                    boxes.append({"kind": kind, "box": [round(v, 4) for v in box]})
    return boxes


def attach_detections(tracks: list[list[dict]], token: str) -> None:
    """Add each chosen photo's detections, fetched eight at a time."""
    ids = sorted({p["id"] for track in tracks for p in track})
    with ThreadPoolExecutor(max_workers=8) as pool:
        found = dict(zip(ids, pool.map(lambda i: detections(i, token), ids), strict=True))
    for track in tracks:
        for p in track:
            p["objects"] = found.get(p["id"], [])
    seen = sum(len(v) for v in found.values())
    print(f"detections: {seen} vehicles, people and lights across {len(ids)} photos")


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
    # The raw search results, kept out of git: re-picking from them takes seconds, searching
    # again about twenty minutes.
    parser.add_argument("--cache", type=Path, default=Path("data/mapillary-photos.json"))
    parser.add_argument("--refresh", action="store_true", help="search Mapillary again")
    args = parser.parse_args(argv)
    route = json.loads(args.route.read_text())
    if args.cache.exists() and not args.refresh:
        photos = json.loads(args.cache.read_text())
        print(f"{len(photos)} photos from {args.cache} (--refresh to search again)")
    else:
        photos = fetch(route, _token(args.env))
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        args.cache.write_text(json.dumps(photos))
    tracks = {f"{side}_{light}": choose(route, photos, facing, light)
              for side, facing in (("front", 0), ("rear", 180)) for light in ("day", "night")}
    cover = {k: round(coverage(route, v), 3) for k, v in tracks.items()}
    # Too few night photos to drive on: the browser darkens day photos instead.
    for k in ("front_night", "rear_night"):
        if cover[k] < 0.6:
            tracks[k] = []
    attach_detections([t for t in tracks.values() if t], _token(args.env))
    data = {
        "source": "Mapillary contributors, CC BY-SA 4.0",
        "step_m": STEP,
        "front": tracks["front_day"],
        "rear": tracks["rear_day"],
        "front_night": tracks["front_night"],
        "rear_night": tracks["rear_night"],
        "coverage": cover,
    }
    args.out.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    print(f"{len(photos)} photos near the route. Coverage: "
          + ", ".join(f"{k} {v:.0%}" for k, v in cover.items()) + f" -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
