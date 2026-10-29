"""Staff directory and user types (Executive, Admin, Support Office, Support Worker)."""
import re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from core import P, USER_P, USER_TYPES, admin_user, current_user, db, new_id, now_iso, type_fields
from routes.auth import hash_password, temp_password

router = APIRouter(prefix="/api")


@router.get("/users")
async def list_users(user=Depends(current_user)):
    return await db.users.find({"hidden": {"$ne": True}}, USER_P).sort("name", 1).to_list(1000)


def check_type(t: str, admin: dict):
    if t not in USER_TYPES:
        raise HTTPException(400, "Unknown user type")
    if t == "executive" and admin.get("user_type") != "executive":
        raise HTTPException(403, "Only Executives can create or change Executives")


async def issue_password(user_id: str) -> str:
    pw = temp_password()
    await db.users.update_one({"user_id": user_id}, {"$set": {"password_hash": hash_password(pw), "must_change_password": True,
                                                               "failed_logins": 0}, "$unset": {"locked_until": ""}})
    await db.user_sessions.delete_many({"user_id": user_id})
    return pw


class NewUserIn(BaseModel):
    name: str
    email: str
    user_type: str
    job_title: str = ""


@router.post("/users")
async def add_user(body: NewUserIn, admin=Depends(admin_user)):
    """Add a staff member. Support Workers get a temporary password (shown once) to pass on."""
    check_type(body.user_type, admin)
    email, name = body.email.strip().lower(), body.name.strip()
    if not name or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "Enter a name and a valid email")
    if await db.users.find_one({"email": email}):
        raise HTTPException(409, "Someone with that email is already in the app")
    uid = new_id("user")
    await db.users.insert_one({"user_id": uid, "email": email, "name": name, "picture": None,
                               "job_title": body.job_title.strip(), "created_at": now_iso(), **type_fields(body.user_type)})
    pw = await issue_password(uid) if body.user_type == "support_worker" else None
    return {"user": await db.users.find_one({"user_id": uid}, USER_P), "temporary_password": pw}


class TypeIn(BaseModel):
    user_type: str


@router.patch("/users/{user_id}/type")
async def set_type(user_id: str, body: TypeIn, admin=Depends(admin_user)):
    check_type(body.user_type, admin)
    if user_id == admin["user_id"]:
        raise HTTPException(400, "You can't change your own user type")
    target = await db.users.find_one({"user_id": user_id}, P)
    if not target:
        raise HTTPException(404, "User not found")
    if target.get("user_type") == "executive" and admin.get("user_type") != "executive":
        raise HTTPException(403, "Only Executives can change an Executive")
    upd = {"$set": type_fields(body.user_type)}
    if body.user_type != "support_worker":  # office staff use Microsoft only
        upd["$unset"] = {"password_hash": "", "must_change_password": ""}
    await db.users.update_one({"user_id": user_id}, upd)
    res = {"user": await db.users.find_one({"user_id": user_id}, USER_P), "temporary_password": None}
    if body.user_type == "support_worker" and not target.get("password_hash"):
        res["temporary_password"] = await issue_password(user_id)
    return res


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: str, admin=Depends(admin_user)):
    target = await db.users.find_one({"user_id": user_id}, P)
    if not target:
        raise HTTPException(404, "User not found")
    if target.get("user_type") != "support_worker":
        raise HTTPException(400, "Only Support Workers have app passwords; office staff use Microsoft")
    return {"temporary_password": await issue_password(user_id)}


@router.delete("/users/{user_id}")
async def remove_user(user_id: str, admin=Depends(admin_user)):
    target = await db.users.find_one({"user_id": user_id}, P)
    if not target or target.get("hidden"):
        raise HTTPException(404, "User not found")
    if user_id == admin["user_id"]:
        raise HTTPException(400, "You can't remove yourself")
    if target.get("user_type") == "executive" and admin.get("user_type") != "executive":
        raise HTTPException(403, "Only Executives can remove an Executive")
    await db.users.delete_one({"user_id": user_id})
    await db.user_sessions.delete_many({"user_id": user_id})
    return {"ok": True}
