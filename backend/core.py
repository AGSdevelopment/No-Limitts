from datetime import datetime, timezone
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from html import escape
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo
import asyncio
import logging
import os
import re
import uuid

ROOT_DIR = Path(__file__).parent


load_dotenv(ROOT_DIR / '.env')


mongo_url = os.environ['MONGO_URL']


client = AsyncIOMotorClient(mongo_url)


db = client[os.environ['DB_NAME']]


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


logger = logging.getLogger(__name__)


EXPIRY_WARNING_DAYS = 30


MAX_UPLOAD_BYTES = 15 * 1024 * 1024


P = {"_id": 0}
USER_P = {"_id": 0, "password_hash": 0, "failed_logins": 0, "locked_until": 0}


def now():
    return datetime.now(timezone.utc)


def now_iso():
    return now().isoformat()


def dmy(iso: str) -> str:
    """yyyy-mm-dd -> dd-mm-yyyy for anything staff read (notifications, emails)."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else (iso or "")


def new_id(prefix: str):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


_bg_tasks = set()


def spawn(coro):
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)


async def user_from_token(token: Optional[str]):
    if not token:
        return None
    sess = await db.user_sessions.find_one({"session_token": token}, P)
    if not sess:
        return None
    exp = sess["expires_at"]
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now():
        return None
    return await db.users.find_one({"user_id": sess["user_id"]}, USER_P)


def bearer(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    return auth[7:] if auth.startswith("Bearer ") else None


async def current_user(request: Request):
    user = await user_from_token(bearer(request))
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user.get("must_change_password") and request.url.path not in PASSWORD_CHANGE_PATHS:
        raise HTTPException(status_code=403, detail="Please change your temporary password first")
    return user


PASSWORD_CHANGE_PATHS = {"/api/auth/me", "/api/auth/change-password", "/api/auth/logout"}


async def admin_user(user=Depends(current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
    return user


# User types. Executives and Admins get admin tools (Executives also manage other Executives);
# Executives, Admins and Support Office sign in with Microsoft, Support Workers with an admin-issued password.
USER_TYPES = {"executive": "Executive", "admin": "Admin", "support_office": "Support Office",
              "support_worker": "Support Worker"}
MICROSOFT_TYPES = ("executive", "admin", "support_office")
SEED_USERS = {"andrewt@nolimitts.com.au": ("Andrew", "executive"), "pronathin@nolimitts.com.au": ("Pronathi", "executive"),
              "rond@nolimitts.com.au": ("Ron", "executive"), "justined@nolimitts.com.au": ("Justine", "executive")}


def type_fields(user_type: str) -> dict:
    """The role / executive / staff_group fields the rest of the app reads, derived from the user type."""
    return {"user_type": user_type, "role": "admin" if user_type in ("executive", "admin") else "employee",
            "executive": user_type == "executive",
            "staff_group": "support_worker" if user_type == "support_worker" else "support_office"}


def is_executive(user: Optional[dict]) -> bool:
    return bool(user and user.get("executive"))


async def executive_user(user=Depends(current_user)):
    if not is_executive(user):
        raise HTTPException(status_code=403, detail="Executives only")
    return user


HIDDEN_TEST_USERS = ["user_testadmin01", "user_testemp001"]


async def notify(user_ids: List[str], ntype: str, title: str, body: str, link: str = ""):
    if not user_ids:
        return
    docs = [{"notification_id": new_id("ntf"), "user_id": uid, "type": ntype, "title": title, "body": body,
             "link": link, "read": False, "created_at": now_iso()} for uid in user_ids]
    await db.notifications.insert_many(docs)


async def all_user_ids(exclude: Optional[str] = None):
    users = await db.users.find({}, {"_id": 0, "user_id": 1}).to_list(5000)
    return [u["user_id"] for u in users if u["user_id"] != exclude]


def result_page(title: str, msg: str) -> HTMLResponse:
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head>"
                        f"<body style='font-family:Arial;padding:32px;text-align:center'><h2>{escape(title)}</h2>"
                        f"<p>{escape(msg)}</p><p>You can close this window and return to No Limitts.</p></body></html>")


DIGEST_TZ = ZoneInfo("Australia/Perth")
