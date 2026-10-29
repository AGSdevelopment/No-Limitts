"""Jotform forms with staff-group access."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from core import FULL_ACCESS_TYPES, P, admin_user, all_user_ids, current_user, db, new_id, notify, now_iso

router = APIRouter(prefix="/api")


class FormIn(BaseModel):
    title: str
    url: str
    description: str = ""
    audiences: List[str] = []
    category: str = "Day-to-Day"


class FormPatch(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    audiences: Optional[List[str]] = None
    category: Optional[str] = None


FORM_CATEGORIES = ("Operations", "Day-to-Day", "HR", "Participant Management & Onboarding", "New Starter", "Compliance",
                   "Referral Triage", "Support Office")


def clean_category(value: str) -> str:
    if value not in FORM_CATEGORIES:
        raise HTTPException(400, "Unknown form section")
    return value


STAFF_GROUPS = ("support_office", "hr", "support_coordinator", "support_worker")


def clean_audiences(values: List[str]) -> List[str]:
    if any(v not in STAFF_GROUPS for v in values):
        raise HTTPException(400, "Unknown staff group")
    return sorted(set(values))


def forms_query(user: dict) -> dict:
    if user.get("role") == "admin" or user.get("user_type") in FULL_ACCESS_TYPES:
        return {}
    ors = [{"audiences": {"$size": 0}}, {"audiences": {"$exists": False}}]
    if user.get("staff_group"):
        ors.append({"audiences": user["staff_group"]})
    return {"$or": ors}


def normalize_jotform(url: str) -> Optional[str]:
    url = url.strip()
    if url.isdigit():
        return f"https://form.jotform.com/{url}"
    if not url.startswith("http"):
        url = "https://" + url
    host = (url.split("/")[2] if len(url.split("/")) > 2 else "").lower()
    if not url.startswith("https://") or not (host == "jotform.com" or host.endswith(".jotform.com")):
        return None
    return url


@router.get("/forms")
async def list_forms(user=Depends(current_user)):
    favs = set(user.get("favourite_forms") or [])
    forms = await db.forms.find(forms_query(user), P).sort("created_at", -1).to_list(200)
    return [{**f, "favourite": f["form_id"] in favs} for f in forms]


@router.post("/forms/{form_id}/favourite")
async def toggle_favourite(form_id: str, user=Depends(current_user)):
    if not await db.forms.find_one({"form_id": form_id, **forms_query(user)}):
        raise HTTPException(404, "Form not found")
    on = form_id not in (user.get("favourite_forms") or [])
    await db.users.update_one({"user_id": user["user_id"]},
                              {"$addToSet" if on else "$pull": {"favourite_forms": form_id}})
    return {"favourite": on}


@router.patch("/forms/{form_id}")
async def update_form(form_id: str, body: FormPatch, admin=Depends(admin_user)):
    upd = {}
    if body.title is not None:
        if not body.title.strip():
            raise HTTPException(400, "Title is required")
        upd["title"] = body.title.strip()
    if body.url is not None:
        url = normalize_jotform(body.url)
        if not url:
            raise HTTPException(400, "Paste a Jotform link (e.g. https://form.jotform.com/123...) or form ID")
        upd["url"] = url
    if body.description is not None:
        upd["description"] = body.description.strip()
    if body.audiences is not None:
        upd["audiences"] = clean_audiences(body.audiences)
    if body.category is not None:
        upd["category"] = clean_category(body.category)
    if not upd:
        raise HTTPException(400, "Nothing to update")
    res = await db.forms.update_one({"form_id": form_id}, {"$set": upd})
    if not res.matched_count:
        raise HTTPException(404, "Form not found")
    return await db.forms.find_one({"form_id": form_id}, P)


@router.post("/forms")
async def create_form(body: FormIn, admin=Depends(admin_user)):
    url = normalize_jotform(body.url)
    if not url:
        raise HTTPException(400, "Paste a Jotform link (e.g. https://form.jotform.com/123...) or form ID")
    if not body.title.strip():
        raise HTTPException(400, "Title is required")
    audiences = clean_audiences(body.audiences)
    doc = {"form_id": new_id("form"), "title": body.title.strip(), "description": body.description.strip(),
           "url": url, "audiences": audiences, "category": clean_category(body.category),
           "created_by": admin["name"], "created_at": now_iso()}
    await db.forms.insert_one(dict(doc))
    if audiences:
        users = await db.users.find({"$or": [{"role": "admin"}, {"staff_group": {"$in": audiences}}]},
                                    {"_id": 0, "user_id": 1}).to_list(5000)
        recipients = [u["user_id"] for u in users if u["user_id"] != admin["user_id"]]
    else:
        recipients = await all_user_ids(admin["user_id"])
    await notify(recipients, "form", "New form available", doc["title"], "/forms")
    return doc


@router.delete("/forms/{form_id}")
async def delete_form(form_id: str, admin=Depends(admin_user)):
    res = await db.forms.delete_one({"form_id": form_id})
    if not res.deleted_count:
        raise HTTPException(404, "Form not found")
    return {"ok": True}
