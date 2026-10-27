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

## Backlog
- P0: Add Google Drive OAuth credentials and connect
- P1: Phone push notifications (Firebase file + build)
- P1: Camera capture for certificates; date picker
- P2: Compliance export report; attachments in chat; real-time websockets; short-lived file tokens
