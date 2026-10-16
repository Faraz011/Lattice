import pytest

from lattice.ids import IdFactory, kind_of


def test_same_seed_produces_identical_ids():
    first = IdFactory(seed=42)
    second = IdFactory(seed=42)

    a = [first.next("account") for _ in range(5)] + [first.next("transfer") for _ in range(5)]
    b = [second.next("account") for _ in range(5)] + [second.next("transfer") for _ in range(5)]

    assert a == b


def test_different_seeds_produce_different_ids():
    a = [IdFactory(seed=1).next("account") for _ in range(1)]
    b = [IdFactory(seed=2).next("account") for _ in range(1)]

    assert a != b


def test_ids_are_unique_within_one_factory():
    factory = IdFactory(seed=7)

    ids = [factory.next("transfer") for _ in range(10_000)]

    assert len(set(ids)) == len(ids)


def test_ids_carry_the_prefix_of_their_kind():
    factory = IdFactory(seed=3)

    assert factory.next("customer").startswith("cust_")
    assert factory.next("account").startswith("acct_")
    assert factory.next("device").startswith("dev_")
    assert factory.next("transfer").startswith("tx_")
    assert factory.next("alert").startswith("alert_")


def test_kind_of_reads_the_kind_back_from_an_id():
    factory = IdFactory(seed=3)

    assert kind_of(factory.next("transfer")) == "transfer"
    assert kind_of(factory.next("account")) == "account"


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="unknown id kind"):
        IdFactory(seed=1).next("planet")


def test_kind_of_rejects_an_unprefixed_id():
    with pytest.raises(ValueError, match="not a Lattice id"):
        kind_of("4:abc:12")
