"""Claude AI assistant, chat summaries and certificate reading."""
from datetime import date
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json
import re
from core import MAX_UPLOAD_BYTES, P, current_user, db, logger, new_id, now_iso
from routes.certificates import with_status
from routes.chat import conv_for_user
from routes.drive import current_roots
import ai_service

router = APIRouter(prefix="/api")


class AskIn(BaseModel):
    question: str


STOPWORDS = {"what", "when", "where", "which", "about", "should", "would", "could", "there", "their", "with",
             "from", "that", "this", "have", "does", "your", "what's", "how", "the", "and", "for", "are", "our"}


async def drive_context(question: str, budget: int = 50000) -> str:
    roots = list((await current_roots()).values())
    if not roots:
        return ""
    words = {w.rstrip("s") if len(w) > 4 else w
             for w in re.findall(r"[a-z0-9]{3,}", question.lower()) if w not in STOPWORDS}
    docs = await db.drive_docs.find({"root_id": {"$in": roots}, "text": {"$ne": ""}, "stale": {"$ne": True}},
                                    {"_id": 0, "name": 1, "text": 1}).to_list(400)
    if not docs:
        return ""
    names = "\n".join(f"- {d['name']}" for d in docs)

    def score(d):
        name, text = d["name"].lower(), d["text"].lower()
        return sum(name.count(w) * 5 + min(text.count(w), 20) for w in words)

    ranked = sorted(docs, key=score, reverse=True)
    out, total = [], 0
    for d in ranked:
        if words and score(d) == 0 and out:
            break
        chunk = f"### Drive file: {d['name']}\n{d['text'][:15000]}\n"
        if total + len(chunk) > budget:
            if out:
                break
            chunk = chunk[:budget]
        out.append(chunk)
        total += len(chunk)
    return f"All files in the folder ({len(docs)}):\n{names}\n\n" + "\n".join(out)


async def assistant_context(user: dict, question: str = "") -> str:
    pols = await db.policies.find({}, P).sort("created_at", -1).to_list(100)
    text, total = [], 0
    for p in pols:
        chunk = f"### {p['category']}: {p['title']}\n{p['content']}\n"
        total += len(chunk)
        if total > 60000:
            break
        text.append(chunk)
    certs = [with_status(c) for c in await db.certificates.find({"owner_id": user["user_id"], "is_deleted": False}, P)
             .to_list(100)]
    cert_lines = "\n".join(f"- {c['title']}: expires {c['expiry_date']} ({c['status']})" for c in certs) or "none"
    drive = await drive_context(question)
    return ("You are the No Limitts assistant for employees. Answer clearly and briefly using the company "
            "policies and procedures and the company Drive documents below. If the answer isn't in them, say so "
            "and suggest asking a manager. Name the policy or Drive file you used. Never invent policy rules.\n"
            f"Today's date: {date.today().isoformat()}. Employee: {user['name']}.\n"
            f"Employee's certificates:\n{cert_lines}\n\nCOMPANY POLICIES & PROCEDURES:\n" + "\n".join(text)
            + (f"\n\nCOMPANY DRIVE DOCUMENTS (most relevant):\n{drive}" if drive else ""))


@router.get("/ai/history")
async def ai_history(user=Depends(current_user)):
    return await db.ai_messages.find({"user_id": user["user_id"]}, P).sort("created_at", 1).to_list(200)


@router.delete("/ai/history")
async def ai_clear(user=Depends(current_user)):
    await db.ai_messages.delete_many({"user_id": user["user_id"]})
    return {"ok": True}


@router.post("/ai/ask")
async def ai_ask(body: AskIn, user=Depends(current_user)):
    q = body.question.strip()[:2000]
    if not q:
        raise HTTPException(400, "Ask a question")
    history = await db.ai_messages.find({"user_id": user["user_id"]}, P).sort("created_at", -1).to_list(8)
    convo = "\n".join(f"{'Employee' if m['role'] == 'user' else 'Assistant'}: {m['text']}" for m in reversed(history))
    prompt = (f"Earlier conversation:\n{convo}\n\n" if convo else "") + f"Employee question: {q}"
    system = await assistant_context(user, q)
    asked_at = now_iso()

    async def gen():
        parts = []
        try:
            async for delta in ai_service.stream_answer(system, prompt):
                parts.append(delta)
                yield f"data: {json.dumps({'delta': delta})}\n\n"
        except Exception as e:
            logger.error(f"AI stream failed: {e}")
            yield f"data: {json.dumps({'error': 'The assistant is unavailable right now. Please try again.'})}\n\n"
        answer = "".join(parts).strip()
        if answer:
            await db.ai_messages.insert_many([
                {"message_id": new_id("aim"), "user_id": user["user_id"], "role": "user", "text": q,
                 "created_at": asked_at},
                {"message_id": new_id("aim"), "user_id": user["user_id"], "role": "assistant", "text": answer,
                 "created_at": now_iso()}])
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


SUMMARY_SYSTEM = ("You summarise workplace team chats for busy employees. Write a short summary in plain text "
                  "(no markdown symbols): start with 1-2 sentences on the main topics, then up to 6 bullet points "
                  "using '• ' covering key updates, decisions, and any action items with who owns them. "
                  "Be factual; never invent details. Do not mention clock times; refer to days only if useful.")


@router.post("/conversations/{conv_id}/summary")
async def summarise_conversation(conv_id: str, user=Depends(current_user)):
    conv = await conv_for_user(conv_id, user)
    msgs = await db.messages.find({"conversation_id": conv_id}, P).sort("created_at", -1).to_list(200)
    if len(msgs) < 2:
        raise HTTPException(400, "There aren't enough messages to summarise yet")
    msgs.reverse()
    lines, total = [], 0
    for m in reversed(msgs):
        line = f"[{m['created_at'][:10]}] {m.get('sender_name', 'Someone')}: {m['text']}"
        total += len(line)
        if total > 40000:
            break
        lines.append(line)
    lines.reverse()
    title = f"#{conv['name']}" if conv["type"] == "channel" else "a direct message"
    try:
        summary = await ai_service.answer(SUMMARY_SYSTEM, f"Summarise this chat from {title}:\n\n" + "\n".join(lines))
    except Exception as e:
        logger.error(f"Chat summary failed: {e}")
        raise HTTPException(502, "Couldn't summarise right now. Please try again.")
    return {"summary": summary.replace("**", "").strip(), "message_count": len(lines),
            "from": msgs[-len(lines)]["created_at"], "to": msgs[-1]["created_at"]}


@router.post("/ai/extract-certificate")
async def ai_extract(file: UploadFile = File(...), user=Depends(current_user)):
    data = await file.read()
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "File is empty or too large")
    ctype = file.content_type or ""
    if not ("pdf" in ctype or ctype in ("image/png", "image/jpeg", "image/jpg", "image/webp")):
        raise HTTPException(415, "Use a PDF, JPG or PNG")
    try:
        return await ai_service.extract_certificate(data, ctype)
    except Exception as e:
        logger.error(f"AI extract failed: {e}")
        raise HTTPException(502, "Couldn't read the certificate. Please fill in the details manually.")
