"""The ground-truth manifest: the answer key for every planted case and decoy (R1).

It is written to a file and must never be loaded into Neo4j, where agents could read it.
"""

import json
from typing import Literal

from pydantic import BaseModel


class CaseRecord(BaseModel):
    case_id: str
    category: Literal["planted", "decoy"]
    kind: str
    expected_verdict: Literal["suspicious", "benign"]
    seed_account_id: str
    alert_id: str
    account_ids: list[str]
    transfer_ids: list[str]
    device_ids: list[str] = []
    # Set on a case whose transfer carries a prompt-injection memo.
    injected_transfer_id: str | None = None
    # Links an injected case and its memo-free twin, in both directions.
    twin_case_id: str | None = None


class Manifest(BaseModel):
    world: str
    seed: int
    reporting_threshold: float
    cases: list[CaseRecord]

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
