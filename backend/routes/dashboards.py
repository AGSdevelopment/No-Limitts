"""External dashboards shown inside the app. The web address is only sent to people whose role/group is allowed.
Pages marked executive_only (Therapist dashboard, Participant plans & safety) are for Executives only."""
from fastapi import APIRouter, Depends, HTTPException
from core import EXECUTIVE_EMAILS, HIDDEN_TEST_USERS, P, current_user, db, is_executive, now_iso

router = APIRouter(prefix="/api")

DEFAULTS = [
    {"dashboard_id": "therapist-dashboard", "name": "Therapist dashboard",
     "url": "https://www.aspireandgrowtherapyservices.com.au/therapist-dashboard", "roles": [], "groups": [],
     "embed": "agts", "executive_only": True},
    {"dashboard_id": "participant-plans", "name": "Participant plans & safety",
     "url": "https://www.aspireandgrowtherapyservices.com.au/therapist-dashboard", "roles": [], "groups": [],
     "embed": "agts-nk", "executive_only": True, "user_emails": ["nikki@aspireandgrow.com.au"]},
]


async def ensure_dashboards():
    # Executive user type: seed the named executives (and the hidden test admin used for QA) once
    if not await db.meta.find_one({"key": "executives_seeded"}):
        await db.users.update_many({"$or": [{"email": {"$in": sorted(EXECUTIVE_EMAILS)}}, {"user_id": HIDDEN_TEST_USERS[0]}]},
                                   {"$set": {"executive": True}})
        await db.meta.insert_one({"key": "executives_seeded", "created_at": now_iso()})
    for d in DEFAULTS:
        emails = d.pop("user_emails", None)
        if not await db.dashboards.find_one({"dashboard_id": d["dashboard_id"]}):
            await db.dashboards.insert_one({**d, "created_at": now_iso()})
        else:
            await db.dashboards.update_one({"dashboard_id": d["dashboard_id"]},
                                           {"$set": {"embed": d.get("embed", ""), "executive_only": True, "roles": d["roles"]}})
        if emails is not None:  # named owner (gets the plan alerts / emails)
            users = await db.users.find({"email": {"$in": emails}}, {"_id": 0, "user_id": 1}).to_list(20)
            await db.dashboards.update_one({"dashboard_id": d["dashboard_id"]},
                                           {"$set": {"users": [u["user_id"] for u in users]}})


def allowed(d: dict, user: dict, home: bool = False) -> bool:
    """home=True is the Home-screen list: only pages shared with the user. Executives can also open any therapist's
    plans page directly (e.g. from the Team plans overview) without it cluttering their Home."""
    if d.get("executive_only"):
        return is_executive(user)
    if not home and d.get("embed") == "agts-nk" and is_executive(user):
        return True
    return (user.get("role") in d.get("roles", []) or (user.get("staff_group") or "") in d.get("groups", [])
            or user.get("user_id") in d.get("users", []))


def out(d: dict) -> dict:
    return {"dashboard_id": d["dashboard_id"], "name": d["name"], "url": d["url"], "embed": d.get("embed", "")}


@router.get("/dashboards")
async def list_dashboards(user=Depends(current_user)):
    docs = await db.dashboards.find({}, P).sort("name", 1).to_list(50)
    return [out(d) for d in docs if allowed(d, user, home=True)]


@router.get("/dashboards/{dashboard_id}")
async def get_dashboard(dashboard_id: str, user=Depends(current_user)):
    d = await db.dashboards.find_one({"dashboard_id": dashboard_id}, P)
    if not d or not allowed(d, user):
        raise HTTPException(404, "Dashboard not found")
    return out(d)
