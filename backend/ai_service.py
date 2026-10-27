"""Claude AI helpers: policy assistant (streaming) and certificate detail extraction."""
import os
import re
import json
import base64
import uuid
import pymupdf
from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent, TextDelta, StreamDone

MODEL = ("anthropic", "claude-sonnet-5-5")


def new_chat(system: str) -> LlmChat:
    return LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=f"staffhub-{uuid.uuid4().hex}",
                   system_message=system).with_model(*MODEL)


async def stream_answer(system: str, prompt: str):
    chat = new_chat(system)
    async for ev in chat.stream_message(UserMessage(text=prompt)):
        if isinstance(ev, TextDelta):
            yield ev.content
        elif isinstance(ev, StreamDone):
            break


async def answer(system: str, prompt: str) -> str:
    return (await new_chat(system).send_message(UserMessage(text=prompt))) or ""


def file_to_image_b64(data: bytes, content_type: str) -> str:
    if "pdf" in content_type:
        doc = pymupdf.open(stream=data, filetype="pdf")
        pix = doc[0].get_pixmap(dpi=110)
        return base64.b64encode(pix.tobytes("png")).decode()
    return base64.b64encode(data).decode()


EXTRACT_SYSTEM = ("You read training certificates. Reply ONLY with JSON: "
                  '{"title": string, "issuer": string, "issue_date": "YYYY-MM-DD" or "", '
                  '"expiry_date": "YYYY-MM-DD" or ""}. If the certificate states a validity period instead of '
                  "an expiry date, compute the expiry date. Use empty strings when unknown.")


async def extract_certificate(data: bytes, content_type: str) -> dict:
    img = file_to_image_b64(data, content_type)
    chat = new_chat(EXTRACT_SYSTEM)
    text = await chat.send_message(UserMessage(text="Extract the certificate details.",
                                               file_contents=[ImageContent(image_base64=img)]))
    m = re.search(r"\{.*\}", text or "", re.S)
    out = {"title": "", "issuer": "", "issue_date": "", "expiry_date": ""}
    if m:
        try:
            parsed = json.loads(m.group(0))
            for k in out:
                v = parsed.get(k)
                out[k] = str(v).strip() if v else ""
        except json.JSONDecodeError:
            pass
    for k in ("issue_date", "expiry_date"):
        if out[k] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", out[k]):
            out[k] = ""
    return out
