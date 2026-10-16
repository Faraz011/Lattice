"""Each detector on small hand-built evidence graphs: what fires it, and what does not."""

from datetime import UTC, datetime, timedelta

from lattice.graph.subgraph import AccountInfo, DeviceLink, EvidenceGraph, Transfer
from lattice.scoring import detectors
from lattice.scoring.scorer import Scorer

T0 = datetime(2026, 2, 1, 9, tzinfo=UTC)
OLD = T0 - timedelta(days=900)


class Builder:
    def __init__(self) -> None:
        self.transfers: list[Transfer] = []
        self.accounts: dict[str, AccountInfo] = {}
        self.links: list[DeviceLink] = []

    def account(self, name, kind="person", created=OLD, customer=None):
        self.accounts[name] = AccountInfo(id=name, kind=kind, created_at=created,
                                          customer_id=customer or f"cust_{name}")
        return name

    def send(self, src, dst, amount, at, channel="wire"):
        for name in (src, dst):
            if name not in self.accounts:
                self.account(name)
        tid = f"tx_{len(self.transfers)}"
        self.transfers.append(Transfer(id=tid, src=src, dst=dst, amount=amount, ts=at,
                                       channel=channel))
        return tid

    def link(self, account, device):
        lid = f"used_device:{account}:{device}"
        self.links.append(DeviceLink(id=lid, account_id=account, device_id=device))
        return lid

    def graph(self) -> EvidenceGraph:
        return EvidenceGraph.build(self.transfers, self.accounts, self.links)


def hours(n):
    return timedelta(hours=n)


def peeling(b: Builder, hops=6, peel=True) -> list[str]:
    forwards = [b.send("exchange", "a0", 100_000, T0, "crypto")]
    b.account("exchange", kind="exchange")
    amount, t = 100_000.0, T0
    for i in range(hops):
        t += hours(6)
        if peel:
            b.send(f"a{i}", f"cash{i}", amount * 0.05, t)
            amount *= 0.95
        forwards.append(b.send(f"a{i}", f"a{i + 1}", amount, t + hours(1)))
    return forwards


# --- peeling chain ------------------------------------------------------------------------


def test_a_long_peeling_chain_fires_at_full_strength_with_all_its_edges():
    b = Builder()
    forwards = peeling(b)

    result = detectors.peeling_chain(b.graph())

    assert result.strength == 1.0
    assert set(forwards) <= set(result.edges)


def test_removing_a_middle_hop_weakens_the_peeling_chain():
    b = Builder()
    forwards = peeling(b, hops=6)
    full = detectors.peeling_chain(b.graph())

    cut = detectors.peeling_chain(b.graph().without({forwards[3]}))

    assert cut.strength < full.strength
    assert full.edges[forwards[3]] > 0


def test_forwarding_without_skimming_is_not_a_peeling_chain():
    b = Builder()
    peeling(b, peel=False)

    assert detectors.peeling_chain(b.graph()).strength == 0


# --- fan in / fan out ---------------------------------------------------------------------


def test_many_deposits_just_under_the_threshold_within_days_fire_fan_in():
    b = Builder()
    for i in range(12):
        b.send(f"mule{i}", "collector", 9_500, T0 + hours(i * 6), "cash_deposit")

    result = detectors.fan_in_structuring(b.graph())

    assert result.strength == 1.0
    assert result.anchor == "collector"


def test_deposits_above_the_threshold_are_not_structuring():
    b = Builder()
    for i in range(12):
        b.send(f"mule{i}", "collector", 12_000, T0 + hours(i * 6))

    assert detectors.fan_in_structuring(b.graph()).strength == 0


def test_structuring_spread_over_a_month_does_not_fire():
    b = Builder()
    for i in range(12):
        b.send(f"mule{i}", "collector", 9_500, T0 + timedelta(days=i * 3))

    assert detectors.fan_in_structuring(b.graph()).strength < 0.5


def test_a_large_deposit_split_across_many_recipients_fires_fan_out():
    b = Builder()
    b.send("exchange", "hub", 60_000, T0, "crypto")
    for i in range(12):
        b.send("hub", f"r{i}", 4_800, T0 + hours(2 + i))

    result = detectors.fan_out(b.graph())

    assert result.strength == 1.0
    assert result.anchor == "hub"


def test_payouts_spread_over_ten_days_are_not_fan_out():
    b = Builder()
    b.send("exchange", "hub", 60_000, T0, "crypto")
    for i in range(12):
        b.send("hub", f"r{i}", 4_800, T0 + timedelta(days=i))

    assert detectors.fan_out(b.graph()).strength < 0.5


# --- cycles and layering ------------------------------------------------------------------


def test_similar_amounts_returning_within_two_weeks_fire_round_trip():
    b = Builder()
    b.send("a", "b", 30_000, T0)
    b.send("b", "c", 29_500, T0 + timedelta(days=2))
    b.send("c", "a", 29_000, T0 + timedelta(days=4))

    assert detectors.round_trip(b.graph()).strength == 1.0


def test_a_slow_cycle_of_unequal_amounts_is_not_round_trip():
    b = Builder()
    b.send("a", "b", 300, T0)
    b.send("b", "c", 1_200, T0 + timedelta(days=12))
    b.send("c", "a", 90, T0 + timedelta(days=30))

    assert detectors.round_trip(b.graph()).strength == 0


def test_whole_amounts_through_new_accounts_within_hours_fire_layering():
    b = Builder()
    b.account("src")
    for i in range(5):
        b.account(f"young{i}", created=T0 - timedelta(days=3))
    route = ["src", *[f"young{i}" for i in range(5)], "dest"]
    amount = 50_000.0
    for i, (s, d) in enumerate(zip(route, route[1:], strict=False)):
        amount *= 0.99
        b.send(s, d, amount, T0 + hours(i * 2))

    assert detectors.rapid_layering(b.graph()).strength == 1.0


def test_the_same_route_through_old_accounts_is_not_layering():
    b = Builder()
    route = ["src", *[f"old{i}" for i in range(5)], "dest"]
    for i, (s, d) in enumerate(zip(route, route[1:], strict=False)):
        b.send(s, d, 50_000 * 0.99 ** (i + 1), T0 + hours(i * 2))

    assert detectors.rapid_layering(b.graph()).strength == 0


# --- devices and exits --------------------------------------------------------------------


def test_unrelated_customers_on_one_device_paying_one_destination_fire_shared_device():
    b = Builder()
    for i in range(4):
        b.account(f"s{i}", customer=f"cust_{i}")
        b.link(f"s{i}", "dev_1")
        b.send(f"s{i}", "dest", 5_000, T0 + hours(i))

    result = detectors.shared_device(b.graph())

    assert result.strength == 1.0
    assert all(f"used_device:s{i}:dev_1" in result.edges for i in range(4))


def test_one_customers_own_accounts_sharing_a_device_is_not_suspicious():
    b = Builder()
    for i in range(4):
        b.account(f"s{i}", customer="cust_same")
        b.link(f"s{i}", "dev_1")
        b.send(f"s{i}", "dest", 5_000, T0 + hours(i))

    assert detectors.shared_device(b.graph()).strength == 0


def test_funds_routed_through_a_mixer_to_an_exchange_fire_exit():
    b = Builder()
    b.account("mixer", kind="mixer")
    b.account("exchange", kind="exchange")
    b.send("src", "hop", 40_000, T0)
    b.send("hop", "mixer", 38_000, T0 + hours(5))
    b.send("mixer", "exchange", 36_000, T0 + hours(20))

    assert detectors.exit_via_mixer(b.graph()).strength == 1.0


def test_paying_an_exchange_directly_is_not_a_mixer_exit():
    b = Builder()
    b.account("exchange", kind="exchange")
    b.send("src", "exchange", 2_000, T0)

    assert detectors.exit_via_mixer(b.graph()).strength == 0


# --- dampener -----------------------------------------------------------------------------


def test_a_business_paying_fixed_monthly_salaries_is_dampened_below_threshold():
    b = Builder()
    b.account("employer", kind="business")
    for month in range(3):
        payday = T0.replace(month=month + 1, day=25)
        b.send("client", "employer", 70_000, payday - hours(20))
        for i in range(12):
            b.send("employer", f"staff{i}", 4_000 + i * 100, payday)

    result = Scorer().score(b.graph())

    assert detectors.fan_out(b.graph()).strength == 1.0  # the raw shape is there
    assert result.score < Scorer().threshold
