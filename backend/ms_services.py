"""Microsoft 365 for the company: SharePoint files, Outlook calendar invites and Teams channel posts.
Uses the same Entra app as sign-in, with app-only (client credentials) access, so nobody has to "connect" an account.
Item ids are "<driveId>!<itemId>" so a single string finds a SharePoint file."""
import asyncio
import base64
import os
import random
import re
import time
import logging
from urllib.parse import urlparse
import httpx
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)
fernet = Fernet(os.environ["WEBHOOK_ENCRYPTION_KEY"].encode())
GRAPH = "https://graph.microsoft.com/v1.0"
FOLDER_MIME = "folder"
DRIVE_FOLDER_NAME = "No Limitts Certificates"
PDF_MIME = "application/pdf"
TEXT_MIMES = ("text/plain", "text/markdown", "text/csv")
OFFICE_TO_PDF = ("wordprocessingml", "msword", "presentationml", "spreadsheetml", "ms-excel", "ms-powerpoint")


def encrypt(v: str) -> str:
    return fernet.encrypt(v.encode()).decode()


def decrypt(v: str) -> str:
    return fernet.decrypt(v.encode()).decode()


def configured() -> bool:
    return all(os.environ.get(k, "").strip() for k in ("MS_TENANT_ID", "MS_CLIENT_ID", "MS_CLIENT_SECRET"))


class Graph:
    """Tiny synchronous Graph client (called from a threadpool) with a cached app-only token."""
    _token, _exp = "", 0.0

    def token(self) -> str:
        if Graph._token and Graph._exp > time.time() + 60:
            return Graph._token
        tid = os.environ["MS_TENANT_ID"].strip()
        r = httpx.post(f"https://login.microsoftonline.com/{tid}/oauth2/v2.0/token", timeout=20, data={
            "client_id": os.environ["MS_CLIENT_ID"].strip(), "client_secret": os.environ["MS_CLIENT_SECRET"].strip(),
            "grant_type": "client_credentials", "scope": "https://graph.microsoft.com/.default"})
        r.raise_for_status()
        Graph._token, Graph._exp = r.json()["access_token"], time.time() + r.json().get("expires_in", 3600)
        return Graph._token

    def req(self, method: str, path: str, **kw) -> httpx.Response:
        url = path if path.startswith("https://") else GRAPH + path
        r = httpx.request(method, url, headers={"Authorization": f"Bearer {self.token()}", **kw.pop("headers", {})},
                          timeout=60, follow_redirects=True, **kw)
        r.raise_for_status()
        return r

    def get(self, path: str, **kw) -> dict:
        return self.req("GET", path, **kw).json()


def drive_service(_unused=None) -> Graph:
    return Graph()


def split_id(item_id: str):
    drive_id, _, iid = item_id.partition("!")
    if not drive_id or not iid:
        raise ValueError("bad item id")
    return drive_id, iid


def norm(it: dict, drive_id: str) -> dict:
    parent = (it.get("parentReference") or {}).get("id")
    return {"id": f"{drive_id}!{it['id']}", "name": it.get("name", ""),
            "mimeType": FOLDER_MIME if "folder" in it else (it.get("file") or {}).get("mimeType", "application/octet-stream"),
            "modifiedTime": it.get("lastModifiedDateTime", ""), "size": it.get("size"), "webViewLink": it.get("webUrl"),
            "parents": [f"{drive_id}!{parent}"] if parent else []}


def folder_id_from_link(link: str) -> str:
    """A SharePoint / OneDrive folder link (or an id we gave out earlier)."""
    link = link.strip()
    if re.fullmatch(r"[^!\s]+![A-Za-z0-9]+", link):
        return link
    if not urlparse(link).scheme.startswith("http"):
        return ""
    enc = base64.urlsafe_b64encode(link.encode()).decode().rstrip("=")
    try:
        it = Graph().get(f"/shares/u!{enc}/driveItem")
    except Exception as e:
        logger.warning(f"SharePoint link lookup failed: {e}")
        return ""
    return f"{it['parentReference']['driveId']}!{it['id']}"


def drive_get(svc: Graph, item_id: str) -> dict:
    d, i = split_id(item_id)
    return norm(svc.get(f"/drives/{d}/items/{i}"), d)


def drive_children(svc: Graph, folder_id: str, q: str = "") -> list:
    d, i = split_id(folder_id)
    out, url = [], f"/drives/{d}/items/{i}/children?$top=200"
    while url and len(out) < 1000:
        res = svc.get(url)
        out += [norm(it, d) for it in res.get("value", [])]
        url = res.get("@odata.nextLink")
    if q:
        out = [f for f in out if q.lower() in f["name"].lower()]
    return sorted(out, key=lambda f: (f["mimeType"] != FOLDER_MIME, f["name"].lower()))


def drive_search_under(svc: Graph, root_id: str, q: str) -> list:
    d, i = split_id(root_id)
    safe = q.replace("'", "''")
    res = svc.get(f"/drives/{d}/items/{i}/search(q='{safe}')?$top=100")
    return [norm(it, d) for it in res.get("value", []) if drive_is_under(svc, f"{d}!{it['id']}", root_id)]


def drive_is_under(svc: Graph, item_id: str, root_id: str) -> bool:
    current = item_id
    for _ in range(20):
        if current == root_id:
            return True
        parents = drive_get(svc, current).get("parents") or []
        if not parents:
            return False
        current = parents[0]
    return False


def drive_walk(svc: Graph, root_id: str, cap: int = 300) -> list:
    files, queue, seen = [], [root_id], 0
    while queue and seen < 80 and len(files) < cap:
        fid = queue.pop(0)
        seen += 1
        for f in drive_children(svc, fid):
            (queue if f["mimeType"] == FOLDER_MIME else files).append(f["id"] if f["mimeType"] == FOLDER_MIME else f)
    return files[:cap]


def is_office(mime: str) -> bool:
    return any(k in mime for k in OFFICE_TO_PDF)


def readable(mime: str) -> bool:
    return mime == PDF_MIME or mime in TEXT_MIMES or is_office(mime)


def _content(svc: Graph, item_id: str, as_pdf: bool = False) -> bytes:
    d, i = split_id(item_id)
    return svc.req("GET", f"/drives/{d}/items/{i}/content" + ("?format=pdf" if as_pdf else "")).content


def drive_text(svc: Graph, f: dict, limit: int = 30000) -> str:
    mime = f["mimeType"]
    if int(f.get("size") or 0) > 15 * 1024 * 1024 or not readable(mime):
        return ""
    if mime in TEXT_MIMES:
        text = _content(svc, f["id"]).decode("utf-8", "ignore")
    else:
        import pymupdf
        doc = pymupdf.open(stream=_content(svc, f["id"], as_pdf=mime != PDF_MIME), filetype="pdf")
        parts, total = [], 0
        for page in doc:
            parts.append(page.get_text())
            total += len(parts[-1])
            if total > limit:
                break
        text = "\n".join(parts)
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:limit]


def drive_download(svc: Graph, item_id: str):
    meta = drive_get(svc, item_id)
    if is_office(meta["mimeType"]):
        return re.sub(r"\.\w+$", "", meta["name"]) + ".pdf", PDF_MIME, _content(svc, item_id, as_pdf=True)
    return meta["name"], meta["mimeType"], _content(svc, item_id)


def drive_upload(svc: Graph, folder_id: str, name: str, data: bytes, mime: str) -> dict:
    d, i = split_id(folder_id)
    safe = re.sub(r'[\\/:*?"<>|#%]', "_", name)[:200]
    it = svc.req("PUT", f"/drives/{d}/items/{i}:/{safe}:/content?@microsoft.graph.conflictBehavior=rename",
                 content=data, headers={"Content-Type": mime or "application/octet-stream"}).json()
    return norm(it, d)


def drive_ensure_folder(svc: Graph, parent_id: str) -> str:
    """'No Limitts Certificates' inside the given SharePoint folder."""
    for f in drive_children(svc, parent_id):
        if f["mimeType"] == FOLDER_MIME and f["name"] == DRIVE_FOLDER_NAME:
            return f["id"]
    d, i = split_id(parent_id)
    it = svc.req("POST", f"/drives/{d}/items/{i}/children",
                 json={"name": DRIVE_FOLDER_NAME, "folder": {}, "@microsoft.graph.conflictBehavior": "replace"}).json()
    return f"{d}!{it['id']}"


# ------------------------------------------------------------- Outlook calendar (organiser's mailbox)
def calendar_insert(organizer_email: str, body: dict) -> dict:
    return Graph().req("POST", f"/users/{organizer_email}/events", json=body).json()


def calendar_delete(organizer_email: str, event_id: str):
    Graph().req("DELETE", f"/users/{organizer_email}/events/{event_id}")


# ------------------------------------------------------------- Microsoft Teams (channel Workflows webhook)
def valid_teams_url(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return url.startswith("https://") and (host.endswith(".logic.azure.com") or host.endswith(".powerplatform.com")
                                           or host.endswith(".webhook.office.com"))


async def post_to_teams(url: str, text: str) -> bool:
    payload = {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": {
        "type": "AdaptiveCard", "version": "1.4", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "body": [{"type": "TextBlock", "text": text[:20000], "wrap": True}]}}]}
    async with httpx.AsyncClient(timeout=10) as client:
        for attempt in range(3):
            try:
                r = await client.post(url, json=payload)
            except httpx.HTTPError:
                r = None
            if r is not None and r.is_success:
                return True
            if r is not None and r.status_code not in (429, 500, 502, 503, 504):
                logger.warning(f"Teams rejected message: {r.status_code}")
                return False
            await asyncio.sleep(2 ** attempt + random.random())
    return False
