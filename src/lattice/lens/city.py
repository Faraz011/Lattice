"""A real drive through central London for the car, from OpenStreetMap data.

Fetches, once, a driving route over real roads (the public OSRM router) and every traffic signal
and pedestrian crossing mapped along it (the OpenStreetMap Overpass API), then places each one at
its distance along the route. The result is committed, so the demo never calls these services:

    uv run python -m lattice.lens.city            # writes lens/public/maps/london.json

The simulation stays one-dimensional (metres along the route), which is all the car's network
sees; the map draws the same positions at their real coordinates.
"""

import argparse
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# A loop through Westminster and the Strand: Parliament Square, Whitehall, Trafalgar Square,
# the Strand, Aldwych, Waterloo Bridge, the South Bank, Westminster Bridge.
WAYPOINTS = [
    (-0.12620, 51.50080),  # Parliament Square
    (-0.12640, 51.50440),  # Whitehall
    (-0.12820, 51.50770),  # Trafalgar Square
    (-0.12100, 51.51060),  # the Strand
    (-0.11720, 51.51270),  # Aldwych
    (-0.11620, 51.50800),  # Waterloo Bridge
    (-0.11450, 51.50460),  # Waterloo Road
    (-0.11800, 51.50160),  # Westminster Bridge Road
    (-0.12230, 51.50080),  # Westminster Bridge
    (-0.12620, 51.50080),  # back to Parliament Square
]
OSRM = "https://router.project-osrm.org/route/v1/driving/"
# Overpass is often busy: try the main server, then the public mirrors.
OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
AGENT = {"User-Agent": "lattice-lens-demo/1.0 (open-source demo; one-off fetch)"}
NEAR_M = 14  # a signal or crossing this close to the route is on it
MERGE_M = 30  # signals closer than this along the route are one junction


def _get(url: str, data: bytes | None = None) -> dict:
    req = urllib.request.Request(url, data=data, headers=AGENT)
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.load(res)


def _metres(lng: float, lat: float, lat0: float) -> tuple[float, float]:
    """Local flat projection, accurate to centimetres over a few kilometres."""
    k = 111_320.0
    return lng * k * math.cos(math.radians(lat0)), lat * 110_540.0


def route() -> list[list[float]]:
    coords = ";".join(f"{lng},{lat}" for lng, lat in WAYPOINTS)
    data = _get(f"{OSRM}{coords}?overview=full&geometries=geojson&continue_straight=true")
    return data["routes"][0]["geometry"]["coordinates"]


def features(line: list[list[float]]) -> list[dict]:
    lngs, lats = [p[0] for p in line], [p[1] for p in line]
    s, w, n, e = min(lats) - 0.001, min(lngs) - 0.001, max(lats) + 0.001, max(lngs) + 0.001
    query = (f"[out:json][timeout:50];(node[highway=traffic_signals]({s},{w},{n},{e});"
             f"node[highway=crossing]({s},{w},{n},{e}););out;")
    body = urllib.parse.urlencode({"data": query}).encode()
    errors = []
    for attempt in range(2):
        for server in OVERPASS:
            try:
                return _get(server, body)["elements"]
            except (OSError, ValueError) as exc:  # HTTP errors and timeouts are OSErrors
                errors.append(f"{server}: {exc}")
                time.sleep(2 + attempt * 5)
    raise RuntimeError("no Overpass server answered: " + "; ".join(errors))


def place(line: list[list[float]], nodes: list[dict]) -> dict:
    lat0 = sum(p[1] for p in line) / len(line)
    pts = [_metres(p[0], p[1], lat0) for p in line]
    cum = [0.0]
    for a, b in zip(pts, pts[1:], strict=False):
        cum.append(cum[-1] + math.dist(a, b))

    def along(lng: float, lat: float) -> tuple[float, float]:
        """(distance along the route, distance from it) of the nearest route point."""
        q = _metres(lng, lat, lat0)
        best = (math.inf, 0.0)
        for i, (a, b) in enumerate(zip(pts, pts[1:], strict=False)):
            dx, dy = b[0] - a[0], b[1] - a[1]
            seg = dx * dx + dy * dy
            dot = (q[0] - a[0]) * dx + (q[1] - a[1]) * dy
            t = 0.0 if seg == 0 else max(0.0, min(1.0, dot / seg))
            px, py = a[0] + t * dx, a[1] + t * dy
            d = math.hypot(q[0] - px, q[1] - py)
            if d < best[0]:
                best = (d, cum[i] + t * math.sqrt(seg))
        return best[1], best[0]

    signals, crossings = [], []
    for node in nodes:
        at, off = along(node["lon"], node["lat"])
        if off > NEAR_M or at < 20 or at > cum[-1] - 20:
            continue
        tags = node.get("tags", {})
        item = {"at": round(at, 1), "lng": node["lon"], "lat": node["lat"]}
        if tags.get("highway") == "traffic_signals":
            signals.append(item)
        else:
            crossings.append({**item, "kind": tags.get("crossing", "unmarked")})
    signals.sort(key=lambda x: x["at"])
    merged: list[dict] = []
    for sig in signals:  # several signal nodes at one junction: one stop line, the first
        if not merged or sig["at"] - merged[-1]["at"] > MERGE_M:
            merged.append(sig)
    crossings.sort(key=lambda x: x["at"])
    return {
        "name": "Central London: Westminster, the Strand and Waterloo Bridge",
        "source": "Route: OSRM over OpenStreetMap. Signals and crossings: OpenStreetMap "
                  "contributors (ODbL).",
        "length_m": round(cum[-1], 1),
        "route": [[round(p[0], 6), round(p[1], 6)] for p in line],
        "cumulative_m": [round(c, 1) for c in cum],
        "signals": merged,
        "crossings": crossings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lattice.lens.city", description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=Path("lens/public/maps/london.json"))
    args = parser.parse_args(argv)
    line = route()
    data = place(line, features(line))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    print(f"{data['name']}: {data['length_m']:.0f} m, {len(data['signals'])} signalled junctions, "
          f"{len(data['crossings'])} crossings -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
