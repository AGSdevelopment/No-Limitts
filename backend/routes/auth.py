"""Sign-in: Microsoft (Executives, Admins, Support Office) and admin-issued email + password (Support Workers).
Both end in the same opaque session token in db.user_sessions."""
import base64
import hashlib
import os
import secrets
from datetime import timedelta
from typing import Optional
from urllib.parse import urlencode, urlparse
import bcrypt
import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from core import MICROSOFT_TYPES, P, USER_P, bearer, current_user, db, logger, now, now_iso, result_page

router = APIRouter(prefix="/api")
SESSION_DAYS = 7
MAX_FAILS, LOCK_MINUTES = 5, 15
APP_SCHEMES = {"staffhub", "exp", "exps"}


# ---- shared helpers
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def check_password(pw: str, hashed: Optional[str]) -> bool:
    try:
        return bool(hashed) and bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


DUMMY_HASH = hash_password("timing-only-dummy")


def temp_password() -> str:
    """Easy to read out loud: e.g. Tree-4821-Sky."""
    words = ["Tree", "Heart", "Sky", "Sun", "Wave", "Leaf", "Star", "Bloom", "River", "Cloud", "Rain", "Bird"]
    return f"{secrets.choice(words)}-{secrets.randbelow(9000) + 1000}-{secrets.choice(words)}"


async def new_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    await db.user_sessions.insert_one({"session_token": token, "user_id": user_id,
                                       "expires_at": now() + timedelta(days=SESSION_DAYS), "created_at": now()})
    return token


# ---- Microsoft (server-side authorization code flow, so it works on web, Expo Go and builds)
def ms_config():
    tid, cid, sec = (os.environ.get(k, "").strip() for k in ("MS_TENANT_ID", "MS_CLIENT_ID", "MS_CLIENT_SECRET"))
    return (tid, cid, sec) if tid and cid and sec else None


def ms_redirect_uri() -> str:
    return (os.environ.get("PUBLIC_BACKEND_URL") or "").rstrip("/") + "/api/auth/microsoft/callback"


def safe_return(url: str) -> bool:
    """Only send the login result back to this app (web origin or app deep link)."""
    p = urlparse(url or "")
    if p.scheme in APP_SCHEMES:
        return True
    own = urlparse(os.environ.get("PUBLIC_BACKEND_URL") or "").hostname
    return p.scheme in ("http", "https") and (p.hostname == own or p.hostname == "localhost")


def back_to_app(ret: str, **params) -> RedirectResponse:
    return RedirectResponse(f"{ret}{'&' if '?' in ret else '?'}{urlencode(params)}", status_code=302)


@router.get("/auth/microsoft/status")
async def ms_status():
    return {"configured": bool(ms_config()), "redirect_uri": ms_redirect_uri()}


@router.get("/auth/microsoft/start")
async def ms_start(redirect: str):
    if not safe_return(redirect):
        raise HTTPException(400, "Invalid return address")
    cfg = ms_config()
    if not cfg:
        return back_to_app(redirect, auth_error="Microsoft sign-in isn't set up yet. Please ask your admin.")
    tid, cid, _ = cfg
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(16), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    await db.oauth_states.insert_one({"state": state, "kind": "ms_login", "redirect": redirect, "nonce": nonce,
                                      "code_verifier": verifier, "created_at": now_iso()})
    q = urlencode({"client_id": cid, "response_type": "code", "redirect_uri": ms_redirect_uri(),
                   "response_mode": "query", "scope": "openid profile email User.Read", "state": state,
                   "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256",
                   "prompt": "select_account"})
    return RedirectResponse(f"https://login.microsoftonline.com/{tid}/oauth2/v2.0/authorize?{q}", status_code=302)


def verify_id_token(id_token: str, tid: str, cid: str, nonce: str) -> dict:
    keys = jwt.PyJWKClient(f"https://login.microsoftonline.com/{tid}/discovery/v2.0/keys")
    claims = jwt.decode(id_token, keys.get_signing_key_from_jwt(id_token).key, algorithms=["RS256"], audience=cid,
                        issuer=f"https://login.microsoftonline.com/{tid}/v2.0",
                        options={"require": ["exp", "iat", "iss", "aud", "nonce"]})
    if claims.get("tid") != tid or claims.get("nonce") != nonce:
        raise ValueError("tenant/nonce mismatch")
    return claims


@router.get("/auth/microsoft/callback")
async def ms_callback(state: str = "", code: str = "", error: str = ""):
    st = await db.oauth_states.find_one_and_delete({"state": state, "kind": "ms_login"}) if state else None
    if not st:
        return result_page("Sign-in expired", "Please go back to No Limitts and try again.")
    ret = st["redirect"]
    cfg = ms_config()
    if error or not code or not cfg:
        return back_to_app(ret, auth_error="Microsoft sign-in was cancelled.")
    tid, cid, sec = cfg
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            tr = await c.post(f"https://login.microsoftonline.com/{tid}/oauth2/v2.0/token", data={
                "client_id": cid, "client_secret": sec, "grant_type": "authorization_code", "code": code,
                "redirect_uri": ms_redirect_uri(), "code_verifier": st["code_verifier"],
                "scope": "openid profile email User.Read"})
            tr.raise_for_status()
            tokens = tr.json()
            claims = await run_in_threadpool(verify_id_token, tokens["id_token"], tid, cid, st["nonce"])
            me = await c.get("https://graph.microsoft.com/v1.0/me?$select=displayName,mail,userPrincipalName",
                             headers={"Authorization": f"Bearer {tokens['access_token']}"})
            me.raise_for_status()
            profile = me.json()
    except Exception as e:
        logger.error(f"Microsoft sign-in failed: {type(e).__name__}")
        return back_to_app(ret, auth_error="Microsoft sign-in failed. Please try again.")
    email = (profile.get("mail") or profile.get("userPrincipalName") or "").strip().lower()
    user = await db.users.find_one({"email": email}, P) if email else None
    if not user:
        return back_to_app(ret, auth_error=f"{email or 'This account'} hasn't been added to No Limitts yet. Ask an admin to add you.")
    if user.get("user_type") not in MICROSOFT_TYPES:
        return back_to_app(ret, auth_error="Support Workers sign in with the email and password from your admin.")
    name = profile.get("displayName") or claims.get("name")
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"ms_oid": claims.get("oid"), **({"name": name} if name else {})}})
    login_code = secrets.token_urlsafe(24)
    await db.login_codes.insert_one({"code": login_code, "session_token": await new_session(user["user_id"]),
                                     "expires_at": now() + timedelta(minutes=3)})
    return back_to_app(ret, session_id=login_code)


class SessionIn(BaseModel):
    session_id: str


@router.post("/auth/session")
async def auth_session(body: SessionIn):
    """Swap the one-time code from the Microsoft redirect for the session token."""
    doc = await db.login_codes.find_one_and_delete({"code": body.session_id})
    exp = (doc or {}).get("expires_at")
    if not doc or (exp.replace(tzinfo=now().tzinfo) if exp.tzinfo is None else exp) < now():
        raise HTTPException(401, "Sign-in link expired, please try again")
    sess = await db.user_sessions.find_one({"session_token": doc["session_token"]}, P)
    user = await db.users.find_one({"user_id": sess["user_id"]}, USER_P) if sess else None
    if not user:
        raise HTTPException(401, "Sign-in failed")
    return {"session_token": doc["session_token"], "user": user}


# ---- Email + password (Support Workers)
class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
async def password_login(body: LoginIn):
    email = body.email.strip().lower()
    doc = await db.users.find_one({"email": email})
    generic = HTTPException(401, "Incorrect email or password")
    if doc and doc.get("locked_until") and doc["locked_until"] > now_iso():
        raise HTTPException(429, f"Too many attempts. Try again in {LOCK_MINUTES} minutes or ask your admin to reset your password.")
    ok = check_password(body.password[:200], (doc or {}).get("password_hash") or DUMMY_HASH)
    if not doc or not ok or not doc.get("password_hash"):
        if doc:
            fails = doc.get("failed_logins", 0) + 1
            upd = {"failed_logins": fails}
            if fails >= MAX_FAILS:
                upd = {"failed_logins": 0, "locked_until": (now() + timedelta(minutes=LOCK_MINUTES)).isoformat()}
            await db.users.update_one({"user_id": doc["user_id"]}, {"$set": upd})
        raise generic
    if doc.get("user_type") in MICROSOFT_TYPES:
        raise HTTPException(400, "Office staff sign in with Microsoft.")
    await db.users.update_one({"user_id": doc["user_id"]}, {"$set": {"failed_logins": 0}, "$unset": {"locked_until": ""}})
    token = await new_session(doc["user_id"])
    return {"session_token": token, "user": await db.users.find_one({"user_id": doc["user_id"]}, USER_P)}


class PasswordChangeIn(BaseModel):
    current_password: Optional[str] = None
    new_password: str


@router.post("/auth/change-password")
async def change_password(body: PasswordChangeIn, request: Request, user=Depends(current_user)):
    doc = await db.users.find_one({"user_id": user["user_id"]})
    if not doc.get("password_hash"):
        raise HTTPException(400, "Your account signs in with Microsoft")
    if not doc.get("must_change_password") and not check_password(body.current_password or "", doc["password_hash"]):
        raise HTTPException(400, "Your current password is incorrect")
    pw = body.new_password
    if len(pw) < 8 or len(pw) > 200 or pw.isalpha() or pw.isdigit():
        raise HTTPException(400, "Use at least 8 characters, mixing letters with numbers or symbols")
    if check_password(pw, doc["password_hash"]):
        raise HTTPException(400, "Choose a new password, not the temporary one")
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"password_hash": hash_password(pw),
                                                                     "must_change_password": False}})
    await db.user_sessions.delete_many({"user_id": user["user_id"], "session_token": {"$ne": bearer(request)}})
    return await db.users.find_one({"user_id": user["user_id"]}, USER_P)


@router.get("/auth/me")
async def auth_me(user=Depends(current_user)):
    return user


@router.post("/auth/logout")
async def logout(request: Request):
    token = bearer(request)
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    return {"ok": True}
