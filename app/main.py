"""FastAPI app: attendees in, four features out, plus LinkedIn login and the signed-in attendee's own page.

`create_app()` takes injected store/llm/oidc for tests.
"""
from __future__ import annotations

import json
import secrets
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from .auth import LinkedInOIDC, OIDCError, snapshot_to_text
from .events import load_sessions, rank_sessions
from .config import Settings, load_settings
from .graph import Store, make_store
from .llm import LLM
from .matching import complementary_matches, project_connections, route_question
from .models import ROLES, Profile, Question, make_person_id, normalize_tag, slugify
from .roomgraph import build_room_graph

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"


class TextProfileRequest(BaseModel):
    name: str
    text: str
    url: str = ""


class QuestionRequest(BaseModel):
    text: str
    asker_id: str = ""


class ProjectRequest(BaseModel):
    description: str


class ProfileUpdateRequest(BaseModel):
    """Editable fields on the signed-in attendee's profile; omitted fields are left unchanged."""
    name: str | None = None
    role: str | None = None
    statement: str | None = None
    headline: str | None = None
    summary: str | None = None
    building: str | None = None
    url: str | None = None
    technologies: list[str] | None = None
    interests: list[str] | None = None
    can_offer: list[str] | None = None
    looking_for: list[str] | None = None


class DevLoginRequest(BaseModel):
    name: str
    email: str = ""


def create_app(settings: Settings | None = None, store: Store | None = None, llm: LLM | None = None,
               oidc: LinkedInOIDC | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="hackthepatch")
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax", https_only=False)
    app.state.settings = settings
    app.state.store = store or make_store(settings)
    app.state.llm = llm or LLM(settings)
    app.state.oidc = oidc or LinkedInOIDC(settings.linkedin_client_id, settings.linkedin_client_secret,
                                          settings.linkedin_redirect_uri, settings.linkedin_scopes)
    app.state.jobs: dict[str, dict] = {}

    # ---- helpers ------------------------------------------------------------

    def ingest(profile: Profile) -> Profile:
        profile.embedding = app.state.llm.embed(profile.text_for_embedding())
        app.state.store.upsert_person(profile)
        return profile

    def current_user(request: Request) -> Profile:
        uid = request.session.get("uid")
        person = app.state.store.get_person(uid) if uid else None
        if not person:
            request.session.pop("uid", None)
            raise HTTPException(401, "not signed in")
        return person

    def run_snapshot_job(job_id: str, person_id: str, text: str) -> None:
        """Consented LinkedIn data (Member Data Portability) -> LLM extraction -> merge into the attendee."""
        job = app.state.jobs[job_id]
        try:
            job["status"] = "extracting"
            existing = app.state.store.get_person(person_id)
            scraped = app.state.llm.extract_profile(text, url=existing.url if existing else "",
                                                    name_hint=existing.name if existing else "")
            profile = existing.merge_scraped(scraped) if existing else scraped
            job.update(status="done", person=ingest(profile).public())
        except Exception as exc:
            job.update(status="failed", error=str(exc))

    def sign_in(request: Request, sub: str, name: str, email: str = "", picture: str = "") -> Profile:
        """Find or create the attendee for an OIDC subject and put them in the session."""
        person = app.state.store.find_by_sub(sub)
        if person:
            person = person.model_copy(update={"email": email or person.email, "picture": picture or person.picture})
            app.state.store.upsert_person(person)
        else:
            person = ingest(Profile(id=f"li-{slugify(sub)}", name=name, email=email, picture=picture, linkedin_sub=sub))
        request.session["uid"] = person.id
        return person

    # ---- auth: Sign in with LinkedIn (OIDC) ---------------------------------

    @app.get("/auth/login", include_in_schema=False)
    def login(request: Request):
        if not app.state.oidc.enabled:
            raise HTTPException(503, "LinkedIn login is not configured (LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET)")
        # The session cookie is bound to the host the browser is on. LinkedIn redirects to the registered
        # callback host, so start the flow there (127.0.0.1 vs localhost is the usual mismatch).
        target = urlsplit(app.state.oidc.redirect_uri)
        if target.netloc and request.url.netloc != target.netloc:
            return RedirectResponse(f"{target.scheme}://{target.netloc}/auth/login", status_code=302)
        state = secrets.token_urlsafe(16)
        request.session["oauth_state"] = state
        return RedirectResponse(app.state.oidc.authorize_url(state), status_code=302)

    @app.get("/auth/callback", include_in_schema=False)
    def callback(request: Request, background: BackgroundTasks, code: str = "", state: str = "",
                 error: str = "", error_description: str = ""):
        if error:
            raise HTTPException(400, f"LinkedIn returned {error}: {error_description}")
        if not state or state != request.session.pop("oauth_state", None):
            raise HTTPException(400, "state mismatch; start the login again from "
                                     f"{urlsplit(app.state.oidc.redirect_uri).scheme}://{urlsplit(app.state.oidc.redirect_uri).netloc}/")
        try:
            token = app.state.oidc.exchange_code(code)
            info = app.state.oidc.userinfo(token)
            url = app.state.oidc.profile_url(token)
            snapshot = app.state.oidc.snapshot(token)  # {} unless the member consented to data portability
        except OIDCError as exc:
            raise HTTPException(502, str(exc)) from exc
        person = sign_in(request, info["sub"], info.get("name") or "LinkedIn member",
                         info.get("email", ""), info.get("picture", ""))
        # Auto-populate from consented data (Member Data Portability) when the member could grant it.
        if snapshot:
            job_id = uuid.uuid4().hex[:8]
            app.state.jobs[job_id] = {"id": job_id, "url": "linkedin:member-data-portability", "person_id": person.id,
                                      "status": "queued", "created": time.time()}
            background.add_task(run_snapshot_job, job_id, person.id, snapshot_to_text(snapshot))
        # Otherwise keep the profile URL when LinkedIn returned it; the attendee imports the rest (PDF or text).
        elif url and not person.url:
            app.state.store.upsert_person(person.model_copy(update={"url": url}))
        return RedirectResponse("/#me", status_code=302)

    @app.post("/auth/dev-login")
    def dev_login(req: DevLoginRequest, request: Request) -> dict:
        """Local testing without a LinkedIn app. Only when DEV_LOGIN=true."""
        if not settings.dev_login:
            raise HTTPException(404, "dev login disabled")
        return sign_in(request, f"dev-{slugify(req.name)}", req.name, req.email).public()

    @app.post("/auth/logout")
    def logout(request: Request) -> dict:
        request.session.clear()
        return {"signed_out": True}

    # ---- me: the signed-in attendee's own page ---------------------------------

    @app.get("/api/me")
    def me(request: Request) -> dict:
        uid = request.session.get("uid")
        person = app.state.store.get_person(uid) if uid else None
        jobs = [j for j in app.state.jobs.values() if person and j.get("person_id") == person.id]
        return {"user": person.public() if person else None,
                "oidc_enabled": app.state.oidc.enabled, "dev_login": settings.dev_login,
                "auto_profile_url": app.state.oidc.can_read_profile_url,
                "portability": app.state.oidc.can_read_snapshot,
                "job": max(jobs, key=lambda j: j["created"]) if jobs else None}

    @app.put("/api/me/profile")
    def me_profile(req: ProfileUpdateRequest, request: Request) -> dict:
        """Save edits to the signed-in attendee's profile (text fields and tag lists), then re-embed."""
        person = current_user(request)
        update: dict = {}
        for field, value in req.model_dump(exclude_none=True).items():
            if isinstance(value, list):
                cleaned: list[str] = []
                for v in value:
                    tag = normalize_tag(str(v))
                    if tag and tag not in cleaned:
                        cleaned.append(tag)
                update[field] = cleaned[:30]
            else:
                update[field] = str(value).strip()[:2000]
        if "name" in update and not update["name"]:
            raise HTTPException(400, "name cannot be empty")
        if "role" in update:
            if update["role"] not in ROLES:
                raise HTTPException(400, f"role must be one of {', '.join(ROLES)}")
        if update.get("url") and "linkedin.com/in/" not in update["url"]:
            raise HTTPException(400, "url must be a linkedin.com/in/... profile URL")
        return ingest(person.model_copy(update=update)).public()

    @app.put("/api/me/tags", include_in_schema=False)
    def me_tags(req: ProfileUpdateRequest, request: Request) -> dict:
        return me_profile(req, request)

    @app.put("/api/me/project")
    def me_project(req: ProjectRequest, request: Request) -> dict:
        person = current_user(request)
        description = req.description.strip()
        if not description:
            raise HTTPException(400, "describe the project first")
        try:
            project = app.state.llm.analyze_project(description, person)
        except Exception as exc:
            raise HTTPException(502, f"LLM analysis failed: {exc}") from exc
        project.updated_at = time.time()
        person = ingest(person.model_copy(update={"project": project}))
        return {"project": project.model_dump(),
                "connections": [c.public() for c in project_connections(person, app.state.store.list_persons())]}

    @app.get("/api/me/connections")
    def me_connections(request: Request) -> list[dict]:
        person = current_user(request)
        return [c.public() for c in project_connections(person, app.state.store.list_persons())]

    # ---- event page: agenda + "Interests" --------------------------------------

    @app.get("/api/event")
    def event() -> dict:
        return {"name": "hackthepatch keynotes", "sessions": load_sessions()}

    @app.post("/api/event/interests")
    def event_interests(request: Request) -> dict:
        """Send the signed-in attendee's profile with the agenda; get the sessions back ranked by fit."""
        person = current_user(request)
        ranked, source = rank_sessions(app.state.llm, person, load_sessions())
        return {"person": person.public(), "sessions": ranked, "source": source}

    # ---- attendees ----------------------------------------------------------

    @app.post("/api/attendees/text")
    def add_from_text(req: TextProfileRequest) -> dict:
        try:
            profile = app.state.llm.extract_profile(req.text, url=req.url, name_hint=req.name)
        except Exception as exc:
            raise HTTPException(502, f"LLM extraction failed: {exc}") from exc
        profile.name = req.name or profile.name
        profile.id = make_person_id(profile.name, req.url)
        return ingest(profile).public()

    @app.get("/api/attendees")
    def list_attendees() -> list[dict]:
        return [p.public() for p in app.state.store.list_persons()]

    @app.get("/api/attendees/{person_id}")
    def get_attendee(person_id: str) -> dict:
        person = app.state.store.get_person(person_id)
        if not person:
            raise HTTPException(404, "unknown attendee")
        return person.public()

    @app.delete("/api/attendees/{person_id}")
    def delete_attendee(person_id: str) -> dict:
        if not app.state.store.delete_person(person_id):
            raise HTTPException(404, "unknown attendee")
        return {"deleted": person_id}

    @app.delete("/api/attendees")
    def reset() -> dict:
        app.state.store.clear()
        app.state.jobs.clear()
        return {"cleared": True}

    # ---- feature 1: complementary matching -----------------------------------

    @app.get("/api/matches/{person_id}")
    def matches(person_id: str, top: int = 5) -> dict:
        person = app.state.store.get_person(person_id)
        if not person:
            raise HTTPException(404, "unknown attendee")
        found = complementary_matches(person, app.state.store.list_persons(), top=top)
        return {"person": person.public(), "matches": [m.public() for m in found]}

    # ---- feature 2: ask the room ---------------------------------------------

    @app.post("/api/questions")
    def ask(req: QuestionRequest) -> dict:
        text = req.text.strip()
        if not text:
            raise HTTPException(400, "empty question")
        profiles = [p for p in app.state.store.list_persons() if p.id != req.asker_id]
        if not profiles:
            raise HTTPException(409, "no attendees to route to")
        shortlist = route_question(text, app.state.llm.embed(text), profiles)
        picks = app.state.llm.rank_for_question(text, [c.person for c in shortlist])
        hits = {c.person.id: c.hits for c in shortlist}
        for pick in picks:
            pick["hits"] = hits.get(pick["id"], [])
        question = Question(id=f"q-{int(time.time() * 1000)}-{uuid.uuid4().hex[:4]}", text=text,
                            asker_id=req.asker_id, routed_to=picks)
        app.state.store.save_question(question)
        return question.model_dump()

    @app.get("/api/questions")
    def questions() -> list[dict]:
        return [q.model_dump() for q in reversed(app.state.store.list_questions())]

    @app.get("/api/inbox/{person_id}")
    def inbox(person_id: str) -> list[dict]:
        """Notifications: questions routed to this attendee."""
        return [q.model_dump() for q in reversed(app.state.store.list_questions())
                if any(r["id"] == person_id for r in q.routed_to)]

    # ---- feature 3: live room graph ------------------------------------------

    @app.get("/api/room-graph")
    def room_graph() -> dict:
        return build_room_graph(app.state.store.list_persons())

    # ---- UI -----------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


# Run with:  uvicorn app.main:create_app --factory --reload
