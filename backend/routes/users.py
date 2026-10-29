"""Staff directory and user types (Executive, Admin, Support Office, Support Worker)."""
import csv
import io
import os
import re
from datetime import date, datetime, timedelta
from html import escape
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from typing import Optional
from core import P, USER_P, USER_TYPES, admin_user, current_user, db, new_id, now_iso, spawn, type_fields
from email_service import send_email
from routes.auth import hash_password, temp_password
from routes.compliance import send_starter_welcome

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
    user = await db.users.find_one({"user_id": uid}, USER_P)
    spawn(send_welcome(user, pw))
    if body.user_type == "support_worker":
        spawn(send_starter_welcome(uid))
    return {"user": user, "temporary_password": pw}


async def send_welcome(u: dict, temp_pw: Optional[str]):
    """Branded welcome email with how to sign in (Support Workers also get their temporary password)."""
    if not u.get("email") or u["email"].endswith("@example.com"):
        return
    app_url = (os.environ.get("PUBLIC_BACKEND_URL") or "").rstrip("/")
    first = escape(u["name"].split(" ")[0])
    if temp_pw:
        how = ("<p><b>How to sign in</b></p><ol>"
               f"<li>Open the No Limitts app{f' (or <a href={chr(39)}{app_url}{chr(39)}>open it in your browser</a>)' if app_url.startswith('https://') else ''}.</li>"
               "<li>Under <b>Support Workers</b>, enter:<br>"
               f"Email: <b>{escape(u['email'])}</b><br>Temporary password: <b style='font-size:17px'>{escape(temp_pw)}</b></li>"
               "<li>Choose your own password when asked.</li></ol>"
               "<p>Your <b>first-week checklist</b> will be waiting on the Home screen to help you get set up.</p>")
    else:
        how = ("<p><b>How to sign in</b></p><ol>"
               f"<li>Open the No Limitts app{f' (or <a href={chr(39)}{app_url}{chr(39)}>open it in your browser</a>)' if app_url.startswith('https://') else ''}.</li>"
               "<li>Tap <b>Sign in with Microsoft</b> and use your work account "
               f"(<b>{escape(u['email'])}</b>).</li></ol>")
    await send_email(to=u["email"], subject="Welcome to No Limitts! Here's how to sign in", html=(
        "<div style='font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#11181C'>"
        f"<h2 style='color:#673E8D'>Welcome to No Limitts, {first}!</h2>"
        f"<p>You've been added to the No Limitts staff app as <b>{USER_TYPES.get(u.get('user_type'), '')}</b>. "
        "It's where you'll find team chat, policies, training certificates, events and company updates.</p>"
        f"{how}<p>Any questions? Just reply to your admin or message the team in the app.</p>"
        "<p style='color:#EB3F7F;font-weight:bold'>Where possibilities are limitless 💜</p></div>"))


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


@router.post("/users/{user_id}/resend-welcome")
async def resend_welcome(user_id: str, admin=Depends(admin_user)):
    """Re-send the welcome email. Support Workers get a fresh temporary password (old one stops working)."""
    target = await db.users.find_one({"user_id": user_id}, USER_P)
    if not target or target.get("hidden") and not admin.get("hidden"):
        raise HTTPException(404, "User not found")
    pw = await issue_password(user_id) if target.get("user_type") == "support_worker" else None
    spawn(send_welcome(target, pw))
    emailed = bool(target.get("email")) and not target["email"].endswith("@example.com")
    return {"temporary_password": pw, "emailed": emailed}


IMPORT_COLS = {"name": ("name", "full name", "staff name"), "email": ("email", "email address", "work email"),
               "user_type": ("user type", "type", "role"), "job_title": ("job title", "title", "position"),
               "start_date": ("start date", "started"), "birthday": ("birthday", "date of birth", "dob")}
TYPE_WORDS = {"support worker": "support_worker", "support workers": "support_worker", "worker": "support_worker",
              "support office": "support_office", "office": "support_office", "admin": "admin", "executive": "executive"}


def parse_day(v, allow_no_year: bool = False) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and 1 < v < 80000:  # Excel serial date stored as a number
        return date(1899, 12, 30) + timedelta(days=int(v))
    s = str(v or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d.%m.%Y") + (("%d/%m", "%d-%m", "%d.%m") if allow_no_year else ()):
        try:
            d = datetime.strptime(s, fmt).date()
            return d.replace(year=2000) if fmt in ("%d/%m", "%d-%m", "%d.%m") else d
        except ValueError:
            pass
    return None


def read_rows(name: str, data: bytes) -> list:
    if name.lower().endswith(".csv"):
        text = data.decode("utf-8-sig", "ignore")
        return [r for r in csv.reader(io.StringIO(text))]
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]


@router.post("/users/import")
async def import_users(file: UploadFile = File(...), admin=Depends(admin_user)):
    """Add many staff from an Excel/CSV sheet (Name, Email, optional User type, Job title, Start date, Birthday).
    Everyone gets the welcome email; Support Workers' temporary passwords are only sent by email."""
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 5 MB)")
    try:
        rows = await run_in_threadpool(read_rows, file.filename or "", data)
    except Exception:
        raise HTTPException(400, "Couldn't read that file. Upload an Excel (.xlsx) or CSV file")
    rows = [r for r in rows if any(str(c or "").strip() for c in r)]
    if len(rows) < 2:
        raise HTTPException(400, "The sheet needs a header row and at least one staff member")
    header = [str(c or "").strip().lower() for c in rows[0]]
    col = {k: next((i for i, h in enumerate(header) if h in names), None) for k, names in IMPORT_COLS.items()}
    if col["name"] is None or col["email"] is None:
        raise HTTPException(400, "Couldn't find 'Name' and 'Email' columns in the first row")
    if len(rows) > 501:
        raise HTTPException(400, "Import up to 500 staff at a time")
    get = lambda r, k: (r[col[k]] if col[k] is not None and col[k] < len(r) else None)  # noqa: E731
    added, skipped, seen = [], [], set()
    for n, r in enumerate(rows[1:], start=2):
        name, email = str(get(r, "name") or "").strip(), str(get(r, "email") or "").strip().lower()
        raw_type = str(get(r, "user_type") or "").strip().lower()
        t = TYPE_WORDS.get(raw_type) if raw_type else "support_worker"
        reason = None
        if not name or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            reason = "Missing name or invalid email"
        elif not t:
            reason = f"Unknown user type '{get(r, 'user_type')}' (use Executive, Admin, Support Office or Support Worker)"
        elif email in seen or await db.users.find_one({"email": email}):
            reason = "Already in the app"
        elif t == "executive" and admin.get("user_type") != "executive":
            reason = "Only Executives can add Executives"
        if reason:
            skipped.append({"row": n, "name": name, "email": email, "reason": reason})
            continue
        seen.add(email)
        start, bday = parse_day(get(r, "start_date")), parse_day(get(r, "birthday"), allow_no_year=True)
        uid = new_id("user")
        await db.users.insert_one({"user_id": uid, "email": email, "name": name[:120], "picture": None,
                                   "job_title": str(get(r, "job_title") or "").strip()[:120], "created_at": now_iso(),
                                   **({"start_date": start.isoformat()} if start else {}),
                                   **({"birthday": bday.strftime("%m-%d")} if bday else {}), **type_fields(t)})
        pw = await issue_password(uid) if t == "support_worker" else None
        spawn(send_welcome(await db.users.find_one({"user_id": uid}, USER_P), pw))
        if t == "support_worker":
            spawn(send_starter_welcome(uid))
        added.append({"name": name, "email": email, "user_type": t, "emailed": not email.endswith("@example.com")})
    return {"added": added, "skipped": skipped}


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
