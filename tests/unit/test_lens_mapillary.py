"""The dashcam-drive finder behind the car's smooth front camera."""

from datetime import UTC, datetime

from lattice.lens.mapillary import drives

NOON = datetime(2022, 7, 1, 12, tzinfo=UTC).timestamp() * 1000
LAT0 = 51.5
LNG0 = -0.13


def _route(metres: float = 600.0) -> dict:
    """A straight road due north."""
    end = LAT0 + metres / 110_540
    return {"route": [[LNG0, LAT0], [LNG0, end]], "cumulative_m": [0.0, metres],
            "length_m": metres}


def _photo(i: int, seq: str, north_m: float, at_ms: float, angle: float = 0.0) -> dict:
    return {"id": f"{seq}-{i}", "sequence": seq, "is_pano": False, "captured_at": at_ms,
            "computed_compass_angle": angle, "creator": {"username": "driver"},
            "computed_geometry": {"coordinates": [LNG0, LAT0 + north_m / 110_540]}}


def _drive(seq: str, start_m: float, frames: int, spacing: float = 0.7,
           angle: float = 0.0) -> dict[str, dict]:
    return {f"{seq}-{i}": _photo(i, seq, start_m + i * spacing, NOON + i * 100, angle)
            for i in range(frames)}


def test_finds_a_dense_drive_in_order_and_drops_standing_frames():
    photos = _drive("a", 50.0, 400)
    # The car stood still for ten frames halfway: the same place, later times.
    for k in range(10):
        p = _photo(1000 + k, "a", 50.0 + 200 * 0.7, NOON + 200 * 100 + 10 + k)
        photos[p["id"]] = p
    found = drives(_route(), photos)
    assert len(found) == 1
    d = found[0]
    s = [f["s"] for f in d["frames"]]
    assert s == sorted(s)
    assert all(b - a >= 0.3 for a, b in zip(s, s[1:], strict=False))
    assert 45 < d["start"] < 60 and d["end"] - d["start"] > 250
    assert d["by"] == "driver" and d["date"] == "2022-07"
    assert len(d["frames"]) == 400  # every moving frame, none of the standing ones
    assert abs(d["frames"][1]["s"] - d["frames"][0]["s"] - 0.7) < 0.01  # the ends are not squashed


def test_skips_short_backward_facing_and_night_drives():
    photos = _drive("short", 0.0, 100)  # 70 m: too short
    photos |= _drive("back", 100.0, 400, angle=180.0)  # facing against the route
    night = _drive("night", 100.0, 400)
    for p in night.values():
        p["captured_at"] = datetime(2022, 1, 1, 23, tzinfo=UTC).timestamp() * 1000
    photos |= night
    assert drives(_route(), photos) == []


def test_one_drive_per_stretch_of_road():
    photos = _drive("a", 10.0, 420) | _drive("copy", 12.0, 400) | _drive("b", 330.0, 360)
    found = drives(_route(), photos)
    assert [d["seq"] for d in found] == ["a", "b"]  # the copy overlaps "a", which has more frames
