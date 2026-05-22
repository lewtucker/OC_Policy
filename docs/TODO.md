# TODO

Running list of issues, ideas, and things to remember. Not necessarily actionable now.

---

- [ ] Approval queue is in-memory only — pending approvals are lost on policy server restart. Needs persistence (SQLite or Redis).
- [ ] Nanoclaw container caches agent-runner source per group — changes to the policy hook are silently ignored until cache is manually cleared. Automate cache invalidation on deploy.
- [ ] No hook exists for intercepting outbound agent messages — agent can leak sensitive data in response text. Monitor as Claude Code hook system evolves.
- [ ] No ACP (Agent Communication Protocol) hooks — inter-agent task messages are invisible to policy. Document as known risk.
- [ ] Shell env `TELEGRAM_BOT_TOKEN` overrides nanoclaw `.env` — caused wrong bot to connect. Consider making nanoclaw prefer `.env` or warn on mismatch.
- [ ] Improve container build of OpenClaw and installation process.
