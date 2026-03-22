"""
OC Policy Engine — Phase 2
Loads rules from a YAML file and evaluates tool call requests against them.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

Effect = Literal["allow", "deny", "pending"]


@dataclass
class Rule:
    id: str
    effect: Effect
    match: dict = field(default_factory=dict)
    priority: int = 0
    name: str = ""
    description: str = ""

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "effect": self.effect,
            "priority": self.priority,
            "match": self.match,
        }
        if not self.name:
            del d["name"]
        return d


class PolicyEngine:
    def __init__(self, policy_file: Path):
        self.policy_file = policy_file
        self._rules: list[Rule] = []
        self.reload()

    # ── Load / persist ────────────────────────────────────────────────────────

    def reload(self) -> None:
        """Re-read rules from the YAML file on disk."""
        if not self.policy_file.exists():
            self._rules = []
            return

        with open(self.policy_file) as f:
            data = yaml.safe_load(f) or {}

        self._rules = [
            Rule(
                id=p["id"],
                effect=p["effect"],
                match=p.get("match", {}),
                priority=p.get("priority", 0),
                name=p.get("name", ""),
                description=p.get("description", ""),
            )
            for p in data.get("policies", [])
        ]
        self._sort()

    def _save(self) -> None:
        """Write current rules back to the YAML file."""
        data = {
            "version": 1,
            "policies": [r.to_dict() for r in self._rules],
        }
        with open(self.policy_file, "w") as f:
            yaml.dump(data, f, sort_keys=False, allow_unicode=True)

    def _sort(self) -> None:
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    # ── CRUD ─────────────────────────────────────────────────────────────────

    @property
    def rules(self) -> list[Rule]:
        return list(self._rules)

    def add(self, rule_data: dict) -> Rule:
        """Append a rule and persist. Raises ValueError if ID already exists."""
        if any(r.id == rule_data["id"] for r in self._rules):
            raise ValueError(f"Rule '{rule_data['id']}' already exists")
        rule = Rule(
            id=rule_data["id"],
            effect=rule_data["effect"],
            match=rule_data.get("match", {}),
            priority=rule_data.get("priority", 0),
            name=rule_data.get("name", ""),
            description=rule_data.get("description", ""),
        )
        self._rules.append(rule)
        self._sort()
        self._save()
        return rule

    def update(self, rule_id: str, rule_data: dict) -> Rule:
        """Update an existing rule in-place and persist. Raises KeyError if not found."""
        for i, r in enumerate(self._rules):
            if r.id == rule_id:
                updated = Rule(
                    id=rule_id,
                    effect=rule_data["effect"],
                    match=rule_data.get("match", {}),
                    priority=rule_data.get("priority", 0),
                    name=rule_data.get("name", ""),
                    description=rule_data.get("description", ""),
                )
                self._rules[i] = updated
                self._sort()
                self._save()
                return updated
        raise KeyError(f"Rule '{rule_id}' not found")

    def remove(self, rule_id: str) -> bool:
        """Remove a rule by ID and persist. Returns True if found."""
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.id != rule_id]
        if len(self._rules) == before:
            return False
        self._save()
        return True

    # ── Evaluation ────────────────────────────────────────────────────────────

    def evaluate(self, tool: str, params: dict) -> tuple[Effect, str, str | None]:
        """
        Returns (effect, reason, matched_rule_id).
        Falls back to ("deny", "No policy permits this action", None) if no rule matches.
        """
        for rule in self._rules:
            if self._matches(rule, tool, params):
                reason = rule.description or f"Matched rule '{rule.id}'"
                return rule.effect, reason, rule.id

        return "deny", "No policy permits this action", None

    def _matches(self, rule: Rule, tool: str, params: dict) -> bool:
        m = rule.match

        # Empty match dict = wildcard (matches everything)
        if not m:
            return True

        # Tool name
        if "tool" in m and m["tool"] != tool:
            return False

        # Program (first word of exec command); supports * glob
        if "program" in m:
            command = str(params.get("command", ""))
            program = command.strip().split()[0] if command.strip() else ""
            if not fnmatch.fnmatch(program, m["program"]):
                return False

        # File path; supports * and ** glob
        if "path" in m:
            path = str(params.get("path", params.get("file", "")))
            if not fnmatch.fnmatch(path, m["path"]):
                return False

        return True
