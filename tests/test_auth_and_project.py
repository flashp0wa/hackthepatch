from fastapi.testclient import TestClient

from app.config import Settings
from app.graph import InMemoryStore
from app.main import create_app
from tests.conftest import fake_oidc, seed_room


def make_client(fake_llm, vanity=None, scopes="openid profile email", dev_login=False, snapshot_status=403):
    settings = Settings(store="memory", openai_api_key="test", dev_login=dev_login)
    app = create_app(settings=settings, store=InMemoryStore(), llm=fake_llm,
                     oidc=fake_oidc(vanity, scopes, snapshot_status))
    return TestClient(app, follow_redirects=False)


def do_login(client):
    r = client.get("/auth/login")
    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith("https://www.linkedin.com/oauth/v2/authorization?") and "client_id=cid" in location
    state = location.split("state=")[1].split("&")[0]
    r = client.get(f"/auth/callback?code=good&state={state}")
    assert r.status_code == 302 and r.headers["location"] == "/#me"


def test_login_creates_attendee_and_session(fake_llm):
    client = make_client(fake_llm)
    assert client.get("/api/me").json()["user"] is None
    do_login(client)
    me = client.get("/api/me").json()
    assert me["user"]["name"] == "Jane Tester" and me["user"]["email"] == "jane@example.com"
    assert me["user"]["picture"].endswith("jane.jpg") and me["user"]["id"] == "li-abc123"
    assert me["auto_profile_url"] is False and me["job"] is None  # no r_basicprofile: URL must be pasted
    assert len(client.get("/api/attendees").json()) == 1
    do_login(client)  # second login finds the same person, no duplicate
    assert len(client.get("/api/attendees").json()) == 1
    assert client.post("/auth/logout").json() == {"signed_out": True}
    assert client.get("/api/me").json()["user"] is None


def test_callback_rejects_bad_state_and_provider_errors(fake_llm):
    client = make_client(fake_llm)
    assert client.get("/auth/callback?code=good&state=forged").status_code == 400
    assert client.get("/auth/callback?error=user_cancelled_login&error_description=no").status_code == 400
    assert client.put("/api/me/project", json={"description": "x"}).status_code == 401


def test_login_without_oidc_config_is_503(fake_llm):
    from app.auth import LinkedInOIDC
    app = create_app(settings=Settings(store="memory", openai_api_key="t"), store=InMemoryStore(), llm=fake_llm,
                     oidc=LinkedInOIDC("", "", "http://x/cb", "openid"))
    assert TestClient(app, follow_redirects=False).get("/auth/login").status_code == 503


def test_login_with_basicprofile_scope_stores_the_profile_url(fake_llm):
    client = make_client(fake_llm, vanity="jane-t", scopes="openid profile email r_basicprofile")
    do_login(client)
    me = client.get("/api/me").json()
    assert me["job"] is None  # nothing runs in the background: the attendee imports a PDF or text
    user = me["user"]
    assert user["id"] == "li-abc123" and user["url"] == "https://www.linkedin.com/in/jane-t"
    assert user["email"] == "jane@example.com" and user["technologies"] == []
    assert len(client.get("/api/attendees").json()) == 1


def test_active_project_extracts_pain_points_and_finds_connections(fake_llm):
    client = make_client(fake_llm)
    seed_room(client)
    do_login(client)
    assert client.put("/api/me/project", json={"description": "   "}).status_code == 400
    r = client.put("/api/me/project", json={"description": "A scheduling API for freelancers, no UI yet."}).json()
    assert r["project"]["pain_points"] == ["no frontend", "no users yet"]
    assert r["project"]["needs"] == ["frontend engineering", "product design"]
    names = [c["person"]["name"] for c in r["connections"]]
    assert names and "Daniel Reyes" in names[:2], names  # designer + frontend covers both needs
    top = r["connections"][0]
    assert set(top["covers"]) <= {"frontend engineering", "product design"} and top["covers"]
    assert "Jane Tester" not in names
    # persisted: visible on /api/me, used by complementary matching, and reloadable
    me = client.get("/api/me").json()["user"]
    assert me["project"]["summary"] == "A scheduling API with no UI."
    assert client.get("/api/me/connections").json()[0]["person"]["name"] == names[0]
    matches = client.get(f"/api/matches/{me['id']}").json()["matches"]
    assert matches and "product design" in matches[0]["fills"] or "frontend engineering" in matches[0]["fills"]


def test_dev_login_only_when_enabled(fake_llm):
    assert make_client(fake_llm).post("/auth/dev-login", json={"name": "Dev"}).status_code == 404
    client = make_client(fake_llm, dev_login=True)
    assert client.post("/auth/dev-login", json={"name": "Dev Person"}).json()["id"] == "li-dev-dev-person"
    assert client.get("/api/me").json()["user"]["name"] == "Dev Person"


def test_login_hops_to_the_registered_callback_host_first(fake_llm):
    client = make_client(fake_llm)
    r = client.get("http://127.0.0.1/auth/login")  # browser on a different host than the redirect URI
    assert r.status_code == 302 and r.headers["location"] == "http://testserver/auth/login"


def test_data_portability_consent_fills_profile(fake_llm):
    client = make_client(fake_llm, vanity="jane-t",
                         scopes="openid profile email r_basicprofile r_dma_portability_self_serve", snapshot_status=200)
    do_login(client)
    me = client.get("/api/me").json()
    assert me["portability"] is True and me["job"]["status"] == "done"
    assert me["job"]["url"] == "linkedin:member-data-portability"
    user = me["user"]
    assert user["technologies"] == ["pytest", "python"] and user["email"] == "jane@example.com"
    prompt = fake_llm.client.calls[0]["messages"][1]["content"]
    assert "## POSITIONS" in prompt and "Title: QA lead" in prompt and "Description: Owns test automation." in prompt


def test_data_portability_refused_leaves_the_profile_for_manual_import(fake_llm):
    client = make_client(fake_llm, vanity="jane-t",
                         scopes="openid profile email r_basicprofile r_dma_portability_self_serve", snapshot_status=403)
    do_login(client)
    me = client.get("/api/me").json()
    assert me["job"] is None and me["user"]["url"] == "https://www.linkedin.com/in/jane-t"


def test_snapshot_to_text_flattens_rows():
    from app.auth import snapshot_to_text
    text = snapshot_to_text({"POSITIONS": [{"Title": "Dev", "Company Name": "Acme", "Description": ""}], "SKILLS": [{"Name": "go"}]})
    assert text == "## POSITIONS\n- Title: Dev | Company Name: Acme\n## SKILLS\n- Name: go"


def test_me_profile_is_editable_and_saved(fake_llm):
    client = make_client(fake_llm)
    assert client.put("/api/me/profile", json={"technologies": ["x"]}).status_code == 401
    do_login(client)
    r = client.put("/api/me/profile", json={"headline": " Platform engineer ", "building": "a policy engine",
                                            "technologies": [" Kubernetes", "go", "kubernetes", ""], "interests": ["Climate Data"]}).json()
    assert r["headline"] == "Platform engineer" and r["building"] == "a policy engine"
    assert r["technologies"] == ["kubernetes", "go"] and r["interests"] == ["climate data"]
    r = client.put("/api/me/profile", json={"interests": []}).json()  # clearing one list leaves the others alone
    assert r["interests"] == [] and r["technologies"] == ["kubernetes", "go"] and r["headline"] == "Platform engineer"
    assert client.put("/api/me/profile", json={"name": "  "}).status_code == 400
    assert client.put("/api/me/profile", json={"url": "https://example.com/x"}).status_code == 400
    assert client.put("/api/me/profile", json={"name": "Jane T", "url": "https://www.linkedin.com/in/jane-t"}).status_code == 200
    me = client.get("/api/me").json()["user"]
    assert me["name"] == "Jane T" and me["url"].endswith("jane-t") and me["technologies"] == ["kubernetes", "go"]
    assert me["email"] == "jane@example.com"  # login identity untouched
    # edits take part in matching: the room graph links on the shared technology
    seed_room(client)
    g = client.get("/api/room-graph").json()
    me_edges = [e for e in g["edges"] if "li-abc123" in (e["from"], e["to"])]
    assert me_edges and any("kubernetes" in e["shared"] for e in me_edges)
