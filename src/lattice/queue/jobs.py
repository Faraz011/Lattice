"""Typed job envelopes and the Redis key layout every worker shares (KTD3)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

# One stream per job type. `echo` is a no-op role used to check deployment and scaling.
JOB_TYPES = ("investigate", "hypothesis", "verify", "execute_action", "echo")


class Job(BaseModel):
    job_id: str
    type: str
    case_id: str
    attempt: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value not in JOB_TYPES:
            raise ValueError(f"unknown job type {value!r}")
        return value

    @classmethod
    def new(cls, job_type: str, case_id: str, payload: dict[str, Any] | None = None) -> "Job":
        return cls(
            job_id=uuid.uuid4().hex,
            type=job_type,
            case_id=case_id,
            payload=payload or {},
            created_at=datetime.now(UTC),
        )

    def retried(self) -> "Job":
        return self.model_copy(update={"attempt": self.attempt + 1})

    def to_fields(self) -> dict[str, str]:
        return {"job": self.model_dump_json()}

    @classmethod
    def from_fields(cls, fields: dict[str, str]) -> "Job":
        return cls.model_validate_json(fields["job"])


@dataclass(frozen=True)
class Keys:
    """Every Redis key Lattice uses, under one namespace (tests use a private one)."""

    namespace: str = "lattice"

    def stream(self, job_type: str) -> str:
        return f"{self.namespace}:jobs:{job_type}"

    def dead_letter(self) -> str:
        return f"{self.namespace}:jobs:dead"

    def done(self, job_id: str) -> str:
        return f"{self.namespace}:done:{job_id}"

    def events(self, case_id: str) -> str:
        return f"{self.namespace}:events:{case_id}"

    def limiter(self) -> str:
        return f"{self.namespace}:llm:bucket"

    def cache(self, digest: str) -> str:
        return f"{self.namespace}:llm:cache:{digest}"

    def usage(self, case_id: str) -> str:
        return f"{self.namespace}:usage:{case_id}"

    def fanin(self, case_id: str, part: str = "meta") -> str:
        return f"{self.namespace}:fanin:{case_id}:{part}"

    def fanin_deadlines(self) -> str:
        return f"{self.namespace}:fanin:deadlines"
