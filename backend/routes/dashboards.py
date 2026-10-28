"""External dashboards shown inside the app. The web address is only sent to people whose role/group is allowed."""
from fastapi import APIRouter, Depends, HTTPException
from core import P, current_user, db, now_iso

router = APIRouter(prefix="/api")

DEFAULTS = [
    {"dashboard_id": "therapist-dashboard", "name": "Therapist dashboard",
     "url": "https://www.aspireandgrowtherapyservices.com.au/therapist-dashboard", "roles": ["admin"], "groups": [],
     "embed": "agts"},
    {"dashboard_id": "participant-plans", "name": "Participant plans & safety",
     "url": "https://www.aspireandgrowtherapyservices.com.au/therapist-dashboard", "roles": [], "groups": [],
     "embed": "agts-nk", "user_emails": ["nikki@aspireandgrow.com.au"]},
]


async def ensure_dashboards():
    for d in DEFAULTS:
        emails = d.pop("user_emails", None)
        if not await db.dashboards.find_one({"dashboard_id": d["dashboard_id"]}):
            await db.dashboards.insert_one({**d, "created_at": now_iso()})
        else:
            await db.dashboards.update_one({"dashboard_id": d["dashboard_id"]}, {"$set": {"embed": d.get("embed", "")}})
        if emails is not None:  # shared with named people only
            users = await db.users.find({"email": {"$in": emails}}, {"_id": 0, "user_id": 1}).to_list(20)
            await db.dashboards.update_one({"dashboard_id": d["dashboard_id"]},
                                           {"$set": {"roles": [], "users": [u["user_id"] for u in users]}})


def allowed(d: dict, user: dict) -> bool:
    return (user.get("role") in d.get("roles", []) or (user.get("staff_group") or "") in d.get("groups", [])
            or user.get("user_id") in d.get("users", []))


def out(d: dict) -> dict:
    return {"dashboard_id": d["dashboard_id"], "name": d["name"], "url": d["url"], "embed": d.get("embed", "")}


@router.get("/dashboards")
async def list_dashboards(user=Depends(current_user)):
    docs = await db.dashboards.find({}, P).sort("name", 1).to_list(50)
    return [out(d) for d in docs if allowed(d, user)]


@router.get("/dashboards/{dashboard_id}")
async def get_dashboard(dashboard_id: str, user=Depends(current_user)):
    d = await db.dashboards.find_one({"dashboard_id": dashboard_id}, P)
    if not d or not allowed(d, user):
        raise HTTPException(404, "Dashboard not found")
    return out(d)
