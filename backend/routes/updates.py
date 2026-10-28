"""Company updates."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from core import P, admin_user, all_user_ids, current_user, db, new_id, notify, now_iso

router = APIRouter(prefix="/api")


class UpdateIn(BaseModel):
    title: str
    body: str
    pinned: bool = False


@router.get("/updates")
async def list_updates(user=Depends(current_user)):
    return await db.updates.find({}, P).sort([("pinned", -1), ("created_at", -1)]).to_list(200)


@router.post("/updates")
async def create_update(body: UpdateIn, admin=Depends(admin_user)):
    if not body.title.strip():
        raise HTTPException(400, "Title is required")
    doc = {"update_id": new_id("upd"), "title": body.title.strip(), "body": body.body.strip(),
           "pinned": body.pinned, "author_id": admin["user_id"], "author_name": admin["name"],
           "created_at": now_iso()}
    await db.updates.insert_one(dict(doc))
    await notify(await all_user_ids(admin["user_id"]), "update", "Company update", doc["title"], "/updates")
    return doc


@router.delete("/updates/{update_id}")
async def delete_update(update_id: str, admin=Depends(admin_user)):
    res = await db.updates.delete_one({"update_id": update_id})
    if not res.deleted_count:
        raise HTTPException(404, "Update not found")
    return {"ok": True}
