# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**OpenClaw Policy Management App** — A Python web application for reading and writing policy rules that govern OpenClaw (OC), an autonomous agent system. The goal is to let users protect their resources from unintended actions OpenClaw might take.

The reference OpenClaw repository is at `~/Documents/dev/OpenClaw Clone` — consult it to understand how OpenClaw works before designing enforcement mechanisms.

## Core Concepts

**Security model**: Any action OpenClaw takes via shell scripts or network connections must be approved by a security guard before execution. The app enforces this through a policy language that serves as the source of truth for what is allowed or denied.

**Control mechanisms**:

- API key provisioning/revocation
- File system permission changes
- Network connection controls
- System resource access limits
- Shell and Python script execution controls

**Identity model**: Resources, services, and users all have human-readable names and immutable identities.

**Policy operations**: Users can add and delete policies. The policy language defines allow/deny rules scoped to identities and resource types.

## Open Design Questions

- How to intercept and block OpenClaw or its sub-agents from performing specific acts (requires research into OpenClaw's architecture)
- Policy language syntax and schema
- Security guard approval workflow (synchronous blocking vs. async queue)
- UI technology choice (web framework, frontend approach)

## Planning Documents

- [Policy_Inst.md](Policy_Inst.md) — Project brief and feature intent
- [Policy_Examples.md](Policy_Examples.md) — Policy language examples (to be filled in)
- [OC_Policy_Control_v01.md](OC_Policy_Control_v01.md) — Architecture & design document (current)
