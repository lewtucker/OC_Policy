# OC Policy — Documentation Guide

**Date**: 2026-03-22
**Author(s)**: Lew Tucker

---

## Project

| Document | Description |
| --- | --- |
| [Project_Overview.md](Project_Overview.md) | Top-level summary of the project — what we're building, system architecture, implementation status, and how the approval loop works |
| [Policy_Inst.md](Policy_Inst.md) | Original project brief — the initial intent and goals for the OC Policy app |
| [Status.md](Status.md) | Point-in-time status snapshot of what is working and what is planned next |

## Architecture & Design

| Document | Description |
| --- | --- |
| [OC_Policy_Control_v01.md](OC_Policy_Control_v01.md) | Detailed architecture and design reference — three-layer system, ZPL-inspired identity model, policy language, tamper prevention, and plugin capability declarations |
| [Trust_and_Security_Model_v02.md](Trust_and_Security_Model_v02.md) | Formal security model — governing principles, OCPL policy language, evaluation algorithm, and implementation roadmap *(current version)* |
| [Trust_and_Security_Model_v01.md](Trust_and_Security_Model_v01.md) | Earlier draft of the security model *(superseded by v02)* |
| [Controlling_OpenClaw_Agents_v02.md](Controlling_OpenClaw_Agents_v02.md) | Controlling Open Claw Agents Prototype — identity and plugin trust model, subject types, multi-user team identity, the subject forgery problem, and plugin trust levels |
| [Policy_Examples.md](Policy_Examples.md) | Policy language examples (placeholder — to be filled in) |

## Progress Reports

| Document | Description |
| --- | --- |
| [Progress_Report_v05.md](Progress_Report_v05.md) | Phase 3 security hardening — two-token auth, per-person tokens, protected rules, policy analyzer Tier 1+2, NL chat panel, test script *(current)* |
| [Progress_Report_v04.md](Progress_Report_v04.md) | Phase 3b — identity-aware policies, person/group matching, UI dropdowns, terminology rename |
| [Progress_Report_v03.md](Progress_Report_v03.md) | Phase 3 live integration with Nanoclaw, persistent audit log, and identity model design work |
| [Progress_Report_v02.md](Progress_Report_v02.md) | Phases 1, 2, and 2.5 — enforcement plugin, policy engine, approvals queue, and audit log |
| [Progress_Report_v01.md](Progress_Report_v01.md) | Phase 1 — initial enforcement proof of concept |

## Plans

| Document | Description |
| --- | --- |
| [Plan_NL_Policy_Authoring_v01.md](Plan_NL_Policy_Authoring_v01.md) | Natural language policy authoring — let users express rules in plain English; Phase 1 as a Claude skill |
| [Plan_Policy_Change_Authorization.md](Plan_Policy_Change_Authorization.md) | Rules and identity on policy changes — per-person tokens, admin-only writes, protected rules, escalation prevention |
| [Plan_Identity_Phase3b.md](Plan_Identity_Phase3b.md) | Identity/person support implementation plan (Phase 3b — complete) |

## Guides

| Document | Description |
| --- | --- |
| [Demo.md](Demo.md) | Five-minute walkthrough of the system without a live OpenClaw instance |
| [Testing_Without_OpenClaw.md](Testing_Without_OpenClaw.md) | Step-by-step guide for running and testing the policy server using the dummy harness |

## Other

| Document | Description |
| --- | --- |
| [Name_Candidates.md](Name_Candidates.md) | Candidate product names under consideration |
