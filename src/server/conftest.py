"""
Pytest conftest — sets up isolated temp environment before server.py is imported.

server.py reads env vars at module level, so we must configure everything
before any test file can trigger the import.
"""
import os
import tempfile
import shutil

import yaml

# ── Create temp directory for test fixtures ──────────────────────────────────
TEST_DIR = tempfile.mkdtemp(prefix="oc_policy_test_")

# ── Test tokens ──────────────────────────────────────────────────────────────
AGENT_TOKEN = "test-agent-token"
ADMIN_TOKEN = "test-admin-token"
LEW_TOKEN   = "lew-test-token"
ALICE_TOKEN = "alice-test-token"
BOB_TOKEN   = "bob-test-token"

# ── Write test identities ───────────────────────────────────────────────────
IDENTITY_FILE = os.path.join(TEST_DIR, "identities.yaml")
with open(IDENTITY_FILE, "w") as f:
    yaml.dump({
        "version": 1,
        "people": [
            {"id": "lew",   "name": "Lew",   "telegram_id": "tg:111", "groups": ["admin"],       "api_token": LEW_TOKEN},
            {"id": "alice", "name": "Alice", "telegram_id": "tg:222", "groups": ["admin"],       "api_token": ALICE_TOKEN},
            {"id": "bob",   "name": "Bob",   "telegram_id": "tg:333", "groups": ["engineering"], "api_token": BOB_TOKEN},
        ],
    }, f, sort_keys=False)

# ── Write minimal test policies ──────────────────────────────────────────────
POLICY_FILE = os.path.join(TEST_DIR, "policies.yaml")
with open(POLICY_FILE, "w") as f:
    yaml.dump({
        "version": 1,
        "policies": [
            {"id": "deny-rm", "name": "Block rm", "description": "Block rm for everyone",
             "result": "deny", "priority": 50, "protected": True, "match": {"tool": "Bash", "program": "rm"}},
            {"id": "allow-admin-ls", "name": "Allow admin ls", "description": "Admin can ls",
             "result": "allow", "priority": 40, "match": {"tool": "Bash", "group": "admin", "program": "ls"}},
            {"id": "ask-git", "name": "Git needs approval", "description": "Git requires approval",
             "result": "pending", "priority": 30, "match": {"tool": "Bash", "program": "git"}},
        ],
    }, f, sort_keys=False)

# ── Audit file (empty) ──────────────────────────────────────────────────────
AUDIT_FILE = os.path.join(TEST_DIR, "audit.jsonl")

# ── Set env vars BEFORE server.py is imported ────────────────────────────────
os.environ["OC_POLICY_AGENT_TOKEN"] = AGENT_TOKEN
os.environ["OC_POLICY_ADMIN_TOKEN"] = ADMIN_TOKEN
os.environ["OC_POLICY_FILE"]       = POLICY_FILE
os.environ["OC_AUDIT_FILE"]        = AUDIT_FILE
os.environ["OC_IDENTITY_FILE"]     = IDENTITY_FILE
# No ANTHROPIC_API_KEY — NL chat will be disabled, which is fine for tests

import pytest
from starlette.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    """In-process test client — no running server needed."""
    from server import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def tokens():
    """All test tokens in a dict for convenience."""
    return {
        "agent": AGENT_TOKEN,
        "admin": ADMIN_TOKEN,
        "lew":   LEW_TOKEN,
        "alice": ALICE_TOKEN,
        "bob":   BOB_TOKEN,
    }


def pytest_sessionfinish(session, exitstatus):
    """Clean up temp directory after all tests."""
    shutil.rmtree(TEST_DIR, ignore_errors=True)
