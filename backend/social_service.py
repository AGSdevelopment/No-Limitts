"""Facebook Page + Instagram (Meta Graph API) and LinkedIn company page: read-only post import."""
import os
import time
from urllib.parse import urlencode
import httpx

META_V = "v26.0"
META_GRAPH = f"https://graph.facebook.com/{META_V}"
META_SCOPES = "pages_show_list,pages_read_engagement,instagram_basic"
LI_VERSION = "202610"
LI_SCOPES = "r_organization_social r_organization_admin"

SOCIAL_LINKS = {
    "instagram": {"label": "Instagram", "handle": "@nolimittsptyltd", "url": "https://www.instagram.com/nolimittsptyltd/"},
    "facebook": {"label": "Facebook", "handle": "nolimittswa", "url": "https://www.facebook.com/nolimittswa"},
}
WEBSITES = [
    {"label": "No Limitts Core", "url": "https://www.nolimitts.com.au"},
    {"label": "No Limitts Charters", "url": "https://www.nolimittscharters.org.au/"},
    {"label": "No Limitts Support Coordination", "url": "https://www.nolimittssc.org.au/"},
]
FB_PAGE_HINT = "nolimittswa"
LI_VANITY = "aspire-grow-therapy-services"


def redirect_uri(kind: str) -> str:
    return os.environ["PUBLIC_BACKEND_URL"].rstrip("/") + f"/api/integrations/{kind}/callback"


def meta_configured() -> bool:
    return bool(os.environ.get("META_APP_ID") and os.environ.get("META_APP_SECRET"))


def linkedin_configured() -> bool:
    return bool(os.environ.get("LINKEDIN_CLIENT_ID") and os.environ.get("LINKEDIN_CLIENT_SECRET"))


# ------------------------------------------------------------- Meta
def meta_auth_url(state: str) -> str:
    q = {"client_id": os.environ["META_APP_ID"], "redirect_uri": redirect_uri("meta"), "state": state,
         "response_type": "code", "scope": META_SCOPES}
    return f"https://www.facebook.com/{META_V}/dialog/oauth?" + urlencode(q)


async def meta_get(path: str, token: str, **params) -> dict:
    params["access_token"] = token
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(META_GRAPH + path, params=params)
    data = r.json()
    if r.is_error or "error" in data:
        raise RuntimeError(str(data.get("error", data))[:300])
    return data


async def meta_exchange(code: str) -> dict:
    """Returns {page_id, page_name, page_token, ig_user_id, ig_username}."""
    cid, secret = os.environ["META_APP_ID"], os.environ["META_APP_SECRET"]
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{META_GRAPH}/oauth/access_token", params={
            "client_id": cid, "client_secret": secret, "redirect_uri": redirect_uri("meta"), "code": code})
        r.raise_for_status()
        short = r.json()["access_token"]
        # long-lived user token -> page tokens derived from it don't expire
        r = await c.get(f"{META_GRAPH}/oauth/access_token", params={
            "grant_type": "fb_exchange_token", "client_id": cid, "client_secret": secret,
            "fb_exchange_token": short})
        r.raise_for_status()
        user_token = r.json()["access_token"]
    pages = (await meta_get("/me/accounts", user_token,
                            fields="id,name,username,link,access_token,instagram_business_account{id,username}"
                            )).get("data", [])
    if not pages:
        raise RuntimeError("No Facebook Page found for this account")
    page = next((p for p in pages if FB_PAGE_HINT in (p.get("username", "") + p.get("link", "")).lower()),
                pages[0])
    ig = page.get("instagram_business_account") or {}
    return {"page_id": page["id"], "page_name": page["name"], "page_token": page["access_token"],
            "ig_user_id": ig.get("id"), "ig_username": ig.get("username", "")}


async def meta_posts(page_id: str, ig_user_id: str, token: str) -> list:
    out = []
    fb = await meta_get(f"/{page_id}/posts", token, limit=10,
                        fields="id,message,created_time,permalink_url,full_picture")
    for p in fb.get("data", []):
        out.append({"source": "facebook", "external_id": p["id"], "text": p.get("message", ""),
                    "published_at": p.get("created_time"), "link": p.get("permalink_url"),
                    "image_url": p.get("full_picture")})
    if ig_user_id:
        ig = await meta_get(f"/{ig_user_id}/media", token, limit=10,
                            fields="id,caption,media_type,media_url,thumbnail_url,permalink,timestamp")
        for p in ig.get("data", []):
            out.append({"source": "instagram", "external_id": p["id"], "text": p.get("caption", ""),
                        "published_at": p.get("timestamp"), "link": p.get("permalink"),
                        "image_url": p.get("thumbnail_url") if p.get("media_type") == "VIDEO" else p.get("media_url")})
    return out


# ------------------------------------------------------------- LinkedIn
def linkedin_auth_url(state: str) -> str:
    q = {"response_type": "code", "client_id": os.environ["LINKEDIN_CLIENT_ID"],
         "redirect_uri": redirect_uri("linkedin"), "state": state, "scope": LI_SCOPES}
    return "https://www.linkedin.com/oauth/v2/authorization?" + urlencode(q)


def li_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Linkedin-Version": LI_VERSION,
            "X-Restli-Protocol-Version": "2.0.0"}


async def linkedin_exchange(code: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post("https://www.linkedin.com/oauth/v2/accessToken", data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri("linkedin"),
            "client_id": os.environ["LINKEDIN_CLIENT_ID"], "client_secret": os.environ["LINKEDIN_CLIENT_SECRET"]})
        r.raise_for_status()
        tok = r.json()
        token = tok["access_token"]
        org_urn, org_name = None, ""
        r = await c.get("https://api.linkedin.com/rest/organizations", headers=li_headers(token),
                        params={"q": "vanityName", "vanityName": LI_VANITY})
        if r.is_success and r.json().get("elements"):
            el = r.json()["elements"][0]
            org_urn, org_name = f"urn:li:organization:{el['id']}", el.get("localizedName", "")
        if not org_urn:
            r = await c.get("https://api.linkedin.com/rest/organizationAcls", headers=li_headers(token),
                            params={"q": "roleAssignee", "state": "APPROVED"})
            if r.is_success and r.json().get("elements"):
                org_urn = r.json()["elements"][0]["organization"]
    if not org_urn:
        raise RuntimeError("Couldn't find the LinkedIn company page for this account")
    return {"access_token": token, "refresh_token": tok.get("refresh_token"),
            "expires_at": time.time() + tok.get("expires_in", 0), "org_urn": org_urn, "org_name": org_name}


async def linkedin_refresh(refresh_token: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post("https://www.linkedin.com/oauth/v2/accessToken", data={
            "grant_type": "refresh_token", "refresh_token": refresh_token,
            "client_id": os.environ["LINKEDIN_CLIENT_ID"], "client_secret": os.environ["LINKEDIN_CLIENT_SECRET"]})
        r.raise_for_status()
        tok = r.json()
    return {"access_token": tok["access_token"], "refresh_token": tok.get("refresh_token", refresh_token),
            "expires_at": time.time() + tok.get("expires_in", 0)}


async def linkedin_posts(token: str, org_urn: str) -> list:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get("https://api.linkedin.com/rest/posts", headers=li_headers(token),
                        params={"q": "author", "author": org_urn, "count": 10, "sortBy": "CREATED"})
    if r.is_error:
        raise RuntimeError(f"LinkedIn {r.status_code}: {r.text[:200]}")
    out = []
    for p in r.json().get("elements", []):
        urn = p.get("id")
        if not urn:
            continue
        created = p.get("createdAt") or p.get("publishedAt")
        iso = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(created / 1000)) if created else None
        out.append({"source": "linkedin", "external_id": urn, "text": p.get("commentary", ""),
                    "published_at": iso, "link": f"https://www.linkedin.com/feed/update/{urn}/",
                    "image_url": None})
    return out
