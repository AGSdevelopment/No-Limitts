"""In-app notifications."""
from fastapi import APIRouter, Depends
from core import P, current_user, db

router = APIRouter(prefix="/api")


@router.get("/notifications")
async def list_notifications(user=Depends(current_user)):
    return await db.notifications.find({"user_id": user["user_id"]}, P).sort("created_at", -1).to_list(200)


@router.post("/notifications/read-all")
async def read_all(user=Depends(current_user)):
    await db.notifications.update_many({"user_id": user["user_id"], "read": False}, {"$set": {"read": True}})
    return {"ok": True}


@router.post("/notifications/{nid}/read")
async def read_one(nid: str, user=Depends(current_user)):
    await db.notifications.update_one({"notification_id": nid, "user_id": user["user_id"]}, {"$set": {"read": True}})
    return {"ok": True}
