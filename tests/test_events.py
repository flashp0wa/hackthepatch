import json

from app.config import Settings
from app.events import load_sessions, overlap_rank, rank_sessions
from app.llm import LLM
from app.models import Profile, Project
from tests.conftest import FakeOpenAI, fake_oidc


def test_agenda_has_the_six_keynotes_described_in_prose_not_tags():
    sessions = load_sessions()
    assert {s["id"] for s in sessions} == {"tls", "kubernetes", "ai-agents", "exchange", "azure-vms", "aws-bedrock"}
    assert all("tags" not in s and len(s["abstract"]) > 300 for s in sessions)


def test_overlap_rank_puts_matching_sessions_first():
    p = Profile(id="x", name="X", technologies=["kubernetes", "flux", "spiffe"], interests=["ai agent security"],
                project=Project(description="d", domains=["gitops"]))
    ranked = overlap_rank(p, load_sessions())
    assert ranked[0]["id"] == "kubernetes" and ranked[0]["score"] > 0
    assert "kubernetes" in ranked[0]["hits"]
    assert ranked[-1]["score"] == 0


def test_rank_sessions_uses_llm_scores_and_falls_back():
    sessions = load_sessions()
    p = Profile(id="x", name="X", technologies=["exchange online"])
    reply = lambda _m: json.dumps({"matches": [{"id": "exchange", "score": 95, "reason": "ran Exchange hybrid"},
                                               {"id": "tls", "score": 10, "reason": "little overlap"}]})
    ranked, source = rank_sessions(LLM(Settings(openai_api_key="t"), client=FakeOpenAI(reply)), p, sessions)
    assert source == "llm"
    assert [s["id"] for s in ranked][:1] == ["exchange"] and ranked[0]["reason"] == "ran Exchange hybrid"
    assert len(ranked) == 6 and all(0 <= s["score"] <= 100 for s in ranked)  # unscored sessions get the fallback
    broken, source = rank_sessions(LLM(Settings(openai_api_key="t"), client=FakeOpenAI(lambda _m: "nope")), p, sessions)
    assert source.startswith("fallback: ")
    assert broken[0]["id"] == "exchange" and broken[0]["reason"].startswith("matches")


def test_interests_endpoint_requires_login_and_returns_ranked_agenda(client):
    assert client.get("/api/event").json()["sessions"][0]["id"] == "tls"
    assert client.post("/api/event/interests").status_code == 401
    r = client.get("/auth/login", follow_redirects=False)
    state = r.headers["location"].split("state=")[1].split("&")[0]
    client.get(f"/auth/callback?code=good&state={state}", follow_redirects=False)
    r = client.post("/api/event/interests").json()
    assert r["person"]["name"] == "Jane Tester" and len(r["sessions"]) == 6
    assert all({"score", "reason", "hits"} <= set(s) for s in r["sessions"])
    assert r["source"].startswith("fallback: ")  # the fake client answers "{}" for this prompt
