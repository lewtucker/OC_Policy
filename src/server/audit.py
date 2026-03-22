"""
Audit log — append-only log of every /check request.
Persists to a JSONL file so entries survive server restarts.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


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
    subject_id: str | None = None
    changed_by: str | None = None   # person ID who made a policy change (policy CRUD only)

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "tool": self.tool,
            "params": self.params,
            "verdict": self.verdict,
            "rule_id": self.rule_id,
            "reason": self.reason,
            "approval_id": self.approval_id,
            "subject_id": self.subject_id,
        }
        if self.changed_by:
            d["changed_by"] = self.changed_by
        return d


class AuditLog:
    def __init__(self, max_entries: int = 1000, log_file: Path | None = None) -> None:
        self._max = max_entries
        self._log_file = log_file
        self._entries: list[AuditEntry] = []
        if log_file:
            self._load(log_file)

    def _load(self, path: Path) -> None:
        """Read existing entries from disk on startup."""
        if not path.exists():
            return
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    self._entries.append(AuditEntry(
                        id=d["id"],
                        timestamp=datetime.fromisoformat(d["timestamp"]),
                        tool=d["tool"],
                        params=d["params"],
                        verdict=d["verdict"],
                        rule_id=d.get("rule_id"),
                        reason=d["reason"],
                        approval_id=d.get("approval_id"),
                        subject_id=d.get("subject_id"),
                    ))
                except Exception:
                    pass  # skip malformed lines
        # Trim to max
        if len(self._entries) > self._max:
            self._entries = self._entries[-self._max:]

    def append(
        self,
        tool: str,
        params: dict,
        verdict: str,
        rule_id: str | None,
        reason: str,
        approval_id: str | None = None,
        subject_id: str | None = None,
        changed_by: str | None = None,
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
            subject_id=subject_id,
            changed_by=changed_by,
        )
        self._entries.append(entry)
        if len(self._entries) > self._max:
            self._entries = self._entries[-self._max:]

        # Persist to disk
        if self._log_file:
            with open(self._log_file, "a") as f:
                f.write(json.dumps(entry.to_dict()) + "\n")

        return entry

    def recent(self, limit: int = 100) -> list[AuditEntry]:
        return list(reversed(self._entries[-limit:]))
