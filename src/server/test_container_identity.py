"""
Test that the nanoclaw Docker container passes channel_id (chatJid) to the policy server.

Runs the nanoclaw-agent container with a fake ContainerInput containing chatJid,
points OC_POLICY_SERVER_URL at a local mock server, and verifies that the
/check request body includes channel_id.

Usage:
    cd src/server
    python test_container_identity.py
"""
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

CAPTURED = []

class MockPolicyServer(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress default logging

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        data = json.loads(body)
        CAPTURED.append((self.path, data))
        print(f"  Mock server received POST {self.path}: {json.dumps(data)}")

        # Return a valid response so the container doesn't hang
        if self.path == "/check":
            resp = json.dumps({"verdict": "deny", "reason": "test mock"}).encode()
        else:
            resp = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def do_GET(self):
        resp = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(resp)


def start_mock_server():
    server = HTTPServer(("0.0.0.0", 9999), MockPolicyServer)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


# Minimal ContainerInput that causes the agent to make one tool call then exit.
# We use a prompt that forces a Bash call.
FAKE_INPUT = {
    "prompt": "Run this exact command and nothing else: echo policy_test_marker",
    "sessionId": None,
    "groupFolder": "telegram_main",
    "chatJid": "tg:6741893378",
    "isMain": True,
    "assistantName": "Andy",
}

TIMEOUT = 90  # seconds — agent needs time to start and make a tool call


def run():
    print("=== Container Identity Test ===")
    print(f"  chatJid in input: {FAKE_INPUT['chatJid']}")
    print()

    print("Starting mock policy server on :9999 ...")
    server = start_mock_server()

    print("Running nanoclaw-agent container ...")
    print("  (this may take ~30s for the container to start and make a tool call)")
    print()

    try:
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "--add-host", "host.docker.internal:host-gateway",
                "-e", "OC_POLICY_SERVER_URL=http://host.docker.internal:9999",
                "-e", "OC_POLICY_AGENT_TOKEN=test",
                "-e", "ANTHROPIC_API_KEY=" + __import__("os").environ.get("ANTHROPIC_API_KEY", ""),
                "-i",
                "nanoclaw-agent",
            ],
            input=json.dumps(FAKE_INPUT).encode(),
            capture_output=True,
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        print("  Container timed out — checking captured requests anyway...")
        result = None

    print()
    print(f"Captured {len(CAPTURED)} request(s) to mock server:")
    check_requests = [d for path, d in CAPTURED if path == "/check"]

    if not check_requests:
        print("  FAIL: No /check requests received.")
        print()
        if result:
            stderr = result.stderr.decode(errors="replace")
            if stderr:
                print("Container stderr (last 1000 chars):")
                print(stderr[-1000:])
        sys.exit(1)

    print()
    all_passed = True
    for i, req in enumerate(check_requests, 1):
        channel_id = req.get("channel_id")
        tool = req.get("tool", "?")
        print(f"  Request {i}: tool={tool!r}  channel_id={channel_id!r}")
        if channel_id == FAKE_INPUT["chatJid"]:
            print(f"    PASS: channel_id matches chatJid")
        elif channel_id is None:
            print(f"    FAIL: channel_id is None — chatJid not being passed")
            all_passed = False
        else:
            print(f"    FAIL: unexpected channel_id value")
            all_passed = False

    print()
    if all_passed:
        print("ALL TESTS PASSED")
    else:
        print("TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    run()
