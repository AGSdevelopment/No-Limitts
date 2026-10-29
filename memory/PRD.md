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
- FastAPI + MongoDB. Backend split (Jun 2026): server.py (app, seeds, startup), core.py (db, auth deps, notify, shared helpers), routes/*.py one router per area (auth, users, notifications, certificates, chat, updates, policies, compliance, events, tasks, dashboard, drive, gchat, forms, socials, cpd, ai, digest). Emergent Object Storage (storage.py) for certificate files, Emergent managed email (email_service.py)
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

- Weekly policy reminders: policy_reminder_loop Monday 9am Perth (meta policy_remind_<y>_<w>), one in-app + email per person listing pending policies
- Compliance dashboard (/compliance, admin, Library → Admin): GET /api/compliance → per staff pending policies, expired/expiring certs, CPD hours this year + summary stats; filters & search

- Compliance export: GET /api/compliance/export?token= (admin) → .xlsx (Staff compliance + Summary sheets, openpyxl); Export button in Compliance header
- New Starter checklist (/starter-checklist): New Starter-category forms visible to user (manual tick, db.checklist_progress), all policies acknowledged (auto), ≥1 certificate (auto); GET /api/starter-checklist, POST /api/starter-checklist/{form:<id>}; Home card + Library row for new_starter_* groups; compliance shows Starter x/y badge

## Backlog
- P0: Add Google Drive OAuth credentials and connect
- P1: Phone push notifications (Firebase file + build)
- P1: Camera capture for certificates; date picker
- P2: attachments in chat; real-time websockets; short-lived file tokens

## Jun 2026 updates
- Backend split into core.py + routes/*.py (no behaviour change)
- Compliance: staff with zero certificates flagged (no_certs, needs attention, Excel + stat)
- Starter checklist: only New Starter groups can tick (403 otherwise)
- Checklist completion: one-time in-app + email alert to all admins (test accounts only alert hidden test admins, no email)
- Old stale backend tests removed; tests/test_iter17*, test_iter18* remain
- Pronathi removed from staff (startup remove_staff migration + seed file)
- Required certificates per staff group (/cert-requirements), missing flagged on compliance + export + starter checklist
- Admin "Remind staff" certificate reminder (in-app + email, preview count first)
- Starter progress view /starter/[id] for admins, with check-in booking (private event, notify starter) and cancel
- Pronathi re-added: admin + Support Office (restore_staff one-time migration)
- Check-in notes & outcome (admin-only; hidden from staff in /events and dashboard)
- Monthly certificate reminders: first Monday 9am Perth (cert_reminder_loop, atomic monthly claim)
- Google Calendar invites per admin (routes/calendar.py, calendar.events scope); needs Calendar API enabled + redirect URI .../api/integrations/google-calendar/callback in Google Cloud
- Expiry warnings mention "required for your role" for required certificates
- Staff profile (/staff/[id], GET /api/staff/{id}/profile): certs, CPD, policies, check-ins, starter progress
- "Follow-up needed" check-in outcome -> one shared task (starter + admin) due in 7 days (Perth date, atomic once)
- Reminder history (/reminder-history, db.cert_reminder_log)
- Welcome email + in-app note when someone is put into a New Starter group (once, atomic)
- Probation tracker (12 months default, editable; admin reminder 14 days before), Starter buddy (3 standard tasks), Profile one-page PDF, Compliance filters by group/CPD band
- Upload screen: also share to CPD Resources (Course/Webinar/Case Study/Resource link) and/or Therapist/Participant Resources Drive folders
- Events: any staff can create (purpose, food & drink option, conditions); RSVP Going/Maybe/Can't go with a comment visible to all; event detail /event/[id]; organiser/admin delete
- Upload screen "Resource to share (no expiry)" mode -> POST /api/resources/upload (CPD Resources / Drive folders / My CPD)
- Event reminders day before 9am Perth to Going/Maybe (in-app + email), event photos (attendees/organiser/admin), Add to calendar (Google link + .ics), Past events tab
- Event chat comments, Home "Event photos" highlights (dashboard.photo_highlights), recurring events (weekly/fortnightly/monthly, 2-12, series delete), capacity + waitlist with auto-promotion
- Edit events (PATCH, notifies responders, capacity change promotes waitlist), date/venue polls with lock-in, photo likes & comments, attendance ticking (profile shows events attended)
- AGTS favourites (/places, button on Company Drive): kinds Eat & Drink / Coffee / WiFi-Meet; admins add/remove, all like; Friday lunch random picker
- Company Drive directories (/directory): Therapist (Suppliers, Templates, Trusted Referral Partner Organisations), Participants (Suppliers, Activities, Resources); entries with contact/link/notes + file attachments (object storage); admin-only add/edit/remove; Drive header 'Add' (Therapist / Participant / AGTS Favourite)
- Directory extras: 1–5 star ratings + short review comments (≤300) on Suppliers/Activities (sorted by rating); 'Share to chat' on Referral Partners, Suppliers & Activities posts to one channel (default #Allied Health, settings key referral_share_channel, admin can change); Referral Partner fields: Company name, Services offered, Phone, Website, Email, Location/postcode; Home 'New templates & resources' (last 14 days); confirm sheet before removing a favourite; admins can edit favourites
- Staff can suggest Trusted Referral Partners (status pending, admins notified; admin Approve/Reject inline; suggester notified on approval); postcode filter on referral list (same / ±10 / ±50 / all nearest-first); Home 'Fresh recommendations' (latest written reviews, 30 days); Activities 'Make it a team event' prefills /event-new
- Staff can also suggest Suppliers & Activities (pending approval like referrals)
- Activities 'Start a team vote': tick 2–6 activities → POST /api/events/activity-vote creates event (date_tbd provisional date, poll kind 'activity'); locking sets title + location
- Poll closing date (poll.closes_on, optional on date/venue/activity polls): poll_close_loop (10 min) sends a one-off 'Last chance to vote' notification (after 9am Perth, the day before / closing day) to staff who haven't voted (poll.reminded flag), and auto-locks the leading option after that day (ties → first listed; no votes → organiser notified, deadline cleared); poll.auto_locked flag
- Referral map honours the Same/Nearby/Wider chips (radius param, postcode-number distance); each pin popup has 'Get directions' (Google Maps directions URL; native WebView opens external links via Linking)
- External dashboards (db.dashboards: name, url, roles, groups; /api/dashboards returns URL only to allowed users): 'Therapist dashboard' (Wix page) admins-only, shown in Library → Resources and as a Home shortcut card (home-dashboard-{id}), embedded via iframe/WebView at /dashboard/[id]
- Referral Partners map (List/Map toggle): backend HTML page /api/referral-map using free OpenStreetMap (Leaflet tiles) + Nominatim geocoding (1 req/s, cached in db.geocache and entry.geo; geocoded on add/edit), iframe on web / WebView on native
- Weekly Company Drive digest email (Mondays 8am Perth): new Templates/Resources + top-rated Suppliers; admin preview on Integrations
- Emerging Therapist Pathway (/pathway): 9 supervision steps + self-set CPD goals; admin sees it on staff profile
- Places on Events: favourite place chips for event location + venue poll options
- Participation leaderboard (/leaderboard): admins + Support Office
- Emerging Therapist staff group (emerging_therapist) added; admins choose which forms it sees
- Upload: CPD Resources type is required (button disabled + hint) when "Add to CPD Resources" is on
- Polls: no relock, no replacing open poll, voters tracked by user id; photo like notifies once; edit can't move event into the past
- AGTS Therapist Performance Dashboard (admins): user's own engine (backend/assets/therapist-dashboard.html, unchanged logic, all 9 tabs) served at /api/agts-dashboard/engine with phone-first CSS (sticky pill tabs, 2-col tiles, tables → stacked cards via JS labeler); wrapper /api/agts-dashboard/app relays the engine's Wix postMessage protocol (ready/shared-data/save/saved/shared-error) to /api/agts-dashboard/data|save. Storage: Wix CMS collection TherapistDashboard via Wix Data REST v2 when WIX_API_KEY + WIX_SITE_ID set (so website & app share data), else Mongo agts_dashboard_parts. dashboards doc has embed:'agts'.
- Engine gets an extra 'Plans & safety' tab (#v-nk, Nikki's participants; data in preview part PREV.nikki); separate dashboard entry 'participant-plans' (embed agts-nk → engine?view=nk shows only that view)
- dashboard_loop (hourly, agts_dashboard.py): Friday ≥9am Perth upload reminder to admins (skipped if preview part updated since Thursday; meta key agts_upload_reminder_{date}); below-hours-target alerts (same maths as statsFor: 4-wk hrs/wk < 90% target, not new starters) once per therapist per window end (meta agts_hours_alert_{key}_{E})
- Therapist own plans pages (view=nk + _plans_tag): every "Nikki's participants" wording (incl. JS-escaped, subtitle, export) becomes "my participants"; template edits go through _inject(), which logs an error if an anchor is missing instead of failing silently
- Plan expiry calendar (nkCal in therapist-dashboard.html, inside Plans & safety view): month grid Mon–Sun, red dot plan end, amber dot review due, dated chip list, ‹ › / Today nav; chip selects participant and scrolls to its card
- Therapist pages are view-only: /data sends only that tag's active clients + their forms (own_participants), /save returns 403, uploads/settings hidden. Test page doc dashboards 'plans-test' (users [user_testemp001], tag "Saraya's Clients")
- Plans alerts also cover missing / not completed / out-of-date risk assessments AND personal emergency plans (once per participant per page)
- Review booked tick (db.plan_reviews_booked key "name|end"): POST /api/agts-dashboard/review-booked; booked reviews drop from overdue chips/tiles/alerts/email/calendar; shared across all pages for that participant
- Monday 8am Perth plans email per page owner (send_plans_emails); test: POST /api/agts-dashboard/plans-email/test?page=
- Google Calendar sync (any user can connect; db.plan_cal_events): all-day "Plan ends"/"Plan review due" events, hourly + POST /api/agts-dashboard/calendar-sync; native bar on plans pages (plan-calendar-bar.tsx)
- Booked review date (review_date on plan_reviews_booked): date input on participant card, green dot on plan calendar, "Reviews booked this month" in email, "Plan review booked" Google Calendar event
- Team plans overview (/plans-overview, admin Home card; GET /api/agts-dashboard/team-overview): per-therapist overdue reviews (rev<today, plan not ending ≤30d, not booked), due ≤30d, ending ≤30d, booked, forms; pages with test:true excluded. Admins can open any agts-nk page directly (dashboards.allowed home=False) but Home list shows only shared pages
- Team plans overview PDF: GET /api/agts-dashboard/team-overview/pdf?token= (admins; pymupdf Story, multi-page A4); "PDF for team meeting" button on /plans-overview
- Monthly team plans report email: first Monday 8am+ Perth (meta agts_team_report_YYYY-MM) to all real admins (excl. @example.com); body = totals + per-therapist table + 14-day HMAC-signed PDF link (exp+sig, key WEBHOOK_ENCRYPTION_KEY); "Email it to me" button → POST /api/agts-dashboard/team-overview/email-me
- Executive user type (users.executive): seeded once for nikki@, andrew@, pronathi@ (+ hidden test admin) and auto-set on login for EXECUTIVE_EMAILS (core.py). Only Executives see Therapist dashboard + Participant plans & safety (dashboards.executive_only), Team plans overview (+PDF, email-me), monthly report and dashboard alerts. Therapists keep their own private "My participant plans" pages. Executives can toggle "Make/Remove Executive" on Team screen (PATCH /api/users/{id}/executive)







- Participant plans & safety is shared only with Nikki (dashboards.users via user_emails; allowed() checks users); 'Plans & safety' tab only injected in view=nk; nk data endpoint returns only preview.nikki (no billing/pay); nk save merges only the nikki key into preview. nikki_plan_alerts (hourly in dashboard_loop): plan end within 0–30 days for clients tagged cfg.tag → notify Nikki once per client+end (meta agts_plan_end_*)
- Private plans pages per therapist: sync_plan_pages creates dashboards 'plans-<name>' (embed agts-nk, tag "<Name>'s Clients", users=[matching StaffHub user by unique first name]) from tags in the uploaded client list; engine/data/save take ?page=<dashboard_id>; tag override applied on read, Nikki's cfg.tag preserved on save. plan_alerts (hourly): plan ending ≤30 days, plan review overdue (end − cfg.months ≤ today, plan >30 days left), completed risk assessment older than cfg.formAge months → page owner, once per participant+date

## Rebrand (Jun 2026)
- No Limitts logo (from EPS) for login, app icon, splash, favicon
- Palette: purple #673E8D (primary), pink #EB3F7F (accent), orange #F7A51D, background #FCFEFF, yellow #EBE837 (highlight)
- App name StaffHub -> No Limitts; email/PDF headings use the purple
