"""Runtime settings, read once from the environment.

The project's .env wins over variables already exported in the shell: a developer machine often carries an
OPENAI_API_KEY for some other provider, and python-dotenv's default of not overriding silently sent that key to
api.openai.com (401 on every call, every LLM feature degraded to its fallback).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv(override=True)


@dataclass(frozen=True)
class Settings:
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    chat_model: str = "gpt-4o-mini"
    embed_model: str = "text-embedding-3-small"
    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    graph_name: str = "hackthepatch"
    store: str = "falkordb"
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_redirect_uri: str = "http://localhost:8000/auth/callback"
    linkedin_scopes: str = "openid profile email"
    session_secret: str = "change-me-hackthepatch"
    dev_login: bool = False


def load_settings() -> Settings:
    env = os.environ
    return Settings(
        openai_base_url=env.get("OPENAI_BASE_URL", Settings.openai_base_url),
        openai_api_key=env.get("OPENAI_API_KEY", ""),
        chat_model=env.get("CHAT_MODEL", Settings.chat_model),
        embed_model=env.get("EMBED_MODEL", Settings.embed_model),
        falkordb_host=env.get("FALKORDB_HOST", Settings.falkordb_host),
        falkordb_port=int(env.get("FALKORDB_PORT", Settings.falkordb_port)),
        graph_name=env.get("GRAPH_NAME", Settings.graph_name),
        store=env.get("STORE", Settings.store).lower(),
        linkedin_client_id=env.get("LINKEDIN_CLIENT_ID", ""),
        linkedin_client_secret=env.get("LINKEDIN_CLIENT_SECRET", ""),
        linkedin_redirect_uri=env.get("LINKEDIN_REDIRECT_URI", Settings.linkedin_redirect_uri),
        linkedin_scopes=env.get("LINKEDIN_SCOPES", Settings.linkedin_scopes),
        session_secret=env.get("SESSION_SECRET", Settings.session_secret),
        dev_login=env.get("DEV_LOGIN", "").lower() in ("1", "true", "yes"),
    )
