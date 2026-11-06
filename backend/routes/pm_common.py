"""Shared Participant Management helpers: Finance / Rosters permissions and Perth (AWST) time handling."""
import re
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request

from core import DIGEST_TZ, bearer, current_user, user_from_token


# ---- Permissions ----

def perms(u: dict) -> set:
    return set(u.get("permissions") or [])


def is_finance(u: dict) -> bool:
    return u.get("role") == "admin" or "finance" in perms(u)


def is_rosters(u: dict) -> bool:
    return u.get("role") == "admin" or "rosters" in perms(u)


def is_coordinator(u: dict) -> bool:
    return u.get("role") == "admin" or u.get("user_type") == "support_coordinator"


async def finance_user(user=Depends(current_user)):
    if not is_finance(user):
        raise HTTPException(403, "For Finance users")
    return user


async def rosters_user(user=Depends(current_user)):
    if not is_rosters(user):
        raise HTTPException(403, "For Rosters users")
    return user


async def office_user(user=Depends(current_user)):
    if not (is_finance(user) or is_rosters(user)):
        raise HTTPException(403, "For Finance and Rosters users")
    return user


# ---- Time helpers (Perth) ----

def parse_dmy(v) -> Optional[str]:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v or "").strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return None


def hhmm_ok(t: str) -> bool:
    return bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t or ""))


def local_dt(d: str, t: str) -> datetime:
    return datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M").replace(tzinfo=DIGEST_TZ)


def span(s: dict):
    start = local_dt(s["date"], s["start"])
    end = local_dt(s["date"], s["end"])
    if end <= start:  # overnight shift finishes the next day
        end += timedelta(days=1)
    return start, end


def now_perth() -> datetime:
    return datetime.now(DIGEST_TZ)


def fmt_hm(dt: datetime) -> str:
    return dt.astimezone(DIGEST_TZ).strftime("%H:%M")


# ---- Funding ----

def money(v) -> float:
    return round(float(v or 0), 2)



async def token_user(request: Request, token: Optional[str]) -> dict:
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Please sign in again")
    return user
