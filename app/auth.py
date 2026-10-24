"""Sign in with LinkedIn (OpenID Connect, authorization-code flow) with plain httpx.

Scopes `openid profile email` return sub, name, picture and email from /v2/userinfo.
The public profile URL (vanityName) is only available with `r_basicprofile`, which LinkedIn
grants per app; when present we read it and the scrape can start without asking the user.
"""
from __future__ import annotations

from urllib.parse import urlencode

import httpx

AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
ME_URL = "https://api.linkedin.com/v2/me"
SNAPSHOT_URL = "https://api.linkedin.com/rest/memberSnapshotData"
SNAPSHOT_VERSION = "202312"
PORTABILITY_SCOPES = ("r_dma_portability_self_serve", "r_dma_portability_3rd_party", "r_dma_portability_member")
SNAPSHOT_DOMAINS = ("PROFILE", "POSITIONS", "EDUCATION", "SKILLS", "PROJECTS")


class OIDCError(RuntimeError):
    pass


class LinkedInOIDC:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, scopes: str,
                 http: httpx.Client | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes.split()
        self.http = http or httpx.Client(timeout=30)

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def can_read_profile_url(self) -> bool:
        return "r_basicprofile" in self.scopes

    @property
    def can_read_snapshot(self) -> bool:
        """Member Data Portability (EU/EEA + Switzerland members only): positions, education, skills."""
        return any(scope in self.scopes for scope in PORTABILITY_SCOPES)

    def authorize_url(self, state: str) -> str:
        query = {"response_type": "code", "client_id": self.client_id, "redirect_uri": self.redirect_uri,
                 "state": state, "scope": " ".join(self.scopes)}
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    def exchange_code(self, code: str) -> str:
        """Authorization code -> access token."""
        response = self.http.post(TOKEN_URL, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri,
            "client_id": self.client_id, "client_secret": self.client_secret,
        })
        if response.status_code >= 400:
            raise OIDCError(f"token exchange failed: HTTP {response.status_code} {response.text[:200]}")
        token = response.json().get("access_token")
        if not token:
            raise OIDCError("token response had no access_token")
        return token

    def userinfo(self, access_token: str) -> dict:
        response = self.http.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        if response.status_code >= 400:
            raise OIDCError(f"userinfo failed: HTTP {response.status_code} {response.text[:200]}")
        info = response.json()
        if not info.get("sub"):
            raise OIDCError("userinfo had no sub")
        return info

    def profile_url(self, access_token: str) -> str:
        """Public profile URL via vanityName. Empty string when the scope is missing or the call fails."""
        if not self.can_read_profile_url:
            return ""
        response = self.http.get(ME_URL, params={"projection": "(vanityName)"},
                                 headers={"Authorization": f"Bearer {access_token}"})
        vanity = response.json().get("vanityName") if response.status_code < 400 else None
        return f"https://www.linkedin.com/in/{vanity}" if vanity else ""

    def snapshot(self, access_token: str, domains: tuple[str, ...] = SNAPSHOT_DOMAINS) -> dict[str, list[dict]]:
        """Member Snapshot API, one call per domain. Returns {} when the member cannot consent (403 outside the EEA)."""
        if not self.can_read_snapshot:
            return {}
        headers = {"Authorization": f"Bearer {access_token}", "LinkedIn-Version": SNAPSHOT_VERSION}
        out: dict[str, list[dict]] = {}
        for domain in domains:
            response = self.http.get(SNAPSHOT_URL, params={"q": "criteria", "domain": domain, "start": 0}, headers=headers)
            if response.status_code >= 400:
                continue
            for element in response.json().get("elements", []):
                rows = [r for r in element.get("snapshotData", []) if isinstance(r, dict)]
                if rows:
                    out.setdefault(element.get("snapshotDomain", domain), []).extend(rows)
        return out


def snapshot_to_text(snapshot: dict[str, list[dict]], limit: int = 6000) -> str:
    """Flatten snapshot domains (rows keyed like the LinkedIn data export) into prompt text."""
    lines: list[str] = []
    for domain, rows in snapshot.items():
        lines.append(f"## {domain}")
        for row in rows[:25]:
            lines.append("- " + " | ".join(f"{k}: {str(v)[:400]}" for k, v in row.items() if v not in (None, "")))
    return "\n".join(lines)[:limit]
