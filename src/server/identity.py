"""
Identity store — loads people and agents from a YAML file.
Resolves people by Telegram chat ID or API token.
Resolves agents by their bearer token.
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


@dataclass
class Agent:
    """An agent runtime (nanoclaw, openclaw, etc.) identified by its bearer token."""
    id: str
    name: str
    token: str
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
        }


class IdentityStore:
    def __init__(self, identity_file: Path):
        self.identity_file = identity_file
        self._people: list[Person] = []
        self._agents: list[Agent] = []
        self._by_telegram: dict[str, Person] = {}
        self._by_token: dict[str, Person] = {}
        self._by_agent_token: dict[str, Agent] = {}
        self.reload()

    def reload(self) -> None:
        """Re-read people and agents from the YAML file on disk."""
        if not self.identity_file.exists():
            self._people = []
            self._agents = []
            self._by_telegram = {}
            self._by_token = {}
            self._by_agent_token = {}
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

        self._agents = [
            Agent(
                id=a["id"],
                name=a.get("name", a["id"]),
                token=a["token"],
                description=a.get("description", ""),
            )
            for a in data.get("agents", [])
        ]
        self._by_agent_token = {a.token: a for a in self._agents}

    def resolve_by_telegram(self, telegram_id: str) -> Person | None:
        """Look up a person by their Telegram chat ID."""
        return self._by_telegram.get(str(telegram_id))

    def resolve_by_token(self, token: str) -> Person | None:
        """Look up a person by their API token."""
        return self._by_token.get(token)

    def resolve_agent(self, token: str) -> Agent | None:
        """Look up an agent runtime by its bearer token."""
        return self._by_agent_token.get(token)

    def is_valid_agent_token(self, token: str) -> bool:
        """Check if a token belongs to any registered agent."""
        return token in self._by_agent_token

    def list_all(self) -> list[Person]:
        return list(self._people)

    def list_agents(self) -> list[Agent]:
        return list(self._agents)
