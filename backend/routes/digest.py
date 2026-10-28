"""Weekly chat digest email."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from html import escape
from typing import Optional
import asyncio
from core import DIGEST_TZ, P, admin_user, db, logger, now, now_iso
from email_service import send_email
import ai_service

router = APIRouter(prefix="/api")


DIGEST_SYSTEM = ("You write a weekly recap of one workplace team chat channel for a Monday morning email. "
                 "Plain text only, no markdown symbols. Write 1 sentence overview, then up to 5 lines starting "
                 "with '• ' for key updates, wins, decisions and action items (with owners). Be factual and brief; "
                 "never invent details; do not mention clock times.")


async def build_digest() -> list:
    since = (now() - timedelta(days=7)).isoformat()
    out = []
    for ch in await db.conversations.find({"type": "channel"}, P).sort("name", 1).to_list(50):
        msgs = await db.messages.find({"conversation_id": ch["conversation_id"], "created_at": {"$gte": since}},
                                      P).sort("created_at", 1).to_list(400)
        if not msgs:
            continue
        lines = [f"{m.get('sender_name', 'Someone')}: {m['text'][:800]}" for m in msgs][-300:]
        try:
            summary = await ai_service.answer(DIGEST_SYSTEM, f"Channel #{ch['name']}, last 7 days:\n\n"
                                              + "\n".join(lines)[:40000])
        except Exception as e:
            logger.error(f"Digest summary failed for {ch['name']}: {e}")
            summary = f"{len(msgs)} new messages this week."
        out.append({"channel": ch["name"], "count": len(msgs), "summary": summary.replace("**", "").strip()})
    return out


def digest_email_html(name: str, sections: list) -> str:
    blocks = "".join(
        f"<div style='margin:0 0 20px;padding:16px;background:#E3F1FE;border-radius:12px'>"
        f"<h3 style='margin:0 0 4px;color:#205890'>#{escape(s['channel'])}</h3>"
        f"<p style='margin:0 0 8px;color:#6b7280;font-size:13px'>{s['count']} message{'s' if s['count'] != 1 else ''}</p>"
        f"<p style='margin:0;white-space:pre-line;color:#111827;line-height:1.5'>{escape(s['summary'])}</p></div>"
        for s in sections)
    return (f"<div style='font-family:Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px'>"
            f"<h2 style='color:#205890;margin:0 0 8px'>Your weekly StaffHub recap</h2>"
            f"<p style='color:#374151'>Hi {escape(name.split(' ')[0] if name else 'there')}, here's what happened "
            f"in your team channels last week.</p>{blocks}"
            f"<p style='color:#6b7280;font-size:12px'>Summaries written by Claude AI. Open StaffHub for the full "
            f"conversations.</p></div>")


async def send_digest(only_user: Optional[dict] = None) -> dict:
    sections = await build_digest()
    if not sections:
        return {"sent": 0, "channels": 0}
    users = [only_user] if only_user else await db.users.find({"email": {"$regex": "@"}}, P).to_list(2000)
    sent = 0
    for u in users:
        if u["email"].endswith("@example.com"):
            continue
        if await send_email(to=u["email"], subject="Your weekly StaffHub recap",
                            html=digest_email_html(u.get("name", ""), sections)):
            sent += 1
    return {"sent": sent, "channels": len(sections)}


async def digest_loop():
    while True:
        try:
            local = datetime.now(DIGEST_TZ)
            if local.weekday() == 0 and local.hour >= 8:
                year, week, _ = local.isocalendar()
                key = f"digest_{year}_{week}"
                if not await db.meta.find_one({"key": key}):
                    await db.meta.insert_one({"key": key, "created_at": now_iso()})
                    res = await send_digest()
                    await db.meta.update_one({"key": key}, {"$set": res})
                    logger.info(f"Weekly digest sent: {res}")
        except Exception as e:
            logger.error(f"Digest loop error: {e}")
        await asyncio.sleep(600)


@router.post("/digest/test")
async def digest_test(admin=Depends(admin_user)):
    """Admin preview: builds this week's digest and emails it only to the requesting admin."""
    res = await send_digest(only_user=admin)
    if not res["channels"]:
        raise HTTPException(400, "No channel messages in the last 7 days to summarise")
    return {**res, "email": admin["email"]}
