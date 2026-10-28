"""AGTS favourites (Eat & Drink, Coffee, WiFi / Meet). Everyone can view and like; admins add and remove."""
import re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from core import P, admin_user, current_user, db, new_id, now_iso

router = APIRouter(prefix="/api")

KINDS = ("Eat & Drink", "Coffee", "WiFi / Meet")


async def migrate_place_kinds():
    """Older Eat / Drink / Eat & drink places all live under Eat & Drink."""
    await db.places.update_many({"kind": {"$nin": list(KINDS)}}, {"$set": {"kind": "Eat & Drink"}})


class PlaceIn(BaseModel):
    name: str
    kind: str = "Eat & Drink"
    address: str = ""
    link: str = ""
    note: str = ""


@router.get("/places")
async def list_places(user=Depends(current_user)):
    docs = await db.places.find({}, P).sort("name", 1).to_list(1000)
    for d in docs:
        d["liked"] = user["user_id"] in (d.get("likes") or [])
        d["like_count"] = len(d.pop("likes", None) or [])
        d["can_delete"] = user["role"] == "admin"
    return docs


@router.post("/places")
async def add_place(body: PlaceIn, user=Depends(admin_user)):
    name = body.name.strip()[:120]
    if not name:
        raise HTTPException(400, "Add the place's name")
    if body.kind not in KINDS:
        raise HTTPException(400, "Choose Eat & Drink, Coffee or WiFi / Meet")
    link = body.link.strip()[:500]
    if link and not link.startswith(("http://", "https://")):
        link = "https://" + link
    if await db.places.find_one({"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}):
        raise HTTPException(409, f"{name} is already on the list")
    doc = {"place_id": new_id("plc"), "name": name, "kind": body.kind, "address": body.address.strip()[:300],
           "link": link, "note": body.note.strip()[:500], "likes": [], "created_by": user["name"],
           "created_by_id": user["user_id"], "created_at": now_iso()}
    await db.places.insert_one(dict(doc))
    doc.pop("_id", None)
    return {**{k: v for k, v in doc.items() if k != "likes"}, "liked": False, "like_count": 0, "can_delete": True}


@router.post("/places/{place_id}/like")
async def like_place(place_id: str, user=Depends(current_user)):
    p = await db.places.find_one({"place_id": place_id}, P)
    if not p:
        raise HTTPException(404, "Place not found")
    liked = user["user_id"] in (p.get("likes") or [])
    await db.places.update_one({"place_id": place_id},
                               {("$pull" if liked else "$addToSet"): {"likes": user["user_id"]}})
    return {"liked": not liked}


@router.delete("/places/{place_id}")
async def delete_place(place_id: str, user=Depends(admin_user)):
    if not (await db.places.delete_one({"place_id": place_id})).deleted_count:
        raise HTTPException(404, "Place not found")
    return {"ok": True}
