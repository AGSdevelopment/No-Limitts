# StaffHub — PRD

## Original problem statement
Build a mobile app for employees to chat, monitor and upload training certificates including notifications of expiry dates, policies & procedures, company updates, events and tasks.

## User choices
- Emergent-managed Google Sign-In (first user becomes admin)
- Only admins/managers post policies, updates, events, assign tasks
- Chat: team channels (#general company-wide, #announcements) + direct messages
- Expiry reminders: in-app + email (phone push deferred: needs Firebase google-services.json + published build)
- Warning starts 30 days before expiry

## Architecture
- Expo Router app (tabs: Home, Chat, Certificates, Library + stack screens), React Query, sage-green light theme
- FastAPI + MongoDB (server.py), Emergent Object Storage (storage.py) for certificate files, Emergent managed email (email_service.py)
- Background expiry checker every 6h + on upload; notifies once per stage (expiring, expired)

## Implemented (2026-06)
- Google login, roles (admin/employee), team directory with role toggle
- Chat channels + DMs (3s polling), unread counts
- Certificate upload (PDF/image), status badges, admin team-wide view, open file, delete
- Company updates (pin), policies & procedures with acknowledgement, events with RSVP, tasks assign/complete
- Notifications center + badges; expiry emails
- Tested: 15/15 backend tests, full frontend flows passed

## Integrations (added 2026-06)
- Google Chat: one-way mirror of channel messages to a Google Chat space via admin-pasted webhook (encrypted at rest)
- Google Drive: admin OAuth connect (backend-owned refresh token, encrypted); certificates copied to "StaffHub Certificates" folder; Drive file attach on policies. Needs GOOGLE_DRIVE_CLIENT_ID / GOOGLE_DRIVE_CLIENT_SECRET (pending from user); redirect URI = PUBLIC_BACKEND_URL + /api/integrations/google-drive/callback
- Jotform: admins add form links; employees open with name/email prefilled
- Claude (claude-sonnet-5-5, Emergent key): streaming policy Q&A assistant; certificate auto-fill from image/PDF
- Tested: iteration 2 — 30/30 backend, frontend flows pass

## Chat updates (2026-06)
- #general renamed to "Allied Health" (linked to Google Chat space spaces/AAAALAwOw8Y); new channel "Celebrate the Wins"
- Two-way Google Chat: backend polls Chat API (chat.messages.readonly, user OAuth) every 10s for channels with two-way on; skips BOT (webhook) messages to avoid echo; dedupe by gchat_name
- Google OAuth env now GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET (shared by Drive + Chat). Chat redirect: PUBLIC_BACKEND_URL/api/integrations/google-chat/callback

## Drive folder + Chat summaries (2026-06)
- Company Drive: admin pastes a Drive folder link in Integrations; all staff browse it (subfolders, search) from Library → Company Drive; files streamed via backend (Google Docs exported as PDF), access restricted to items under the chosen folder
- Claude chat summaries: "Summarise" button in every chat thread → bottom sheet summary of last 200 messages

## Round 3 (2026-06)
- Claude reads Company Drive docs: background index every 4h (+ on folder set / admin "Refresh now"); Docs/Sheets/Slides/PDF/text → db.drive_docs; keyword-ranked top docs (≤50k chars) added to assistant context
- Weekly chat digest: Monday 8am Australia/Perth, email to all users (team channels only, Claude summary per channel); admin "Email me a preview" (POST /api/digest/test); dedupe via meta digest_<year>_<week>
- Camera certificates: "Take a photo" → camera (pre-permission sheet, Open Settings fallback) → auto Claude fill
- Pinned Drive files: admin pin/unpin (db.drive_pins), Pinned section at top of Company Drive root

## Round 4 (2026-06)
- Drive AI fix: docs/pins cleared when shared folder cleared/changed; AI context filtered by current root + full file list
- Socials tab (Instagram/Facebook/LinkedIn links + latest posts). Meta Graph v26 (FB Page + linked IG) and LinkedIn Posts API (r_organization_social) admin OAuth; poll every 15 min, new posts → Company Updates (+notify). Needs META_APP_ID/SECRET, LINKEDIN_CLIENT_ID/SECRET. Redirects: PUBLIC_BACKEND_URL/api/integrations/{meta|linkedin}/callback
- Tasks: anyone creates private tasks (only visible to them); admins assign to one person or Everyone (copy per user); delete own tasks
- CPD (Library): personal log with yearly hours, shared resources (admin), team hours (admin)
- Test users Alex Admin / Erin Employee hidden (hidden flag) from /users
- Team directory: 27 staff imported from contacts.csv (company_seed.json staff_v2, one-time meta company_staff_v2) with staff groups

## Round 5 (2026-06)
- CPD certificates: attach PDF/photo to CPD log → Claude fills title/provider/date/hours/type (POST /api/cpd/extract); file stored (/api/cpd/{id}/file)
- Home "Latest from our socials" highlight (dashboard.latest_social); social posts excluded from Home updates list
- CPD Resources grouped into Courses / Webinars / Resource Links; staff can share a CPD log (+document) to the library (POST /api/cpd/{id}/share); contributors or admins delete
- Upload Certificate: "Count towards my CPD hours" + hours → creates linked CPD log with certificate as evidence
- Company Drive: two sections Therapist Resources / Participants Resources (integration.spaces.{therapist,participant}); APIs take ?space=; AI index covers both

## Round 6 (2026-06)
- Forms: 6 Week Check-in + 3/6/12 Month Review → Everyone; new "Task Creation & Management" (Support Office, support_office only) via one-time migrate_forms_v3 + company_seed.json
- New staff groups: new_starter_employee, new_starter_contractor (backend STAFF_GROUPS + src/groups.ts)
- Tasks: optional file attachment (POST /api/tasks/attachments → attachment_id on POST /api/tasks; GET /api/tasks/files/{id}?token=)
- Fixes: cert delete removes linked CPD log; upload-certificate back fallback; CPD share failure toast; Drive section labels shortened

## Round 7 (2026-06)
- CPD: "Case Studies" resources section + "Case Study" log type
- Library Resources order: Notifications, Company updates, My tasks, Forms, CPD, Events, Policies, Team directory (then Company Drive, Ask AI)
- All date inputs DD-MM-YYYY (ui.tsx dmyDate/isoToDmy/dmyToIso; API still ISO)
- Certificate "count towards CPD" logs with today's date so it adds to this year's total
- Tasks: admin multi-select people (assignee_ids) → each copy has collaborators[]; shown "Working on this with …" + notification "with …"

## Round 8 (2026-06)
- Task progress: admin "All assigned" groups shared tasks (group_id) into one row with progress bar "x of n done" + per-person status/completed_at; DELETE /api/tasks/group/{group_id}; PATCH sets completed_at
- CPD library resources: delete is admin-only
- Pending from user: Therapist/Participants Drive folder links (skipped), LinkedIn keys (skipped)

- CPD entries editable: tap entry or pencil → Edit CPD sheet prefilled (PATCH /api/cpd/{id}, owner only); can replace certificate; AI-filled fields editable before save

- CPD Report PDF: GET /api/cpd/report?year=&token= (summary table + evidence pages via pymupdf); button on My CPD total card
- Task reminders: hourly loop, shared (group) open tasks due tomorrow (Perth) → in-app + email once (reminder_sent)

- Drive setup: ensure_drive_setup() (runs in index_drive, once per DB when Drive connected, meta drive_setup_v1) sets Therapist (1AkYaS…) / Participants (1_Bu1oe…) folders and imports policies from folder 1jfsRbz… (27 PDFs; skips "All Published" compilations); POST /api/policies/import-drive {link}; GET /api/policies/{id}/file proxies the Drive file
- Library: Ask AI placed below Policies & procedures

- Policy versions: POST /api/policies/{id}/version (multipart: file PDF/Word → object storage, change_note, content; PDF text auto-extracted) → version+1, previous kept in versions[], acknowledged_by reset to admin, staff notified to re-acknowledge
- Acknowledgement tracker: GET /api/policies/{id}/acks (acknowledged/pending, hidden users excluded), POST /api/policies/{id}/remind (in-app + email to pending); UI in src/components/policy-admin.tsx on policy detail (admin buttons)

## Backlog
- P0: Add Google Drive OAuth credentials and connect
- P1: Phone push notifications (Firebase file + build)
- P1: Camera capture for certificates; date picker
- P2: Compliance export report; attachments in chat; real-time websockets; short-lived file tokens
