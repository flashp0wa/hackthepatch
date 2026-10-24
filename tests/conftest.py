"""Shared fakes: an OpenAI-shaped client that never touches the network, and a seeded in-memory app."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.graph import InMemoryStore
from app.llm import LLM
from app.main import create_app
from app.models import Profile, make_person_id

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SEED = json.loads((FIXTURES / "seed_profiles.json").read_text())


class FakeOpenAI:
    """Mimics the two client calls the app uses. `chat_reply` decides what the model 'says'."""

    def __init__(self, chat_reply=None, embeddings_fail=False):
        self.chat_reply = chat_reply or (lambda messages: "{}")
        self.calls: list[dict] = []
        client = self

        class _Completions:
            def create(self, **kw):
                client.calls.append(kw)
                content = client.chat_reply(kw["messages"])
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

        class _Embeddings:
            def create(self, **kw):
                if embeddings_fail:
                    raise RuntimeError("no embeddings endpoint")
                text = kw["input"]
                vec = [float(len(text) % 7), float(text.count("a")), 1.0]
                return SimpleNamespace(data=[SimpleNamespace(embedding=vec)])

        self.chat = SimpleNamespace(completions=_Completions())
        self.embeddings = _Embeddings()


def seed_profiles() -> list[Profile]:
    out = []
    for rec in SEED:
        rec = dict(rec)
        rec.setdefault("id", make_person_id(rec["name"], rec.get("url", "")))
        out.append(Profile(**rec))
    return out


def seed_room(client) -> list[Profile]:
    """Put the 14 fictional attendees into a test app's store, embedded the way ingest() would."""
    app = client.app
    out = []
    for p in seed_profiles():
        p.embedding = app.state.llm.embed(p.text_for_embedding())
        app.state.store.upsert_person(p)
        out.append(p)
    return out


@pytest.fixture
def settings() -> Settings:
    return Settings(store="memory", openai_api_key="test")


@pytest.fixture
def fake_llm(settings) -> LLM:
    # Extraction reply is only used by the /attendees/text test; routing replies pick the first id.
    def reply(messages):
        system = messages[0]["content"]
        if "shortlist" in system.lower():
            first = messages[1]["content"].split("id=")[1].split(" ")[0]
            return json.dumps({"picks": [{"id": first, "reason": "fake pick"}]})
        if "pain_points" in system:
            return json.dumps({
                "summary": "A scheduling API with no UI.", "pain_points": ["no frontend", "no users yet"],
                "needs": ["frontend engineering", "product design"], "domains": ["developer tools"],
                "connection_ideas": ["A designer who has shipped a developer tool."],
            })
        return json.dumps({
            "name": "Jane Tester", "headline": "QA lead at Example", "summary": "Tests things.",
            "building": "a test harness", "technologies": ["pytest", "python"], "interests": ["testing"],
            "can_offer": ["qa", "test automation"], "looking_for": ["backend engineering"],
            "companies": ["Example"], "schools": ["Test U"],
        })
    return LLM(settings, client=FakeOpenAI(reply, embeddings_fail=True))


def fake_oidc(vanity: str | None = None, scopes: str = "openid profile email", snapshot_status: int = 403):
    """LinkedInOIDC wired to a mock transport for the token, userinfo and /me calls."""
    import httpx
    from app.auth import LinkedInOIDC

    def handler(request: httpx.Request):
        if request.url.path.endswith("/accessToken"):
            assert b"grant_type=authorization_code" in request.read() and b"code=good" in request.read()
            return httpx.Response(200, json={"access_token": "tok"})
        assert request.headers["Authorization"] == "Bearer tok"
        if request.url.path.endswith("/userinfo"):
            return httpx.Response(200, json={"sub": "abc123", "name": "Jane Tester", "email": "jane@example.com",
                                             "picture": "https://img.example/jane.jpg"})
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"vanityName": vanity} if vanity else {})
        if request.url.path.endswith("/memberSnapshotData"):
            assert request.headers["LinkedIn-Version"] == "202312"
            domain = request.url.params["domain"]
            if snapshot_status != 200:
                return httpx.Response(snapshot_status, json={"message": "ACCESS_DENIED"})
            rows = {"POSITIONS": [{"Company Name": "Example", "Title": "QA lead", "Description": "Owns test automation.",
                                   "Started On": "Jan 2021"}],
                    "SKILLS": [{"Name": "pytest"}, {"Name": "python"}]}.get(domain, [])
            return httpx.Response(200, json={"elements": [{"snapshotDomain": domain, "snapshotData": rows}]})
        return httpx.Response(404)

    return LinkedInOIDC("cid", "csecret", "http://testserver/auth/callback", scopes,
                        http=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.fixture
def client(settings, fake_llm):
    from fastapi.testclient import TestClient
    app = create_app(settings=settings, store=InMemoryStore(), llm=fake_llm, oidc=fake_oidc())
    return TestClient(app)
