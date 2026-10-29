"""Staff directory, roles and staff groups."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from core import P, admin_user, current_user, db, executive_user, spawn
from routes.forms import STAFF_GROUPS

router = APIRouter(prefix="/api")


@router.get("/users")
async def list_users(user=Depends(current_user)):
    return await db.users.find({"hidden": {"$ne": True}}, P).sort("name", 1).to_list(1000)


class RoleIn(BaseModel):
    role: str


class StaffGroupIn(BaseModel):
    staff_group: Optional[str] = None


@router.patch("/users/{user_id}/group")
async def set_staff_group(user_id: str, body: StaffGroupIn, admin=Depends(admin_user)):
    if body.staff_group is not None and body.staff_group not in STAFF_GROUPS:
        raise HTTPException(400, "Unknown staff group")
    res = await db.users.update_one({"user_id": user_id}, {"$set": {"staff_group": body.staff_group}})
    if not res.matched_count:
        raise HTTPException(404, "User not found")
    from routes.compliance import send_starter_welcome  # local import avoids a circular import
    spawn(send_starter_welcome(user_id))
    return await db.users.find_one({"user_id": user_id}, P)


@router.patch("/users/{user_id}/role")
async def set_role(user_id: str, body: RoleIn, admin=Depends(admin_user)):
    if body.role not in ("admin", "employee"):
        raise HTTPException(400, "Invalid role")
    if user_id == admin["user_id"] and body.role != "admin":
        raise HTTPException(400, "You cannot remove your own admin role")
    res = await db.users.update_one({"user_id": user_id}, {"$set": {"role": body.role}})
    if not res.matched_count:
        raise HTTPException(404, "User not found")
    return await db.users.find_one({"user_id": user_id}, P)



class ExecutiveIn(BaseModel):
    executive: bool


@router.patch("/users/{user_id}/executive")
async def set_executive(user_id: str, body: ExecutiveIn, exe=Depends(executive_user)):
    """Executive user type (Therapist dashboard, Participant plans & safety, Team plans overview). Only Executives can change it."""
    if user_id == exe["user_id"] and not body.executive:
        raise HTTPException(400, "You cannot remove your own Executive access")
    res = await db.users.update_one({"user_id": user_id}, {"$set": {"executive": body.executive}})
    if not res.matched_count:
        raise HTTPException(404, "User not found")
    return await db.users.find_one({"user_id": user_id}, P)
