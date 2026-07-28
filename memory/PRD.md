# M365 Migration Suite — PRD

## Original Problem Statement
> "We have office 365 tenant so our requirements is to migrate all services to other office 365 tenant so we need a migration tool for tenant to tenant for all office 365 services like exchange email and sharepoint one drive Distribution list and all others office 365 services and migration tool have individual migration services like for every service we need individual option for migration so kindly build the production enterprise application for the specified features"

## User Choices (2026-02-22)
- Migration engine: Production-ready UI + simulated engine (real MS Graph wiring deferred)
- Services: All 9 (Exchange, SharePoint, OneDrive, Distribution Lists, Teams, M365 Groups, Contacts, Calendars, Public Folders)
- Auth: JWT-based custom auth
- Scope: Multi-tenant support (many projects)
- Design: Distinctive dark enterprise "command center" aesthetic

## Personas
- **IT Administrator** — configures tenants, kicks off migrations
- **MSP Operator** — manages multiple client migration projects
- **Compliance Reviewer** — reads audit logs

## Architecture
- Backend: FastAPI + Motor (async MongoDB), JWT auth, background tasks orchestrate simulated migration
- Frontend: React 19 + React Router 7, TailwindCSS, Shadcn UI overridden to sharp/dark aesthetic, IBM Plex Mono/Sans + Cabinet Grotesk, Phosphor icons
- Storage: MongoDB collections — users, projects, jobs, logs

## Implemented (2026-02-22)
- Admin seed (`admin@migratetool.com` / `Admin@12345`)
- Auth: register, login, logout, `/auth/me` (JWT + cookie + bearer fallback)
- Projects CRUD + connection test
- Discovery endpoint for each of 9 services with deterministic mock data
- Job lifecycle: create → run (background) → progress → complete, with pause / resume / cancel / retry-failed
- Live log stream per job
- Dashboard with real-time telemetry, per-service breakdown, recent jobs
- Sidebar navigation with all service modules
- Job Queue + Audit Log views
- Settings screen
- 29/29 backend pytest suite passing; full frontend flow verified

## Implemented (2026-02-22 iter 2)
- Microsoft Graph adapter (`graph_adapter.py`) — MSAL app-only client credentials,
  per-tenant token cache, tenacity retry on 429/503 with Retry-After honoring
- Automatic simulated-mode fallback when tenant credentials are absent
- Concurrent job runner with `asyncio.Semaphore` — per-job concurrency (1-10)
- Pre-flight endpoint (`/projects/{id}/preflight`) — connectivity + license +
  storage headroom checks with pass/warn/fail semantics
- Notification pipeline — Resend, SendGrid, and generic webhooks, configured
  per project via `notification_settings`; PUT `/projects/{id}/notifications`
- Report exports — CSV and PDF per completed job (`/jobs/{id}/report.csv|pdf`)
- Front-end additions: preflight modal, concurrency selector, live/simulated
  mode badge on discovery, CSV/PDF download buttons in Job Detail
- 42/42 backend pytest passing (29 iter1 + 13 iter2)

## Implemented (2026-02-22 iter 6)
- Real per-service content migration via Microsoft Graph API (`graph_migrations.py`)
- Live-mode dispatcher in `graph_adapter.migrate_item` delegates to service-specific
  functions once BOTH tenants have valid credentials
- Per-service coverage:
  - Exchange: user provisioning + mail folder tree + messages (incl. body, recipients,
    from/sender, importance, isRead) + attachments (chunked)
  - Calendars: full event copy (start/end, attendees, recurrence, location, categories)
  - Contacts: personal contacts per user
  - OneDrive: full file tree with chunked upload (4MB threshold, 5MB chunks) via
    createUploadSession
  - M365 Groups: unified group + members + owners
  - Distribution Lists: mail-enabled non-security group + members
  - SharePoint Sites: provision site via Unified group + copy default drive contents
    (folder tree + files, chunked)
  - Teams: create team shell + non-General channels + members
  - Public Folders: structured "not supported by Graph" failure with MRS/3rd-party guidance
- Per-item `stats` (messages_copied, files_copied, bytes, etc.) persisted on
  `items[i].stats`; aggregate numeric stats atomically accumulated in
  `job.aggregate_stats` via a single `$set + $inc` update
- 106/106 backend pytest passing (20 new + 86 regression)

## Implemented (2026-02-22 iter 5)
- Symmetric encryption at rest for all tenant client_secrets via
  `cryptography.Fernet` with an `enc:v1:` prefix
- `CONN_ENCRYPTION_KEY` env var required in production; legacy plaintext
  records still readable (backward-compatible)
- Project GET/list responses no longer include `client_secret`; each tenant
  panel exposes `has_secret: bool` instead
- Live Graph discovery errors now surface as 400 with a readable message
  instead of an uncaught 500
- 86/86 backend pytest passing (29 + 13 + 15 + 14 + 15)

## Implemented (2026-02-22 iter 4)
- Tenant Connections manager in Settings — saved reusable Azure AD credential
  profiles: `POST/GET/PUT/DELETE /api/tenant-connections`, `POST /test`
- Secrets masked in list/get responses; `?reveal=true` for explicit autofill;
  reveal actions written to `audit_logs`
- Projects Create modal has "Load from saved" dropdowns to autofill source
  and destination tenant panels from saved connections
- Settings page lists Azure AD Application permission requirements inline
- 71/71 backend pytest passing (29 + 13 + 15 + 14)

## Implemented (2026-02-22 iter 3)
- Scheduled migrations — cron + one-shot triggers backed by a persistent
  `schedules` collection; asyncio scheduler loop (15s tick) dispatches due
  schedules by creating jobs
- Endpoints: `POST/GET/PUT toggle/DELETE /api/schedules`, `POST /api/schedules/{id}/run-now`
- Checkpointed delta sync — per (project, service) `checkpoints` collection
  tracks per-item last-sync status; discovery annotates items with
  `checkpoint_status` (never|success|failed); `mode='incremental'` skips
  already-successful items; `mode='delta'` processes only 'never' items
- Front-end additions: dedicated Schedules page (create modal with cron
  presets + one-shot picker + item chooser), checkpoint banner + hide-synced
  toggle + reset-checkpoint on service module, Sync column per row
- 57/57 backend pytest passing (29 + 13 + 15)

## Backlog (P0 / P1 / P2)
- **P0** — Real Microsoft Graph API integration (per-service): OAuth 2.0 client credentials flow, delegated permissions, mailbox export/import via Graph, SharePoint site provisioning, OneDrive file transfer using upload sessions, group/DL recreation
- **P1** — Delta / incremental sync with checkpoint tracking; scheduled migrations; concurrency throttling with retry-backoff on 429s
- **P1** — Report export (CSV/PDF) per project
- **P2** — Role management UI (operator vs. admin), team collaboration
- **P2** — Webhook / email notifications on job completion
- **P2** — Pre-flight validation (license checks, licenses, storage quotas at destination)

## Next Tasks
1. Wire real Microsoft Graph SDK once source + destination tenant app registrations are provided
2. Add per-service migration adapter pattern (`ExchangeAdapter`, `SharePointAdapter`, etc.) to swap simulation → real API without touching orchestrator
3. Persist mapping rules (source user → destination user) for merger scenarios
