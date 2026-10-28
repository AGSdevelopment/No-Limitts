"""Google Drive (OAuth, company account) + Google Chat incoming webhooks."""
import os
import io
import re
import asyncio
import random
import logging
import httpx
from cryptography.fernet import Fernet
from google.auth.transport.requests import Request as GRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

logger = logging.getLogger(__name__)
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")  # Google may return extra previously granted scopes

fernet = Fernet(os.environ["WEBHOOK_ENCRYPTION_KEY"].encode())
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
DRIVE_FOLDER_NAME = "StaffHub Certificates"


def encrypt(v: str) -> str:
    return fernet.encrypt(v.encode()).decode()


def decrypt(v: str) -> str:
    return fernet.decrypt(v.encode()).decode()


# ------------------------------------------------------------- Google Drive
def drive_client_config():
    cid = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    if not cid or not secret:
        return None
    return {"web": {"client_id": cid, "client_secret": secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token"}}


def redirect_uri(kind: str):
    return os.environ["PUBLIC_BACKEND_URL"].rstrip("/") + f"/api/integrations/{kind}/callback"


def drive_redirect_uri():
    return redirect_uri("google-drive")


def oauth_flow(kind: str, scopes, state=None):
    flow = Flow.from_client_config(drive_client_config(), scopes=scopes, state=state)
    flow.redirect_uri = redirect_uri(kind)
    return flow


def oauth_auth_url(kind: str, scopes, state: str, login_hint: str = ""):
    flow = oauth_flow(kind, scopes, state)
    extra = {"login_hint": login_hint} if login_hint else {}
    url, _ = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent", **extra)
    return url, flow.code_verifier


def oauth_exchange(kind: str, scopes, state: str, code: str, code_verifier):
    flow = oauth_flow(kind, scopes, state)
    if code_verifier:
        flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    return flow.credentials.refresh_token


def drive_auth_url(state: str):
    return oauth_auth_url("google-drive", DRIVE_SCOPES, state)


def drive_exchange(state: str, code: str, code_verifier):
    return oauth_exchange("google-drive", DRIVE_SCOPES, state, code, code_verifier)


def google_creds(refresh_token_enc: str, scopes):
    cfg = drive_client_config()["web"]
    creds = Credentials(token=None, refresh_token=decrypt(refresh_token_enc), token_uri=cfg["token_uri"],
                        client_id=cfg["client_id"], client_secret=cfg["client_secret"], scopes=scopes)
    creds.refresh(GRequest())
    return creds


def drive_service(refresh_token_enc: str):
    return build("drive", "v3", credentials=google_creds(refresh_token_enc, DRIVE_SCOPES), cache_discovery=False)


# ------------------------------------------------------------- Google Calendar (per-admin invites)
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def calendar_service(refresh_token_enc: str):
    return build("calendar", "v3", credentials=google_creds(refresh_token_enc, CALENDAR_SCOPES), cache_discovery=False)


def calendar_insert(svc, body: dict) -> dict:
    return svc.events().insert(calendarId="primary", body=body, sendUpdates="all").execute()


def calendar_patch(svc, event_id: str, body: dict) -> dict:
    return svc.events().patch(calendarId="primary", eventId=event_id, body=body, sendUpdates="none").execute()


def calendar_delete(svc, event_id: str):
    svc.events().delete(calendarId="primary", eventId=event_id, sendUpdates="all").execute()


# ------------------------------------------------------------- Google Chat (two-way read via Chat API)
CHAT_SCOPES = ["https://www.googleapis.com/auth/chat.messages.readonly"]


def chat_service(refresh_token_enc: str):
    return build("chat", "v1", credentials=google_creds(refresh_token_enc, CHAT_SCOPES), cache_discovery=False)


def space_from_webhook(url: str):
    m = re.search(r"/v1/(spaces/[^/]+)/messages", url)
    return m.group(1) if m else None


def chat_new_messages(svc, space: str, after_iso: str) -> list:
    out, token = [], None
    while True:
        res = svc.spaces().messages().list(parent=space, pageSize=100, pageToken=token,
                                           filter=f'createTime > "{after_iso}"', orderBy="createTime asc").execute()
        out += res.get("messages", [])
        token = res.get("nextPageToken")
        if not token or len(out) >= 500:
            return out


def drive_account_email(svc) -> str:
    return svc.about().get(fields="user(emailAddress)").execute().get("user", {}).get("emailAddress", "")


def drive_ensure_folder(svc) -> str:
    q = (f"name = '{DRIVE_FOLDER_NAME}' and mimeType = 'application/vnd.google-apps.folder' "
         "and trashed = false and 'root' in parents")
    found = svc.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files", [])
    if found:
        return found[0]["id"]
    return svc.files().create(body={"name": DRIVE_FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"},
                              fields="id").execute()["id"]


def drive_upload(svc, folder_id: str, name: str, data: bytes, mime: str) -> dict:
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime, resumable=False)
    return svc.files().create(body={"name": name, "parents": [folder_id]}, media_body=media,
                              fields="id,name,webViewLink", supportsAllDrives=True).execute()


def drive_list(svc, q: str = "") -> list:
    safe = q.replace("\\", "").replace("'", "\\'")
    query = "trashed = false and mimeType != 'application/vnd.google-apps.folder'"
    if safe:
        query += f" and name contains '{safe}'"
    res = svc.files().list(q=query, pageSize=30, orderBy="modifiedTime desc",
                           fields="files(id,name,mimeType,modifiedTime,webViewLink,iconLink)",
                           supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    return res.get("files", [])


def drive_get(svc, file_id: str) -> dict:
    return svc.files().get(fileId=file_id, fields="id,name,mimeType,webViewLink,parents",
                           supportsAllDrives=True).execute()


FOLDER_MIME = "application/vnd.google-apps.folder"
EXPORT_MIME = {"application/vnd.google-apps.document": "application/pdf",
               "application/vnd.google-apps.spreadsheet": "application/pdf",
               "application/vnd.google-apps.presentation": "application/pdf",
               "application/vnd.google-apps.drawing": "application/pdf"}


def folder_id_from_link(link: str) -> str:
    link = link.strip()
    m = re.search(r"/folders/([A-Za-z0-9_-]+)", link) or re.search(r"[?&]id=([A-Za-z0-9_-]+)", link)
    if m:
        return m.group(1)
    return link if re.fullmatch(r"[A-Za-z0-9_-]{10,}", link) else ""


def drive_children(svc, folder_id: str, q: str = "") -> list:
    safe = q.replace("\\", "").replace("'", "\\'")
    query = f"'{folder_id}' in parents and trashed = false"
    if safe:
        query += f" and name contains '{safe}'"
    out, token = [], None
    while True:
        res = svc.files().list(q=query, pageSize=200, pageToken=token, orderBy="folder,name",
                               fields="nextPageToken,files(id,name,mimeType,modifiedTime,size)",
                               supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        out += res.get("files", [])
        token = res.get("nextPageToken")
        if not token or len(out) >= 1000:
            return out


def drive_search_under(svc, root_id: str, q: str) -> list:
    """Search by name anywhere below root (walks subfolders, capped)."""
    found, queue, seen = [], [root_id], 0
    while queue and seen < 60:
        fid = queue.pop(0)
        seen += 1
        for f in drive_children(svc, fid):
            if f["mimeType"] == FOLDER_MIME:
                queue.append(f["id"])
            if q.lower() in f["name"].lower():
                found.append(f)
        if len(found) >= 100:
            break
    return found


def drive_is_under(svc, file_id: str, root_id: str) -> bool:
    current = file_id
    for _ in range(15):
        if current == root_id:
            return True
        parents = drive_get(svc, current).get("parents") or []
        if not parents:
            return False
        current = parents[0]
    return False


TEXT_EXPORT = {"application/vnd.google-apps.document": "text/plain",
               "application/vnd.google-apps.presentation": "text/plain",
               "application/vnd.google-apps.spreadsheet": "text/csv"}
TEXT_MIMES = ("text/plain", "text/markdown", "text/csv")
PDF_MIME = "application/pdf"


def drive_walk(svc, root_id: str, cap: int = 300) -> list:
    """All non-folder files below root (breadth-first, capped)."""
    files, queue, seen = [], [root_id], 0
    while queue and seen < 80 and len(files) < cap:
        fid = queue.pop(0)
        seen += 1
        for f in drive_children(svc, fid):
            if f["mimeType"] == FOLDER_MIME:
                queue.append(f["id"])
            else:
                files.append(f)
    return files[:cap]


def readable(mime: str) -> bool:
    return mime in TEXT_EXPORT or mime in TEXT_MIMES or mime == PDF_MIME


def drive_text(svc, f: dict, limit: int = 30000) -> str:
    mime = f["mimeType"]
    if mime in TEXT_EXPORT:
        data = svc.files().export(fileId=f["id"], mimeType=TEXT_EXPORT[mime]).execute()
        text = data.decode("utf-8", "ignore") if isinstance(data, bytes) else str(data)
    elif mime == PDF_MIME:
        if int(f.get("size") or 0) > 15 * 1024 * 1024:
            return ""
        data = svc.files().get_media(fileId=f["id"], supportsAllDrives=True).execute()
        import pymupdf
        doc = pymupdf.open(stream=data, filetype="pdf")
        parts, total = [], 0
        for page in doc:
            t = page.get_text()
            parts.append(t)
            total += len(t)
            if total > limit:
                break
        text = "\n".join(parts)
    elif mime in TEXT_MIMES:
        data = svc.files().get_media(fileId=f["id"], supportsAllDrives=True).execute()
        text = data.decode("utf-8", "ignore")
    else:
        return ""
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:limit]


def drive_download(svc, file_id: str):
    meta = drive_get(svc, file_id)
    mime = meta["mimeType"]
    if mime in EXPORT_MIME:
        data = svc.files().export(fileId=file_id, mimeType=EXPORT_MIME[mime]).execute()
        return meta["name"] + ".pdf", EXPORT_MIME[mime], data
    data = svc.files().get_media(fileId=file_id, supportsAllDrives=True).execute()
    return meta["name"], mime, data


# ------------------------------------------------------------- Google Chat
def valid_gchat_url(url: str) -> bool:
    return url.startswith("https://chat.googleapis.com/") and "key=" in url and "token=" in url


async def post_to_gchat(url: str, text: str) -> bool:
    payload = {"text": text[:30000]}
    async with httpx.AsyncClient(timeout=10) as client:
        for attempt in range(3):
            try:
                r = await client.post(url, json=payload)
            except httpx.HTTPError:
                r = None
            if r is not None and r.is_success:
                return True
            if r is not None and r.status_code not in (429, 500, 502, 503, 504):
                logger.warning(f"Google Chat rejected message: {r.status_code}")
                return False
            await asyncio.sleep(2 ** attempt + random.random())
    return False
