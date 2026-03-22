"""
OC Policy Server — Comprehensive Pytest Suite

Self-contained: conftest.py creates temp fixtures (policies, identities,
audit file) and sets env vars before server.py is imported.

Run with:  cd src/server && python -m pytest test_policy_suite.py -v

Test categories:
  1. Auth & Authorization
  2. Protected Rules
  3. Policy Evaluation (/check)
  4. Policy Analyzer
  5. Approval Flow
  6. Audit Trail
  7. Policy CRUD
  8. Identities
"""
import pytest
from conftest import AGENT_TOKEN, ADMIN_TOKEN, LEW_TOKEN, ALICE_TOKEN, BOB_TOKEN


# ── Helpers ──────────────────────────────────────────────────────────────────

def agent_auth():
    return {"Authorization": f"Bearer {AGENT_TOKEN}"}

def admin_auth():
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}

def person_auth(token):
    return {"Authorization": f"Bearer {token}"}

def bad_auth():
    return {"Authorization": "Bearer wrong-token"}


# ═════════════════════════════════════════════════════════════════════════════
# 1. Auth & Authorization
# ═════════════════════════════════════════════════════════════════════════════

class TestAuth:
    """Token validation and role-based access."""

    def test_health_no_auth(self, client):
        """Health endpoint is public."""
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_check_requires_agent_token(self, client):
        r = client.post("/check", json={"tool": "Bash", "params": {}}, headers=bad_auth())
        assert r.status_code == 401

    def test_check_rejects_admin_token(self, client):
        """The /check endpoint only accepts the agent token, not admin."""
        r = client.post("/check", json={"tool": "Bash", "params": {}}, headers=admin_auth())
        assert r.status_code == 401

    def test_check_rejects_person_token(self, client):
        r = client.post("/check", json={"tool": "Bash", "params": {}}, headers=person_auth(LEW_TOKEN))
        assert r.status_code == 401

    def test_policies_requires_auth(self, client):
        r = client.get("/policies", headers=bad_auth())
        assert r.status_code == 401

    def test_policies_rejects_agent_token(self, client):
        """Agent token cannot access management endpoints."""
        r = client.get("/policies", headers=agent_auth())
        assert r.status_code == 401

    def test_admin_token_grants_access(self, client):
        r = client.get("/policies", headers=admin_auth())
        assert r.status_code == 200

    def test_admin_person_token_grants_access(self, client):
        """Lew is in the admin group — should have full access."""
        r = client.get("/policies", headers=person_auth(LEW_TOKEN))
        assert r.status_code == 200

    def test_non_admin_person_gets_403(self, client):
        """Bob is in engineering, not admin — should be blocked."""
        r = client.get("/policies", headers=person_auth(BOB_TOKEN))
        assert r.status_code == 403

    def test_me_returns_admin_identity(self, client):
        r = client.get("/me", headers=admin_auth())
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == "admin"
        assert "admin" in data["groups"]

    def test_me_returns_person_identity(self, client):
        r = client.get("/me", headers=person_auth(ALICE_TOKEN))
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == "alice"
        assert data["name"] == "Alice"

    def test_me_rejects_bad_token(self, client):
        r = client.get("/me", headers=bad_auth())
        assert r.status_code == 401


# ═════════════════════════════════════════════════════════════════════════════
# 2. Protected Rules
# ═════════════════════════════════════════════════════════════════════════════

class TestProtectedRules:
    """Protected rules cannot be modified or deleted via the API."""

    def test_cannot_delete_protected_rule(self, client):
        r = client.delete("/policies/deny-rm", headers=admin_auth())
        assert r.status_code == 403
        assert "protected" in r.json()["detail"].lower()

    def test_cannot_update_protected_rule(self, client):
        r = client.put("/policies/deny-rm", json={
            "id": "deny-rm", "name": "Changed", "result": "allow",
            "priority": 50, "match": {"tool": "Bash", "program": "rm"},
        }, headers=admin_auth())
        assert r.status_code == 403

    def test_protected_rule_visible_in_list(self, client):
        r = client.get("/policies", headers=admin_auth())
        rules = r.json()["policies"]
        protected = [p for p in rules if p.get("protected")]
        assert len(protected) >= 1
        assert any(p["id"] == "deny-rm" for p in protected)


# ═════════════════════════════════════════════════════════════════════════════
# 3. Policy Evaluation (/check)
# ═════════════════════════════════════════════════════════════════════════════

class TestPolicyEvaluation:
    """Rule matching and evaluation logic via /check."""

    def test_deny_rm_for_everyone(self, client):
        """deny-rm rule (priority 50) blocks rm regardless of identity."""
        r = client.post("/check", json={
            "tool": "Bash", "params": {"command": "rm -rf /tmp/foo"},
        }, headers=agent_auth())
        assert r.status_code == 200
        assert r.json()["verdict"] == "deny"

    def test_deny_rm_even_for_admin(self, client):
        """Admin identity should still be denied rm (deny-rm is highest priority)."""
        r = client.post("/check", json={
            "tool": "Bash", "params": {"command": "rm file.txt"},
            "channel_id": "tg:111",  # lew = admin
        }, headers=agent_auth())
        assert r.json()["verdict"] == "deny"

    def test_admin_allowed_ls(self, client):
        """allow-admin-ls (priority 40) lets admin group run ls."""
        r = client.post("/check", json={
            "tool": "Bash", "params": {"command": "ls -la"},
            "channel_id": "tg:111",  # lew = admin
        }, headers=agent_auth())
        assert r.json()["verdict"] == "allow"

    def test_non_admin_denied_ls(self, client):
        """Bob (engineering) has no allow rule for ls — falls through to default deny."""
        r = client.post("/check", json={
            "tool": "Bash", "params": {"command": "ls -la"},
            "channel_id": "tg:333",  # bob = engineering
        }, headers=agent_auth())
        assert r.json()["verdict"] == "deny"

    def test_git_needs_approval(self, client):
        """ask-git rule (priority 30) returns pending verdict."""
        r = client.post("/check", json={
            "tool": "Bash", "params": {"command": "git push origin main"},
        }, headers=agent_auth())
        data = r.json()
        assert data["verdict"] == "pending"
        assert data["approval_id"] is not None

    def test_unknown_tool_denied(self, client):
        """No rule matches an unknown tool — default deny."""
        r = client.post("/check", json={
            "tool": "UnknownTool", "params": {},
        }, headers=agent_auth())
        assert r.json()["verdict"] == "deny"

    def test_anonymous_no_channel_id(self, client):
        """Without channel_id, identity is None — group-scoped rules won't match."""
        r = client.post("/check", json={
            "tool": "Bash", "params": {"command": "ls"},
        }, headers=agent_auth())
        # No channel_id → no identity → admin group rule won't match → deny
        assert r.json()["verdict"] == "deny"

    def test_unknown_channel_id(self, client):
        """A channel_id not in identities should be treated as anonymous."""
        r = client.post("/check", json={
            "tool": "Bash", "params": {"command": "ls"},
            "channel_id": "tg:999999",
        }, headers=agent_auth())
        assert r.json()["verdict"] == "deny"

    def test_priority_ordering(self, client):
        """Higher priority deny-rm (50) beats lower allow-admin-ls (40) for rm."""
        r = client.post("/check", json={
            "tool": "Bash", "params": {"command": "rm important.txt"},
            "channel_id": "tg:222",  # alice = admin
        }, headers=agent_auth())
        assert r.json()["verdict"] == "deny"


# ═════════════════════════════════════════════════════════════════════════════
# 4. Policy Analyzer
# ═════════════════════════════════════════════════════════════════════════════

class TestPolicyAnalyzer:
    """Tier 1 and Tier 2 analysis checks."""

    def test_analyze_endpoint_returns_findings(self, client):
        r = client.get("/policies/analyze", headers=admin_auth())
        assert r.status_code == 200
        data = r.json()
        assert "findings" in data
        assert "summary" in data
        assert isinstance(data["summary"]["total"], int)

    def test_shadow_detection(self, client):
        """Add a broad rule that shadows a narrower one, then check analysis."""
        client.post("/policies", json={
            "id": "test-broad", "name": "Broad", "result": "allow",
            "priority": 60, "match": {"tool": "Bash"},
        }, headers=admin_auth())

        r = client.get("/policies/analyze", headers=admin_auth())
        findings = r.json()["findings"]
        shadow_findings = [f for f in findings if f["check"] == "shadow"]
        assert len(shadow_findings) > 0

        # Cleanup
        client.delete("/policies/test-broad", headers=admin_auth())

    def test_conflict_detection(self, client):
        """Two rules at same priority with overlapping conditions but different results."""
        client.post("/policies", json={
            "id": "conflict-a", "name": "A", "result": "allow",
            "priority": 25, "match": {"tool": "Bash"},
        }, headers=admin_auth())
        client.post("/policies", json={
            "id": "conflict-b", "name": "B", "result": "deny",
            "priority": 25, "match": {"tool": "Bash"},
        }, headers=admin_auth())

        r = client.get("/policies/analyze", headers=admin_auth())
        findings = r.json()["findings"]
        conflict_findings = [f for f in findings if f["check"] == "conflict"]
        assert len(conflict_findings) > 0

        # Cleanup
        client.delete("/policies/conflict-a", headers=admin_auth())
        client.delete("/policies/conflict-b", headers=admin_auth())

    def test_orphan_detection(self, client):
        """A rule referencing a non-existent person produces an orphan warning."""
        client.post("/policies", json={
            "id": "orphan-test", "name": "Orphan", "result": "allow",
            "priority": 10, "match": {"tool": "Bash", "person": "nonexistent"},
        }, headers=admin_auth())

        r = client.get("/policies/analyze", headers=admin_auth())
        findings = r.json()["findings"]
        orphan_findings = [f for f in findings if f["check"] == "orphan" and f["rule_id"] == "orphan-test"]
        assert len(orphan_findings) == 1

        # Cleanup
        client.delete("/policies/orphan-test", headers=admin_auth())

    def test_uncovered_group_detection(self, client):
        """Engineering group has no rules targeting it — should be flagged."""
        r = client.get("/policies/analyze", headers=admin_auth())
        findings = r.json()["findings"]
        uncovered = [f for f in findings if f["check"] == "uncovered" and "engineering" in f["message"]]
        assert len(uncovered) == 1

    def test_unused_rule_detection(self, client):
        """A rule that never matched anything in audit should be flagged as unused."""
        client.post("/policies", json={
            "id": "never-used", "name": "Never", "result": "allow",
            "priority": 5, "match": {"tool": "FakeToolXYZ"},
        }, headers=admin_auth())

        r = client.get("/policies/analyze", headers=admin_auth())
        findings = r.json()["findings"]
        unused = [f for f in findings if f["check"] == "unused" and f["rule_id"] == "never-used"]
        assert len(unused) == 1

        # Cleanup
        client.delete("/policies/never-used", headers=admin_auth())


# ═════════════════════════════════════════════════════════════════════════════
# 5. Approval Flow
# ═════════════════════════════════════════════════════════════════════════════

class TestApprovalFlow:
    """End-to-end pending -> approve/deny flow."""

    def test_pending_creates_approval(self, client):
        """A pending verdict should return an approval_id."""
        r = client.post("/check", json={
            "tool": "Bash", "params": {"command": "git status"},
        }, headers=agent_auth())
        data = r.json()
        assert data["verdict"] == "pending"
        assert data["approval_id"] is not None

    def test_approve_flow(self, client):
        # Create a pending action
        r = client.post("/check", json={
            "tool": "Bash", "params": {"command": "git log"},
        }, headers=agent_auth())
        approval_id = r.json()["approval_id"]

        # Agent can poll the approval status
        r = client.get(f"/approvals/{approval_id}", headers=agent_auth())
        assert r.status_code == 200
        assert r.json()["verdict"] is None  # still pending

        # Admin approves
        r = client.post(f"/approvals/{approval_id}", json={
            "verdict": "allow", "reason": "Looks good",
        }, headers=admin_auth())
        assert r.status_code == 200
        assert r.json()["verdict"] == "allow"

        # Agent polls again — now resolved
        r = client.get(f"/approvals/{approval_id}", headers=agent_auth())
        assert r.json()["verdict"] == "allow"

    def test_deny_flow(self, client):
        r = client.post("/check", json={
            "tool": "Bash", "params": {"command": "git push --force"},
        }, headers=agent_auth())
        approval_id = r.json()["approval_id"]

        r = client.post(f"/approvals/{approval_id}", json={
            "verdict": "deny", "reason": "Not allowed",
        }, headers=admin_auth())
        assert r.status_code == 200
        assert r.json()["verdict"] == "deny"

    def test_cannot_resolve_twice(self, client):
        r = client.post("/check", json={
            "tool": "Bash", "params": {"command": "git diff"},
        }, headers=agent_auth())
        approval_id = r.json()["approval_id"]

        # Resolve once
        client.post(f"/approvals/{approval_id}", json={
            "verdict": "allow",
        }, headers=admin_auth())

        # Try to resolve again — should fail
        r = client.post(f"/approvals/{approval_id}", json={
            "verdict": "deny",
        }, headers=admin_auth())
        assert r.status_code == 404

    def test_invalid_verdict_rejected(self, client):
        r = client.post("/check", json={
            "tool": "Bash", "params": {"command": "git stash"},
        }, headers=agent_auth())
        approval_id = r.json()["approval_id"]

        r = client.post(f"/approvals/{approval_id}", json={
            "verdict": "maybe",
        }, headers=admin_auth())
        assert r.status_code == 400

    def test_approval_stores_subject_id(self, client):
        """When channel_id is provided, subject_id should be stored on the approval."""
        r = client.post("/check", json={
            "tool": "Bash", "params": {"command": "git commit"},
            "channel_id": "tg:333",  # bob
        }, headers=agent_auth())
        approval_id = r.json()["approval_id"]

        r = client.get(f"/approvals/{approval_id}", headers=agent_auth())
        assert r.json()["subject_id"] == "bob"

    def test_list_approvals_requires_admin(self, client):
        r = client.get("/approvals", headers=agent_auth())
        assert r.status_code == 401

    def test_list_approvals_pending_only(self, client):
        r = client.get("/approvals?pending_only=true", headers=admin_auth())
        assert r.status_code == 200
        for a in r.json()["approvals"]:
            assert a["verdict"] is None

    def test_nonexistent_approval_404(self, client):
        r = client.get("/approvals/nonexistent-id", headers=agent_auth())
        assert r.status_code == 404


# ═════════════════════════════════════════════════════════════════════════════
# 6. Audit Trail
# ═════════════════════════════════════════════════════════════════════════════

class TestAuditTrail:
    """Audit log records every /check call."""

    def test_audit_records_check(self, client):
        """A /check call should appear in the audit log."""
        client.post("/check", json={
            "tool": "Bash", "params": {"command": "echo hello"},
        }, headers=agent_auth())

        r = client.get("/audit", headers=admin_auth())
        assert r.status_code == 200
        entries = r.json()["entries"]
        assert len(entries) > 0
        latest = entries[0]
        assert latest["tool"] == "Bash"

    def test_audit_includes_subject_id(self, client):
        """When channel_id resolves to a person, subject_id is logged."""
        client.post("/check", json={
            "tool": "Bash", "params": {"command": "ls"},
            "channel_id": "tg:111",  # lew
        }, headers=agent_auth())

        r = client.get("/audit", headers=admin_auth())
        latest = r.json()["entries"][0]
        assert latest["subject_id"] == "lew"

    def test_audit_includes_approval_id(self, client):
        """Pending verdicts should have approval_id in the audit entry."""
        check_r = client.post("/check", json={
            "tool": "Bash", "params": {"command": "git remote -v"},
        }, headers=agent_auth())
        approval_id = check_r.json()["approval_id"]

        r = client.get("/audit", headers=admin_auth())
        latest = r.json()["entries"][0]
        assert latest["approval_id"] == approval_id

    def test_audit_requires_admin(self, client):
        r = client.get("/audit", headers=agent_auth())
        assert r.status_code == 401

    def test_audit_limit_param(self, client):
        r = client.get("/audit?limit=2", headers=admin_auth())
        assert r.status_code == 200
        assert len(r.json()["entries"]) <= 2


# ═════════════════════════════════════════════════════════════════════════════
# 7. Policy CRUD
# ═════════════════════════════════════════════════════════════════════════════

class TestPolicyCRUD:
    """Create, read, update, delete policy rules."""

    def test_list_policies(self, client):
        r = client.get("/policies", headers=admin_auth())
        assert r.status_code == 200
        policies = r.json()["policies"]
        assert isinstance(policies, list)
        assert len(policies) >= 3  # deny-rm, allow-admin-ls, ask-git

    def test_add_rule(self, client):
        r = client.post("/policies", json={
            "id": "test-add", "name": "Test Add", "description": "Test rule",
            "result": "deny", "priority": 10, "match": {"tool": "TestTool"},
        }, headers=admin_auth())
        assert r.status_code == 201
        assert r.json()["id"] == "test-add"

        # Verify it's in the list
        r = client.get("/policies", headers=admin_auth())
        ids = [p["id"] for p in r.json()["policies"]]
        assert "test-add" in ids

        # Cleanup
        client.delete("/policies/test-add", headers=admin_auth())

    def test_add_duplicate_rule_fails(self, client):
        client.post("/policies", json={
            "id": "test-dup", "name": "Dup", "result": "deny",
            "priority": 10, "match": {},
        }, headers=admin_auth())

        r = client.post("/policies", json={
            "id": "test-dup", "name": "Dup Again", "result": "allow",
            "priority": 20, "match": {},
        }, headers=admin_auth())
        assert r.status_code == 409

        # Cleanup
        client.delete("/policies/test-dup", headers=admin_auth())

    def test_update_rule(self, client):
        # Create
        client.post("/policies", json={
            "id": "test-upd", "name": "Before", "result": "deny",
            "priority": 10, "match": {"tool": "Bash"},
        }, headers=admin_auth())

        # Update
        r = client.put("/policies/test-upd", json={
            "id": "test-upd", "name": "After", "result": "allow",
            "priority": 15, "match": {"tool": "Bash"},
        }, headers=admin_auth())
        assert r.status_code == 200
        assert r.json()["result"] == "allow"
        assert r.json()["priority"] == 15

        # Cleanup
        client.delete("/policies/test-upd", headers=admin_auth())

    def test_update_nonexistent_rule_404(self, client):
        r = client.put("/policies/no-such-rule", json={
            "id": "no-such-rule", "name": "X", "result": "deny",
            "priority": 1, "match": {},
        }, headers=admin_auth())
        assert r.status_code == 404

    def test_delete_rule(self, client):
        client.post("/policies", json={
            "id": "test-del", "name": "Delete Me", "result": "deny",
            "priority": 1, "match": {},
        }, headers=admin_auth())

        r = client.delete("/policies/test-del", headers=admin_auth())
        assert r.status_code == 204

        # Verify it's gone
        r = client.get("/policies", headers=admin_auth())
        ids = [p["id"] for p in r.json()["policies"]]
        assert "test-del" not in ids

    def test_delete_nonexistent_rule_404(self, client):
        r = client.delete("/policies/no-such-rule", headers=admin_auth())
        assert r.status_code == 404

    def test_add_returns_warnings(self, client):
        """Adding conflicting rules should return inline warnings."""
        client.post("/policies", json={
            "id": "warn-a", "name": "A", "result": "allow",
            "priority": 99, "match": {"tool": "Bash"},
        }, headers=admin_auth())
        r = client.post("/policies", json={
            "id": "warn-b", "name": "B", "result": "deny",
            "priority": 99, "match": {"tool": "Bash"},
        }, headers=admin_auth())
        data = r.json()
        assert "warnings" in data
        assert len(data["warnings"]) > 0

        # Cleanup
        client.delete("/policies/warn-a", headers=admin_auth())
        client.delete("/policies/warn-b", headers=admin_auth())

    def test_non_admin_cannot_add_rule(self, client):
        r = client.post("/policies", json={
            "id": "bob-rule", "name": "Bob", "result": "allow",
            "priority": 1, "match": {},
        }, headers=person_auth(BOB_TOKEN))
        assert r.status_code == 403

    def test_non_admin_cannot_delete_rule(self, client):
        r = client.delete("/policies/allow-admin-ls", headers=person_auth(BOB_TOKEN))
        assert r.status_code == 403

    def test_reload_policies(self, client):
        r = client.post("/policies/reload", headers=admin_auth())
        assert r.status_code == 200
        assert "reloaded" in r.json()


# ═════════════════════════════════════════════════════════════════════════════
# 8. Identities
# ═════════════════════════════════════════════════════════════════════════════

class TestIdentities:
    """Identity store endpoints."""

    def test_list_identities(self, client):
        r = client.get("/identities", headers=admin_auth())
        assert r.status_code == 200
        people = r.json()["people"]
        assert len(people) == 3
        ids = {p["id"] for p in people}
        assert ids == {"lew", "alice", "bob"}

    def test_identities_requires_admin(self, client):
        r = client.get("/identities", headers=person_auth(BOB_TOKEN))
        assert r.status_code == 403

    def test_reload_identities(self, client):
        r = client.post("/identities/reload", headers=admin_auth())
        assert r.status_code == 200
        assert "reloaded" in r.json()

    def test_identity_groups_correct(self, client):
        r = client.get("/identities", headers=admin_auth())
        people = {p["id"]: p for p in r.json()["people"]}
        assert "admin" in people["lew"]["groups"]
        assert "admin" in people["alice"]["groups"]
        assert "engineering" in people["bob"]["groups"]
        assert "admin" not in people["bob"]["groups"]
