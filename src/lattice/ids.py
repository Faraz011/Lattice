"""Stable application-level IDs (R2, KTD6).

Generated data gets deterministic IDs from the generator seed, so the same seed always yields
the same graph. Runtime records (cases, ledger entries, actions, recordings) get random IDs.
Neo4j's internal element IDs are never used outside the database.
"""

import hashlib
import itertools
import uuid

PREFIXES = {
    "customer": "cust",
    "account": "acct",
    "device": "dev",
    "transfer": "tx",
    "alert": "alert",
    "case": "case",
    "ledger": "led",
    "action": "act",
    "recording": "rec",
}
_KINDS_BY_PREFIX = {prefix: kind for kind, prefix in PREFIXES.items()}


def _prefix(kind: str) -> str:
    try:
        return PREFIXES[kind]
    except KeyError:
        raise ValueError(f"unknown id kind: {kind!r}") from None


class IdFactory:
    """Deterministic IDs for generated data: same seed and call order, same IDs."""

    def __init__(self, seed: int) -> None:
        self._seed = seed
        self._counters: dict[str, itertools.count] = {}

    def next(self, kind: str) -> str:
        prefix = _prefix(kind)
        n = next(self._counters.setdefault(kind, itertools.count()))
        digest = hashlib.sha256(f"{self._seed}:{kind}:{n}".encode()).hexdigest()[:16]
        return f"{prefix}_{digest}"


def new_id(kind: str) -> str:
    """Random ID for records created at runtime."""
    return f"{_prefix(kind)}_{uuid.uuid4().hex[:16]}"


def link_id(rel_type: str, src: str, dst: str) -> str:
    """Stable ID for relationships that carry no `id` of their own (OWNS, USED_DEVICE)."""
    return f"{rel_type.lower()}:{src}:{dst}"


def kind_of(entity_id: str) -> str:
    prefix, sep, _ = entity_id.partition("_")
    if not sep or prefix not in _KINDS_BY_PREFIX:
        raise ValueError(f"not a Lattice id: {entity_id!r}")
    return _KINDS_BY_PREFIX[prefix]
