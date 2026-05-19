---
name: architecture-v1
description: Phase 1 architecture document covering all backend models, API routes, frontend component tree, database schema, and AI Agent module design
metadata:
  type: reference
---

The complete architecture document is at `docs/architecture.md`. It covers all Phase 1 requirements from PRD v1 (prd-v1.md). Key architectural decisions documented:

- AD-1: One session per patient (long-term memory pattern)
- AD-2: AI supplement auto-updates patient record, no admin review needed
- AD-3: Makeup check-in schedule_id is nullable
- AD-4: Schedule matrix layout with dual-entry view (worker/patient)
- AD-5: Session context = full history + AI auto-summary
- AD-6: Frontend state = AuthContext only, no global store
- AD-7: No refresh token, single access token (24h)
- AD-8: Absent auto-mark at 1 hour after schedule ends

New tables added: schedule_log, absenteeism, patient_version, reminder
Removed from Phase 1: complaint, alert, auto-schedule, adjust-schedule

The existing `backend/ARCHITECTURE.md` and `frontend/ARCHITECTURE.md` are outdated and should be replaced by `docs/architecture.md`.
