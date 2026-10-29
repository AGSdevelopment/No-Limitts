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
    return await db.users.find_one({"user_id": sess["user_id"]}, P)


def bearer(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    return auth[7:] if auth.startswith("Bearer ") else None


async def current_user(request: Request):
    user = await user_from_token(bearer(request))
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def admin_user(user=Depends(current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
    return user


# Executives see the Therapist dashboard, Participant plans & safety and the Team plans overview
EXECUTIVE_EMAILS = {"nikki@aspireandgrow.com.au", "andrew@aspireandgrow.com.au", "pronathi@aspireandgrow.com.au"}


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
