"""Admin staff profile: certificates, CPD, policies, check-ins and starter progress on one page."""
from fastapi import APIRouter, Depends, HTTPException
from core import P, admin_user, db
from routes.certificates import missing_required, requirements, with_status
from routes.compliance import NEW_STARTER_GROUPS, starter_checklist
from routes.cpd import cpd_year_start

router = APIRouter(prefix="/api")


@router.get("/staff/{user_id}/profile")
async def staff_profile(user_id: str, admin=Depends(admin_user)):
    u = await db.users.find_one({"user_id": user_id}, P)
    if not u:
        raise HTTPException(404, "Staff member not found")
    certs = [with_status(c) for c in await db.certificates.find(
        {"owner_id": user_id, "is_deleted": {"$ne": True}}, P).sort("expiry_date", 1).to_list(500)]
    year_start = cpd_year_start()
    cpd = await db.cpd_logs.find({"user_id": user_id}, {"_id": 0, "log_id": 1, "title": 1, "type": 1, "hours": 1,
                                                        "date": 1}).sort("date", -1).to_list(500)
    policies = await db.policies.find({}, {"_id": 0, "policy_id": 1, "title": 1, "acknowledged_by": 1,
                                           "version": 1}).sort("title", 1).to_list(1000)
    checkins = await db.events.find({"checkin_for": user_id}, {"_id": 0, "attendees": 0}).sort("date", -1).to_list(100)
    starter = None
    if u.get("staff_group") in NEW_STARTER_GROUPS:
        items = await starter_checklist(u)
        starter = {"done": sum(i["done"] for i in items), "total": len(items)}
    return {
        "user": {k: u.get(k) for k in ("user_id", "name", "email", "picture", "role", "staff_group", "created_at")},
        "certificates": certs,
        "missing_required": missing_required(certs, (await requirements()).get(u.get("staff_group") or "", [])),
        "cpd": {"year_hours": round(sum(c["hours"] for c in cpd if c["date"] >= year_start), 2),
                "year": int(year_start[:4]), "logs": cpd[:20], "total_logs": len(cpd)},
        "policies": [{"policy_id": p["policy_id"], "title": p["title"],
                      "acknowledged": user_id in (p.get("acknowledged_by") or [])} for p in policies],
        "checkins": checkins, "starter": starter,
        "open_tasks": await db.tasks.count_documents({"assignee_id": user_id, "status": "open"}),
    }
