"""
Audit log — append-only in-memory log of every /check request.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class AuditEntry:
    id: str
    timestamp: datetime
    tool: str
    params: dict
    verdict: str          # "allow" | "deny" | "pending"
    rule_id: str | None
    reason: str
    approval_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "tool": self.tool,
            "params": self.params,
            "verdict": self.verdict,
            "rule_id": self.rule_id,
            "reason": self.reason,
            "approval_id": self.approval_id,
        }


class AuditLog:
    def __init__(self, max_entries: int = 1000) -> None:
        self._entries: list[AuditEntry] = []
        self._max = max_entries

    def append(
        self,
        tool: str,
        params: dict,
        verdict: str,
        rule_id: str | None,
        reason: str,
        approval_id: str | None = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            tool=tool,
            params=params,
            verdict=verdict,
            rule_id=rule_id,
            reason=reason,
            approval_id=approval_id,
        )
        self._entries.append(entry)
        if len(self._entries) > self._max:
            self._entries = self._entries[-self._max:]
        return entry

    def recent(self, limit: int = 100) -> list[AuditEntry]:
        return list(reversed(self._entries[-limit:]))
