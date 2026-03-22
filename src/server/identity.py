"""
Identity store — loads people from a YAML file and resolves by Telegram chat ID or API token.
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
    api_token: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "telegram_id": self.telegram_id,
            "groups": self.groups,
        }

    def is_admin(self) -> bool:
        return "admin" in self.groups


class IdentityStore:
    def __init__(self, identity_file: Path):
        self.identity_file = identity_file
        self._people: list[Person] = []
        self._by_telegram: dict[str, Person] = {}
        self._by_token: dict[str, Person] = {}
        self.reload()

    def reload(self) -> None:
        """Re-read people from the YAML file on disk."""
        if not self.identity_file.exists():
            self._people = []
            self._by_telegram = {}
            self._by_token = {}
            return

        with open(self.identity_file) as f:
            data = yaml.safe_load(f) or {}

        self._people = [
            Person(
                id=p["id"],
                name=p.get("name", p["id"]),
                telegram_id=str(p["telegram_id"]),
                groups=p.get("groups", []),
                api_token=p.get("api_token"),
            )
            for p in data.get("people", [])
        ]
        self._by_telegram = {p.telegram_id: p for p in self._people}
        self._by_token = {
            p.api_token: p for p in self._people if p.api_token
        }

    def resolve_by_telegram(self, telegram_id: str) -> Person | None:
        """Look up a person by their Telegram chat ID."""
        return self._by_telegram.get(str(telegram_id))

    def resolve_by_token(self, token: str) -> Person | None:
        """Look up a person by their API token."""
        return self._by_token.get(token)

    def list_all(self) -> list[Person]:
        return list(self._people)
