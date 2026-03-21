# Dueling Bots — Telegram Pairing Issue

**Date**: 2026-03-20

## Problem

Telegram bot (`@LTClaudeBot`) is not sending a pairing code when DM'd.

## What We Found

### Bot is healthy
- Token saved at `~/.claude/channels/telegram/.env` (prefix `<redacted>:...`)
- `getMe` returns OK — bot identity is valid
- No stale webhook registered — `getWebhookInfo` returns empty URL
- `getUpdates` returns empty — the running server **is** consuming updates (DMs are being received)

### Two Claude processes are competing
Both of these are running simultaneously with the Telegram plugin loaded:

```
PID 49046  claude --channels plugin:telegram@claude-plugins-official  (terminal s004)
PID 43691  claude --channels plugin:telegram@claude-plugins-official  (terminal s001)
```

Telegram's long-poll API delivers each update to **only one** polling client. These two processes race for every incoming message. Whichever one wins gets the DM — but no pairing code ever arrives back in Telegram. The other process never sees the message at all.

### Nanoclaw is not the culprit
A nanoclaw Docker container (`nanoclaw-telegram-main`) is also running, but it uses a **different bot token** (`<redacted>:...`). No conflict there.

## Likely Root Cause

The two Claude instances are fighting over updates. One consumes the DM, but the pairing response either silently fails or gets lost in the confused dual-poll state.

## Where We Left It

- Did not yet kill either duplicate process
- Did not yet confirm which terminal session (s004 or s001) is the "active" one
- Next step: kill one of the duplicate Claude-telegram processes, then DM the bot again and watch the surviving session's output for log activity

## Next Steps

1. Kill one of the duplicate processes (probably PID 43691 / s001, keep the most recently active one)
2. DM `@LTClaudeBot` again
3. Watch terminal output — a pairing log line should appear
4. Approve via `/telegram:access pair <code>`
5. Lock down to `allowlist` policy once your ID is in
