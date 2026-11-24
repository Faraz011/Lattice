"""The self-driving car: what the car sees, the expert it imitates, and its policy network.

The car drives up a road with traffic lights, crosswalks and other cars. Each tick it sees 13
numbers (`INPUTS`) and picks one of three actions (`OUTPUTS`). The policy network learns those
choices from a rule-based expert driver (`expert`) over randomly sampled situations.

The browser simulation computes the same 13 numbers from its own world, using the constants in
`PHYSICS`, which are exported with the model so both sides agree.

Nearness, not distance: an empty road is all zeros, so every hazard is something the network
sees switch on, never the absence of a "far off" signal.

Two hazards that both demand braking, a red light and a pedestrian on the crosswalk, are what
give the trace its backup route: switch off the neurons that carry one, and the other still
stops the car.
"""

import numpy as np

from lattice.lens.mlp import Feature

PHYSICS = {
    "view_m": 120.0,  # how far ahead the car sees; distances are divided by this
    "vmax_ms": 20.0,  # speeds are divided by this (72 km/h)
    "accel_ms2": 2.5,
    "brake_ms2": 6.0,
    "drag_ms2": 0.3,
    "comfort_brake_ms2": 4.0,  # the expert plans stops at this deceleration
    "tick_s": 0.1,
}

INPUTS = [
    Feature("speed", "fast", "The car's speed, as a share of 72 km/h.", "slow"),
    Feature("light_red", "red light", "The next traffic light ahead is red.", "no red light"),
    Feature("light_yellow", "yellow light", "The next traffic light ahead is yellow.",
            "no yellow light"),
    Feature("light_green", "green light", "The next traffic light ahead is green.",
            "no green light"),
    Feature("light_near", "near the light", "How close the next stop line is; 0 if none.",
            "light far off"),
    Feature("ped_crossing", "pedestrian on crosswalk", "Someone is on the crosswalk ahead.",
            "crosswalk clear"),
    Feature("ped_waiting", "pedestrian at curb", "Someone is waiting to cross ahead.",
            "nobody at the curb"),
    Feature("crosswalk_near", "near the crosswalk", "How close the next crosswalk is; 0 if none.",
            "crosswalk far off"),
    Feature("lead_car", "car ahead", "A car is ahead in this lane.", "no car ahead"),
    Feature("lead_near", "close behind a car", "How close the car ahead is; 0 if none.",
            "car ahead far off"),
    Feature("closing", "closing on car ahead", "How fast the gap is shrinking.", "not closing"),
    Feature("rain", "rain", "The road is wet: drive slower, stop earlier.", "dry road"),
    Feature("night", "night", "It is dark. The expert ignores this; a good policy should too.",
            "daylight"),
]

OUTPUTS = [
    Feature("accelerate", "accelerate"),
    Feature("cruise", "cruise"),
    Feature("brake", "brake"),
]

ACCELERATE, CRUISE, BRAKE = 0, 1, 2
IDX = {f.id: i for i, f in enumerate(INPUTS)}


def stopping_distance(speed: float, rain: bool) -> float:
    """Normalised distance to stop from `speed` (a share of vmax) at comfortable braking."""
    v = speed * PHYSICS["vmax_ms"]
    decel = PHYSICS["comfort_brake_ms2"] * (0.7 if rain else 1.0)
    return (v * v / (2 * decel)) / PHYSICS["view_m"]


def expert(x: np.ndarray) -> int:
    """The rule-based driver the policy imitates. One situation in, one action out."""
    speed, rain = x[IDX["speed"]], x[IDX["rain"]] > 0.5
    zone = stopping_distance(speed, rain) + 0.06  # brake once a hazard is this close
    hazards = []
    light = 1 - x[IDX["light_near"]]
    if x[IDX["light_red"]] > 0.5:
        hazards.append(light)
    if x[IDX["light_yellow"]] > 0.5 and light > stopping_distance(speed, rain) * 0.5:
        hazards.append(light)  # too close to stop on yellow: go through
    crosswalk = 1 - x[IDX["crosswalk_near"]]
    if x[IDX["ped_crossing"]] > 0.5 or x[IDX["ped_waiting"]] > 0.5:
        hazards.append(crosswalk)
    if x[IDX["lead_car"]] > 0.5:
        gap = 1 - x[IDX["lead_near"]]
        if gap < zone * 0.6 + x[IDX["closing"]] * 0.5 + 0.03:
            return BRAKE
    if any(h < zone for h in hazards):
        return BRAKE
    target = 0.5 if rain else 0.75
    if speed > target + 0.08:
        return BRAKE
    return ACCELERATE if speed < target - 0.04 else CRUISE


def sample(n: int, seed: int) -> np.ndarray:
    """Random driving situations, weighted toward the ones where the choice is hard."""
    rng = np.random.default_rng(seed)
    x = np.zeros((n, len(INPUTS)))
    x[:, IDX["speed"]] = rng.uniform(0, 1, n)
    x[:, IDX["rain"]] = rng.random(n) < 0.3
    x[:, IDX["night"]] = rng.random(n) < 0.5

    light = rng.random(n) < 0.6
    colour = rng.choice(3, n, p=[0.45, 0.2, 0.35])
    for k, name in enumerate(["light_red", "light_yellow", "light_green"]):
        x[:, IDX[name]] = light & (colour == k)
    x[:, IDX["light_near"]] = np.where(light, 1 - rng.uniform(0, 1, n) ** 1.5, 0.0)

    crosswalk = rng.random(n) < 0.55
    who = rng.choice(3, n, p=[0.35, 0.2, 0.45])
    x[:, IDX["ped_crossing"]] = crosswalk & (who == 0)
    x[:, IDX["ped_waiting"]] = crosswalk & (who == 1)
    x[:, IDX["crosswalk_near"]] = np.where(crosswalk, 1 - rng.uniform(0, 1, n) ** 1.5, 0.0)

    lead = rng.random(n) < 0.35
    x[:, IDX["lead_car"]] = lead
    x[:, IDX["lead_near"]] = np.where(lead, 1 - rng.uniform(0, 1, n) ** 1.5, 0.0)
    x[:, IDX["closing"]] = np.where(lead, np.clip(rng.normal(0.1, 0.2, n), 0, 1), 0.0)
    return x


def dataset(n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    x = sample(n, seed)
    y = np.array([expert(row) for row in x])
    return x, y


def concepts(x: np.ndarray) -> dict[str, np.ndarray]:
    """What the expert reasons about, per situation: used only to name the network's neurons."""
    out: dict[str, list[bool]] = {k: [] for k in (
        "red light ahead to stop for", "yellow light to stop for", "pedestrian in the path",
        "car ahead too close", "too fast", "below cruising speed", "at cruising speed", "rain")}
    for row in x:
        speed, rain = row[IDX["speed"]], row[IDX["rain"]] > 0.5
        zone = stopping_distance(speed, rain) + 0.06
        light = 1 - row[IDX["light_near"]]
        crosswalk = 1 - row[IDX["crosswalk_near"]]
        gap = 1 - row[IDX["lead_near"]]
        target = 0.5 if rain else 0.75
        out["red light ahead to stop for"].append(row[IDX["light_red"]] > 0.5 and light < zone)
        out["yellow light to stop for"].append(
            row[IDX["light_yellow"]] > 0.5 and stopping_distance(speed, rain) * 0.5 < light < zone)
        out["pedestrian in the path"].append(
            (row[IDX["ped_crossing"]] > 0.5 or row[IDX["ped_waiting"]] > 0.5) and crosswalk < zone)
        out["car ahead too close"].append(
            row[IDX["lead_car"]] > 0.5 and gap < zone * 0.6 + row[IDX["closing"]] * 0.5 + 0.03)
        out["too fast"].append(speed > target + 0.08)
        out["below cruising speed"].append(speed < target - 0.04)
        out["at cruising speed"].append(target - 0.04 <= speed <= target + 0.08)
        out["rain"].append(rain)
    return {k: np.array(v) for k, v in out.items()}
