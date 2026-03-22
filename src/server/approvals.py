"""
Approvals queue — in-memory store for pending tool call approvals.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ApprovalRecord:
    id: str
    tool: str
    params: dict
    rule_id: str
    created_at: datetime
    verdict: str | None = None       # None = pending; "allow" | "deny" = resolved
    reason: str | None = None
    resolved_at: datetime | None = None
    subject_id: str | None = None    # person who triggered the request

    @property
    def is_pending(self) -> bool:
        return self.verdict is None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tool": self.tool,
            "params": self.params,
            "rule_id": self.rule_id,
            "created_at": self.created_at.isoformat(),
            "verdict": self.verdict,
            "reason": self.reason,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "subject_id": self.subject_id,
        }


class ApprovalStore:
    def __init__(self) -> None:
        self._records: dict[str, ApprovalRecord] = {}

    def create(self, tool: str, params: dict, rule_id: str, subject_id: str | None = None) -> ApprovalRecord:
        record = ApprovalRecord(
            id=str(uuid.uuid4()),
            tool=tool,
            params=params,
            rule_id=rule_id,
            created_at=datetime.now(timezone.utc),
            subject_id=subject_id,
        )
        self._records[record.id] = record
        return record

    def get(self, approval_id: str) -> ApprovalRecord | None:
        return self._records.get(approval_id)

    def resolve(self, approval_id: str, verdict: str, reason: str | None = None) -> ApprovalRecord | None:
        record = self._records.get(approval_id)
        if record is None or not record.is_pending:
            return None
        record.verdict = verdict
        record.reason = reason
        record.resolved_at = datetime.now(timezone.utc)
        return record

    def list_all(self) -> list[ApprovalRecord]:
        return sorted(self._records.values(), key=lambda r: r.created_at, reverse=True)

    def list_pending(self) -> list[ApprovalRecord]:
        return [r for r in self.list_all() if r.is_pending]
