"""Participant Groups (Service Coordinators): one group per participant, built from their Support Team, plus members the
coordinator adds (or removes). Each group has a group chat; coordinators send announcements and allocate tasks that every
member must action or acknowledge themselves. Progress is tracked for Compliance."""
import asyncio
from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import P, current_user, db, dmy, logger, new_id, notify, now_iso
from routes.pm_common import is_coordinator, now_perth

router = APIRouter(prefix="/api")
KINDS = {"action": "Action required", "acknowledge": "Please acknowledge"}


async def coordinator(user=Depends(current_user)):
    if not is_coordinator(user):
        raise HTTPException(403, "For Service Coordinators and Admins")
    return user


async def members_of(g: dict) -> list:
    p = await db.participants.find_one({"participant_id": g["participant_id"]}, {"_id": 0, "assigned_ids": 1}) or {}
    ids = [i for i in dict.fromkeys((p.get("assigned_ids") or []) + (g.get("extra_ids") or [])) if i not in (g.get("excluded_ids") or [])]
    users = await db.users.find({"user_id": {"$in": ids}, "hidden": {"$ne": True}}, {"_id": 0, "user_id": 1, "name": 1, "picture": 1}).to_list(500)
    team = set(p.get("assigned_ids") or [])
    return sorted([{**u, "from_team": u["user_id"] in team} for u in users], key=lambda u: u["name"].lower())


async def sync(g: dict) -> list:
    """Keep the group chat's members in step with the Support Team (and coordinator changes)."""
    members = await members_of(g)
    ids = sorted({m["user_id"] for m in members} | set(g.get("manager_ids") or []))
    await db.conversations.update_one({"conversation_id": g["conversation_id"]}, {"$set": {"member_ids": ids, "name": g["name"]}})
    return members


async def group_for(group_id: str, user: dict) -> tuple:
    g = await db.participant_groups.find_one({"group_id": group_id}, P)
    if not g:
        raise HTTPException(404, "Group not found")
    members = await sync(g)
    if not is_coordinator(user) and user["user_id"] not in {m["user_id"] for m in members}:
        raise HTTPException(404, "Group not found")
    return g, members


async def task_progress(group_id: str) -> list:
    today = now_perth().date().isoformat()
    by: dict = {}
    async for t in db.tasks.find({"participant_group_id": group_id}, P).sort("created_at", -1):
        b = by.setdefault(t["group_id"], {"task_group_id": t["group_id"], "title": t["title"], "kind": t.get("kind", "action"),
                                          "description": t.get("description", ""), "due_date": t.get("due_date", ""),
                                          "created_by": t["created_by"], "created_at": t["created_at"], "done": [], "outstanding": []})
        (b["done"] if t["status"] == "done" else b["outstanding"]).append(
            {"user_id": t["assignee_id"], "name": t["assignee_name"], "completed_at": t.get("completed_at")})
    out = []
    for b in by.values():
        b["overdue"] = bool(b["outstanding"]) and bool(b["due_date"]) and b["due_date"] < today
        b["complete"] = not b["outstanding"]
        out.append(b)
    return out


def view(g: dict, members: list, tasks: list) -> dict:
    return {**{k: v for k, v in g.items() if k not in ("extra_ids", "excluded_ids", "manager_ids")}, "members": members,
            "open_tasks": sum(not t["complete"] for t in tasks), "overdue_tasks": sum(t["overdue"] for t in tasks)}


@router.get("/participant-groups")
async def list_groups(user=Depends(current_user)):
    out = []
    async for g in db.participant_groups.find({}, P).sort("participant_name", 1):
        members = await sync(g)
        if is_coordinator(user) or user["user_id"] in {m["user_id"] for m in members}:
            out.append(view(g, members, await task_progress(g["group_id"])))
    return {"groups": out, "can_manage": is_coordinator(user)}


class GroupIn(BaseModel):
    participant_id: str


@router.post("/participant-groups")
async def create_group(body: GroupIn, user=Depends(coordinator)):
    p = await db.participants.find_one({"participant_id": body.participant_id}, P)
    if not p:
        raise HTTPException(404, "Participant not found")
    if await db.participant_groups.find_one({"participant_id": body.participant_id}):
        raise HTTPException(400, f"{p['name']} already has a group")
    conv_id = new_id("conv")
    g = {"group_id": new_id("pgrp"), "participant_id": p["participant_id"], "participant_name": p["name"], "name": f"{p['name']} Support Team",
         "conversation_id": conv_id, "extra_ids": [], "excluded_ids": [], "manager_ids": [user["user_id"]],
         "created_by": user.get("name") or "", "created_at": now_iso()}
    await db.conversations.insert_one({"conversation_id": conv_id, "type": "group", "name": g["name"], "participant_group_id": g["group_id"],
                                       "description": f"Support Team for {p['name']}", "member_ids": [], "last_message": "",
                                       "last_at": "", "created_at": now_iso()})
    await db.participant_groups.insert_one(dict(g))
    members = await sync(g)
    await notify([m["user_id"] for m in members if m["user_id"] != user["user_id"]], "message", f"You've been added to {g['name']}",
                 "Group chat, announcements and tasks for this participant's team.", f"/participant-groups/{g['group_id']}")
    return view(g, members, [])


@router.get("/participant-groups/{group_id}")
async def get_group(group_id: str, user=Depends(current_user)):
    g, members = await group_for(group_id, user)
    tasks = await task_progress(group_id)
    if not is_coordinator(user):  # members see their own progress, not everyone's
        tasks = [{**t, "mine_done": any(d["user_id"] == user["user_id"] for d in t["done"]), "done": [], "outstanding": []} for t in tasks]
    return {**view(g, members, tasks), "tasks": tasks, "can_manage": is_coordinator(user)}


class MembersIn(BaseModel):
    add_ids: List[str] = []
    remove_ids: List[str] = []


@router.put("/participant-groups/{group_id}/members")
async def edit_members(group_id: str, body: MembersIn, user=Depends(coordinator)):
    g, _ = await group_for(group_id, user)
    extra, excluded = set(g.get("extra_ids") or []), set(g.get("excluded_ids") or [])
    if body.add_ids and await db.users.count_documents({"user_id": {"$in": body.add_ids}}) != len(set(body.add_ids)):
        raise HTTPException(404, "Staff member not found")
    for uid in body.add_ids:
        excluded.discard(uid)
        extra.add(uid)
    for uid in body.remove_ids:
        extra.discard(uid)
        excluded.add(uid)
    g.update({"extra_ids": sorted(extra), "excluded_ids": sorted(excluded)})
    await db.participant_groups.update_one({"group_id": group_id}, {"$set": {"extra_ids": g["extra_ids"], "excluded_ids": g["excluded_ids"]}})
    members = await sync(g)
    if body.add_ids:
        await notify([u for u in body.add_ids if u != user["user_id"]], "message", f"You've been added to {g['name']}",
                     "Group chat, announcements and tasks for this participant's team.", f"/participant-groups/{group_id}")
    return view(g, members, await task_progress(group_id))


@router.delete("/participant-groups/{group_id}")
async def delete_group(group_id: str, user=Depends(coordinator)):
    g = await db.participant_groups.find_one({"group_id": group_id}, P)
    if not g:
        raise HTTPException(404, "Group not found")
    await db.participant_groups.delete_one({"group_id": group_id})
    await db.conversations.delete_one({"conversation_id": g["conversation_id"]})
    await db.messages.delete_many({"conversation_id": g["conversation_id"]})
    await db.tasks.delete_many({"participant_group_id": group_id, "status": "open"})
    return {"ok": True}


class AnnounceIn(BaseModel):
    text: str


async def post_to_chat(g: dict, user: dict, text: str):
    msg = {"message_id": new_id("msg"), "conversation_id": g["conversation_id"], "sender_id": user["user_id"], "sender_name": user["name"],
           "sender_picture": user.get("picture"), "text": text[:4000], "created_at": now_iso()}
    await db.messages.insert_one(dict(msg))
    await db.conversations.update_one({"conversation_id": g["conversation_id"]},
                                      {"$set": {"last_message": f"{user['name'].split(' ')[0]}: {text[:80]}", "last_at": msg["created_at"]}})


@router.post("/participant-groups/{group_id}/announce")
async def announce(group_id: str, body: AnnounceIn, user=Depends(coordinator)):
    g, members = await group_for(group_id, user)
    text = body.text.strip()
    if len(text) < 2:
        raise HTTPException(400, "Write the announcement")
    await post_to_chat(g, user, f"📣 Announcement: {text}")
    others = [m["user_id"] for m in members if m["user_id"] != user["user_id"]]
    await notify(others, "message", f"Announcement · {g['name']}", text[:140], f"/chat/{g['conversation_id']}")
    return {"sent_to": len(others)}


class GroupTaskIn(BaseModel):
    title: str
    description: str = ""
    due_date: str = ""  # YYYY-MM-DD
    kind: str = "action"  # action | acknowledge


@router.post("/participant-groups/{group_id}/tasks")
async def allocate_task(group_id: str, body: GroupTaskIn, user=Depends(coordinator)):
    g, members = await group_for(group_id, user)
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "Title is required")
    if body.kind not in KINDS:
        raise HTTPException(400, "Choose action or acknowledge")
    if body.due_date:
        try:
            date.fromisoformat(body.due_date)
        except ValueError:
            raise HTTPException(400, "Due date must be YYYY-MM-DD")
    if not members:
        raise HTTPException(400, "This group has no members yet")
    tgrp = new_id("tgrp")
    team = [{"user_id": m["user_id"], "name": m["name"]} for m in members]
    for m in members:
        await db.tasks.insert_one({"task_id": new_id("task"), "title": title, "description": body.description.strip(), "due_date": body.due_date,
                                   "assignee_id": m["user_id"], "assignee_name": m["name"], "status": "open", "created_by": user["name"],
                                   "created_by_id": user["user_id"], "private": False, "group_id": tgrp, "attachment": None,
                                   "for_everyone": False, "collaborators": [c for c in team if c["user_id"] != m["user_id"]],
                                   "participant_group_id": group_id, "participant_group_name": g["name"], "kind": body.kind,
                                   "created_at": now_iso()})
    await notify([m["user_id"] for m in members if m["user_id"] != user["user_id"]], "task", f"{KINDS[body.kind]} · {g['name']}",
                 title + (f" (due {dmy(body.due_date)})" if body.due_date else ""), "/tasks")
    await post_to_chat(g, user, f"✅ New task for everyone ({KINDS[body.kind].lower()}): {title}. Tick it off in My tasks.")
    return {"task_group_id": tgrp, "assigned": len(members)}


@router.get("/participant-groups-compliance")
async def groups_compliance(user=Depends(coordinator)):
    """Every group's tasks: who has / hasn't actioned or acknowledged (shown in Compliance)."""
    out = []
    async for g in db.participant_groups.find({}, P).sort("participant_name", 1):
        tasks = await task_progress(g["group_id"])
        if tasks:
            out.append({"group_id": g["group_id"], "name": g["name"], "participant_name": g["participant_name"], "tasks": tasks})
    return {"groups": out, "outstanding": sum(len(t["outstanding"]) for g in out for t in g["tasks"]),
            "overdue": sum(t["overdue"] for g in out for t in g["tasks"])}


async def group_sync_loop():
    """Support Teams change elsewhere (tag approvals, caseload assignment): refresh group chat members every 10 minutes."""
    await asyncio.sleep(90)
    while True:
        try:
            async for g in db.participant_groups.find({}, P):
                await sync(g)
        except Exception as e:
            logger.error(f"Participant group sync failed: {type(e).__name__}: {e}")
        await asyncio.sleep(600)
