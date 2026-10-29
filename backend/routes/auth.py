"""Sign-in sessions (Emergent Google login)."""
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import httpx
import os
from core import EXECUTIVE_EMAILS, P, bearer, current_user, db, new_id, now, now_iso

router = APIRouter(prefix="/api")


class SessionIn(BaseModel):
    session_id: str


@router.post("/auth/session")
async def auth_session(body: SessionIn):
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get("https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                        headers={"X-Session-ID": body.session_id})
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session")
    data = r.json()
    email = data["email"].strip().lower()
    admin_emails = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
    existing = await db.users.find_one({"email": email}, P)
    if existing:
        upd = {"name": data.get("name") or existing["name"], "picture": data.get("picture")}
        if email.lower() in admin_emails:
            upd["role"] = "admin"
        if email in EXECUTIVE_EMAILS and "executive" not in existing:  # first sign-in only; later changes made on Team stick
            upd["executive"] = True
        await db.users.update_one({"email": email}, {"$set": upd})
        user_id = existing["user_id"]
    else:
        is_first = await db.users.count_documents({"email": {"$not": {"$regex": "@example\\.com$"}}}) == 0
        user_id = new_id("user")
        await db.users.insert_one({"user_id": user_id, "email": email, "name": data.get("name") or email,
                                   "picture": data.get("picture"),
                                   "role": "admin" if (is_first or email.lower() in admin_emails) else "employee",
                                   "executive": email in EXECUTIVE_EMAILS,
                                   "job_title": "", "created_at": now_iso()})
    token = data["session_token"]
    await db.user_sessions.insert_one({"session_token": token, "user_id": user_id,
                                       "expires_at": now() + timedelta(days=7), "created_at": now()})
    user = await db.users.find_one({"user_id": user_id}, P)
    return {"session_token": token, "user": user}


@router.get("/auth/me")
async def auth_me(user=Depends(current_user)):
    return user


@router.post("/auth/logout")
async def logout(request: Request):
    token = bearer(request)
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    return {"ok": True}
