"""Emerging Therapist Pathway: supervision checklist + self-set CPD goals."""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from core import P, admin_user, current_user, db, new_id, now_iso

router = APIRouter(prefix="/api")

SUPERVISION_STEPS = [
    ("meet_supervisor", "Meet your clinical supervisor", "Introduce yourself and swap contact details"),
    ("supervision_plan", "Agree your supervision plan", "Set how often you'll meet and what you'll focus on"),
    ("first_session", "Complete your first supervision session", ""),
    ("shadow_senior", "Shadow a senior therapist", "Observe at least one session with an experienced therapist"),
    ("case_presentation", "Present your first case in supervision", ""),
    ("review_3m", "3-month supervision review", "Check progress against your goals with your supervisor"),
    ("independent_session", "Run a session independently", "With your supervisor's sign-off"),
    ("review_6m", "6-month supervision review", ""),
    ("review_12m", "12-month review & pathway sign-off", "Celebrate your first year!"),
]
STEP_KEYS = {k for k, _, _ in SUPERVISION_STEPS}


class GoalIn(BaseModel):
    title: str
    due: str = ""
    notes: str = ""


class GoalEditIn(BaseModel):
    title: str | None = None
    due: str | None = None
    notes: str | None = None
    done: bool | None = None


def is_emerging(user: dict) -> bool:
    return user.get("staff_group") == "emerging_therapist"


async def pathway_for(uid: str) -> dict:
    doc = await db.pathways.find_one({"user_id": uid}, P) or {}
    ticks = doc.get("steps") or {}
    steps = [{"key": k, "title": t, "description": d, "done": k in ticks, "done_at": ticks.get(k)}
             for k, t, d in SUPERVISION_STEPS]
    goals = await db.cpd_goals.find({"user_id": uid}, P).sort([("done", 1), ("due", 1)]).to_list(200)
    year = f"{date.today().year}-01-01"
    logs = await db.cpd_logs.find({"user_id": uid, "date": {"$gte": year}}, {"_id": 0, "hours": 1}).to_list(2000)
    return {"steps": steps, "steps_done": len(ticks), "steps_total": len(SUPERVISION_STEPS), "goals": goals,
            "goals_done": sum(1 for g in goals if g.get("done")), "cpd_year_hours": round(sum(lg["hours"] for lg in logs), 2)}


def require_emerging(user: dict):
    if not is_emerging(user):
        raise HTTPException(403, "The pathway is for Emerging Therapists")


@router.get("/pathway")
async def my_pathway(user=Depends(current_user)):
    require_emerging(user)
    return await pathway_for(user["user_id"])


@router.get("/pathway/user/{user_id}")
async def staff_pathway(user_id: str, admin=Depends(admin_user)):
    if not await db.users.find_one({"user_id": user_id, "staff_group": "emerging_therapist"}):
        raise HTTPException(404, "Not an Emerging Therapist")
    return await pathway_for(user_id)


@router.post("/pathway/steps/{key}")
async def toggle_step(key: str, user=Depends(current_user)):
    require_emerging(user)
    if key not in STEP_KEYS:
        raise HTTPException(404, "Step not found")
    doc = await db.pathways.find_one({"user_id": user["user_id"]}, P) or {}
    done = key in (doc.get("steps") or {})
    upd = {"$unset": {f"steps.{key}": ""}} if done else {"$set": {f"steps.{key}": now_iso()}}
    await db.pathways.update_one({"user_id": user["user_id"]}, upd, upsert=True)
    return {"done": not done}


def clean_due(due: str) -> str:
    due = (due or "").strip()
    if due:
        try:
            date.fromisoformat(due)
        except ValueError:
            raise HTTPException(400, "Enter the target date as dd-mm-yyyy")
    return due


@router.post("/pathway/goals")
async def add_goal(body: GoalIn, user=Depends(current_user)):
    require_emerging(user)
    title = body.title.strip()[:200]
    if not title:
        raise HTTPException(400, "Describe your goal")
    doc = {"goal_id": new_id("goal"), "user_id": user["user_id"], "title": title, "due": clean_due(body.due),
           "notes": body.notes.strip()[:1000], "done": False, "done_at": None, "created_at": now_iso()}
    await db.cpd_goals.insert_one(dict(doc))
    return doc


@router.patch("/pathway/goals/{goal_id}")
async def edit_goal(goal_id: str, body: GoalEditIn, user=Depends(current_user)):
    require_emerging(user)
    upd = {}
    if body.title is not None:
        if not body.title.strip():
            raise HTTPException(400, "Describe your goal")
        upd["title"] = body.title.strip()[:200]
    if body.due is not None:
        upd["due"] = clean_due(body.due)
    if body.notes is not None:
        upd["notes"] = body.notes.strip()[:1000]
    if body.done is not None:
        upd.update({"done": body.done, "done_at": now_iso() if body.done else None})
    res = await db.cpd_goals.update_one({"goal_id": goal_id, "user_id": user["user_id"]}, {"$set": upd})
    if not res.matched_count:
        raise HTTPException(404, "Goal not found")
    return await db.cpd_goals.find_one({"goal_id": goal_id}, P)


@router.delete("/pathway/goals/{goal_id}")
async def delete_goal(goal_id: str, user=Depends(current_user)):
    require_emerging(user)
    if not (await db.cpd_goals.delete_one({"goal_id": goal_id, "user_id": user["user_id"]})).deleted_count:
        raise HTTPException(404, "Goal not found")
    return {"ok": True}
