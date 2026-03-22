"""
Identity store — loads people from a YAML file and resolves by Telegram chat ID.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Person:
    id: str
    name: str
    telegram_id: str
    groups: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "telegram_id": self.telegram_id,
            "groups": self.groups,
        }


class IdentityStore:
    def __init__(self, identity_file: Path):
        self.identity_file = identity_file
        self._people: list[Person] = []
        self._by_telegram: dict[str, Person] = {}
        self.reload()

    def reload(self) -> None:
        """Re-read people from the YAML file on disk."""
        if not self.identity_file.exists():
            self._people = []
            self._by_telegram = {}
            return

        with open(self.identity_file) as f:
            data = yaml.safe_load(f) or {}

        self._people = [
            Person(
                id=p["id"],
                name=p.get("name", p["id"]),
                telegram_id=str(p["telegram_id"]),
                groups=p.get("groups", []),
            )
            for p in data.get("people", [])
        ]
        self._by_telegram = {p.telegram_id: p for p in self._people}

    def resolve_by_telegram(self, telegram_id: str) -> Person | None:
        """Look up a person by their Telegram chat ID."""
        return self._by_telegram.get(str(telegram_id))

    def list_all(self) -> list[Person]:
        return list(self._people)
