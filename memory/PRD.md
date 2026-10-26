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

## Backlog
- P1: Phone push notifications (Firebase file + build)
- P1: Camera capture for certificates; date picker
- P2: Compliance export report; attachments in chat; real-time websockets; short-lived file tokens
