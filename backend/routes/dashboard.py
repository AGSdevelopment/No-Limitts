"""Home screen summary."""
import calendar
from datetime import date, datetime
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from core import DIGEST_TZ, P, current_user, db
from pdf_brand import LOGO
from routes.certificates import with_status
from routes.events import event_fields, photo_highlights, visible_events

router = APIRouter(prefix="/api")


@router.get("/dashboard")
async def dashboard(user=Depends(current_user)):
    uid = user["user_id"]
    certs = [with_status(c) for c in await db.certificates.find({"owner_id": uid, "is_deleted": False}, P)
             .to_list(1000)]
    alerts = sorted([c for c in certs if c["status"] != "valid"], key=lambda c: c["expiry_date"])
    today = date.today().isoformat()
    events = await db.events.find({"date": {"$gte": today}, **visible_events(user)},
                                  {**event_fields(user), "attendees": 0}).sort("date", 1).to_list(3)
    tasks = await db.tasks.find({"assignee_id": uid, "status": "open"}, P).to_list(100)
    tasks.sort(key=lambda t: t.get("due_date") or "9999")
    updates = await db.updates.find({"source": {"$exists": False}}, P).sort([("pinned", -1), ("created_at", -1)]).to_list(3)
    unread = await db.notifications.count_documents({"user_id": uid, "read": False})
    pending_policies = await db.policies.count_documents({"acknowledged_by": {"$ne": uid}})
    latest_social = await db.updates.find_one({"source": {"$in": ["facebook", "instagram", "linkedin"]}}, P,
                                              sort=[("created_at", -1)])
    return {"cert_alerts": alerts, "cert_total": len(certs), "events": events, "open_tasks": tasks[:5],
            "photo_highlights": await photo_highlights(user),
            "open_task_count": len(tasks), "updates": updates, "unread_notifications": unread,
            "pending_policies": pending_policies, "latest_social": latest_social,
            "celebrations": await celebrations(user)}


async def celebrations(user: dict) -> list:
    """Today's birthdays (MM-DD set by admins) and work anniversaries (start date, 1+ years), Perth time.
    29 Feb birthdays are celebrated on 28 Feb in non-leap years."""
    t = datetime.now(DIGEST_TZ).date()
    md = t.strftime("%m-%d")
    mds = [md] + (["02-29"] if md == "02-28" and not calendar.isleap(t.year) else [])
    q = {} if user.get("hidden") else {"hidden": {"$ne": True}}
    out = []
    async for u in db.users.find({**q, "$or": [{"birthday": {"$in": mds}}, {"start_date": {"$regex": f"-({'|'.join(mds)})$"}}]},
                                 {"_id": 0, "user_id": 1, "name": 1, "picture": 1, "birthday": 1, "start_date": 1}):
        base = {"user_id": u["user_id"], "name": u.get("name", ""), "picture": u.get("picture")}
        if u.get("birthday") in mds:
            out.append({**base, "type": "birthday"})
        sd = u.get("start_date") or ""
        if sd[5:] in mds and sd[:4].isdigit() and int(sd[:4]) < t.year:
            out.append({**base, "type": "anniversary", "years": t.year - int(sd[:4])})
    return out


@router.get("/brand/logo.png")
async def brand_logo():
    """Public logo for email headers."""
    return FileResponse(LOGO, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
