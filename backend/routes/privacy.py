"""No Limitts app privacy policy. Public (no sign-in) so it can be linked from Login and the app store listings;
admins can edit the wording in the app."""
from html import escape
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from core import admin_user, db, now_iso

router = APIRouter(prefix="/api")

DEFAULT_POLICY = """## About this policy
This policy explains how the No Limitts staff app ("the app") collects, uses, stores and protects personal information. The app is for No Limitts employees and contractors only. We handle personal information in line with the Privacy Act 1988 (Cth), the Australian Privacy Principles and our obligations as a registered NDIS provider.

## Information we collect
Staff information: your name, work email, phone number, job title, staff group, start date, birthday (if you add it), profile photo and sign-in details.
Training and compliance: certificates you upload (such as NDIS Worker Screening, First Aid and CPR), their expiry dates, CPD records and onboarding checklist progress.
Work activity: messages, event RSVPs, comments, tasks, and acknowledgements of policies and shift handovers.
Participant information: for staff who support participants, the app shows participant names, profile details (goals, support needs, communication, health alerts and key contacts) and case notes submitted through our Jotform forms.

## How we use it
We use this information to run the app and support our people. That includes:
- keeping training and compliance up to date and reminding you before certificates expire
- sharing company updates, policies, events and tasks
- helping Support Workers and Coordinators provide safe, consistent support to participants
- meeting our legal and NDIS Quality and Safeguards obligations.
Some features use AI to summarise case notes or read certificate details. This information is processed only to provide that feature and is not used to train AI models.

## Who can see it
Access is based on your role. Only admins can see staff email addresses and phone numbers. Support Workers only see participants they are assigned to, and only Support Worker case notes. Coordinators, HR and admins can see participant information they need for their role.
We do not sell personal information. We share it only with service providers that help run the app (such as Microsoft for sign-in and Teams, Jotform for forms, cloud hosting and email delivery), or where the law requires it.

## Storage and security
Information is stored on secure cloud servers and sent over encrypted connections. Sign-in is protected by Microsoft accounts or individual passwords. Private links to participant documents expire after 7 days. We keep information only for as long as we need it for work, legal or NDIS record-keeping purposes.

## Your choices and rights
You can view and update your own profile in the app at any time. You can ask to access or correct the personal information we hold about you, or ask questions about this policy, by contacting your manager or the No Limitts admin team. If you are not satisfied with our response, you can contact the Office of the Australian Information Commissioner (oaic.gov.au).

## Participants
Participant information is collected and managed under No Limitts' participant privacy and consent processes. Participants and their representatives can contact their Service Coordinator to access or correct their information.

## Changes to this policy
We may update this policy from time to time. The latest version is always available in the app and at this page."""


async def current() -> dict:
    doc = await db.meta.find_one({"key": "privacy_policy"}, {"_id": 0})
    return {"text": (doc or {}).get("text") or DEFAULT_POLICY, "updated_at": (doc or {}).get("updated_at", "")}


@router.get("/privacy")
async def get_privacy():
    return await current()


@router.get("/privacy/page", response_class=HTMLResponse)
async def privacy_page():
    """Web version for the App Store / Google Play privacy policy URL."""
    doc = await current()
    parts = []
    for block in doc["text"].split("\n"):
        line = block.strip()
        if not line:
            continue
        if line.startswith("## "):
            parts.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.startswith("- "):
            parts.append(f"<li>{escape(line[2:])}</li>")
        else:
            parts.append(f"<p>{escape(line)}</p>")
    body = "".join(parts)
    return HTMLResponse(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>No Limitts app privacy policy</title><style>body{font-family:Arial,sans-serif;max-width:760px;margin:0 auto;padding:24px;"
        "color:#11181C;line-height:1.55}h1{color:#673E8D}h2{color:#673E8D;font-size:18px;margin-top:28px}li{margin-left:20px}</style></head>"
        f"<body><h1>No Limitts app privacy policy</h1>{body}</body></html>")


class PolicyIn(BaseModel):
    text: str


@router.put("/privacy")
async def save_privacy(body: PolicyIn, user=Depends(admin_user)):
    text = body.text.strip()[:30000]
    await db.meta.update_one({"key": "privacy_policy"},
                             {"$set": {"key": "privacy_policy", "text": text, "updated_at": now_iso(),
                                       "updated_by": user.get("name") or ""}}, upsert=True)
    return await current()
