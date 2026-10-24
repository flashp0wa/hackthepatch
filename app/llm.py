"""OpenAI-compatible LLM access: profile extraction, embeddings, question ranking.

Works against any server that speaks the OpenAI chat/embeddings API. Embeddings
fall back to a local hashed vector when the endpoint has none, so the demo keeps
working with chat-only servers.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from openai import OpenAI

from .config import Settings
from .models import Profile, Project, make_person_id, normalize_tag, normalize_role

EXTRACTION_PROMPT = """You turn a LinkedIn profile into a compact JSON object for an event-matching app.
Return ONLY a JSON object with these keys:
- name: string
- role: which group this attendee belongs to, from their About statement: "investor" (invests, writes cheques, runs a
  fund or syndicate), "founder" (building a company or product), "hiring" (has open roles to fill), "open_to_work"
  (seeking a role), or "connecting" (none of the above). Pick exactly one.
- statement: the sentence or two in About where they say what they want from the event: what they invest in, which
  roles they are hiring for, which roles they seek, or what they are building ("" if there is none)
- headline: one line, current role and company
- summary: one sentence about the person
- building: one sentence on what they are currently building or working on ("" if unknown)
- technologies: list of concrete technologies, tools, languages, frameworks they have used (lowercase, short)
- interests: list of domains or topics they care about (lowercase, short, e.g. "developer tools", "climate", "robotics")
- can_offer: list of roles or skills they can bring to a collaboration (lowercase, e.g. "backend engineering", "product design", "fundraising")
- looking_for: list of roles or skills they appear to need or be seeking, inferred from gaps, open roles, "looking for", hiring, cofounder search, or an unfinished project (lowercase; [] if nothing is implied)
- companies: list of employers, past and present (as written)
- schools: list of schools (as written)
Keep each list to at most 10 items.
Fill looking_for and can_offer by group, because matching pairs people on gaps:
- investor: looking_for = the themes and stages they invest in (e.g. "pre-seed", "fintech", "developer tools");
  can_offer = "funding" plus any operating expertise they mention.
- founder: building = the product; looking_for = the roles, skills or money the company needs ("cofounder", "funding",
  "frontend engineering"); can_offer = the founder's own skills.
- hiring: looking_for = the roles they are hiring for, one tag per role ("backend engineer", "ml engineer");
  can_offer = "open roles" plus their own expertise.
- open_to_work: looking_for = the roles they seek, one tag per role; can_offer = their skills.
- connecting: interests carry the weight; looking_for and can_offer as the text supports.
The text is what the member exported or pasted (LinkedIn's Save-to-PDF, consented profile data, or free text), so
it may be partial. Infer technologies, interests and can_offer from the headline, employers and their industry,
certifications, courses and recommendations when the text supports it; an inference the material supports is better
than an empty list. Mark nothing as certain that is not, do not invent employers or schools, and leave out anything
whose name is missing rather than writing a placeholder."""

ROUTING_PROMPT = """An attendee at a hackathon asked the room a question. You get the question and a shortlist of attendees.
Pick the 3 people best placed to answer it. Return ONLY JSON: {"picks": [{"id": "...", "reason": "one short sentence"}]}.
Use only ids from the shortlist."""

PROJECT_PROMPT = """An attendee at a hackathon describes what they are actively working on. You also get their profile.
Read the project for what is likely to block it and who could help. Return ONLY JSON with:
- summary: one sentence restating the project
- pain_points: list of short phrases naming likely blockers, gaps or risks given this person's background (max 6)
- needs: list of roles or skills that would unblock the project (lowercase, short, e.g. "frontend engineering", "product design", "go-to-market", max 8)
- domains: list of topic areas the project lives in (lowercase, max 5)
- connection_ideas: list of short sentences, each describing one kind of person worth meeting and why (max 4)
Base pain points on the description and the profile; do not invent facts."""

HASH_DIM = 256


def parse_json_object(text: str) -> dict:
    """Tolerant JSON extraction: strips code fences and anything around the outer braces."""
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(cleaned[start : end + 1])


def hash_embedding(text: str, dim: int = HASH_DIM) -> list[float]:
    """Deterministic bag-of-words vector; a stand-in when no embeddings endpoint exists."""
    vec = [0.0] * dim
    for token in re.findall(r"[a-z0-9+#.]+", text.lower()):
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


PLACEHOLDERS = {"unknown", "unknown school", "unknown company", "hidden", "n/a", "none", "not specified", "undefined"}


def _names(value: Any) -> list[str]:
    """Employer/school names as written, minus the placeholders a model writes for hidden entries."""
    out: list[str] = []
    for item in value or []:
        name = str(item).strip()
        if name and name.lower().strip("*. ") not in PLACEHOLDERS and not set(name) <= set("*? ") and name not in out:
            out.append(name)
    return out[:10]


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: list[str] = []
    for item in value:
        tag = normalize_tag(str(item))
        if tag and tag not in seen:
            seen.append(tag)
    return seen[:10]


class LLM:
    def __init__(self, settings: Settings, client: Any | None = None):
        self.settings = settings
        self.client = client or OpenAI(
            base_url=settings.openai_base_url, api_key=settings.openai_api_key or "not-set"
        )

    # ---- chat helpers -------------------------------------------------------

    def _chat_json(self, system: str, user: str) -> dict:
        response = self.client.chat.completions.create(
            model=self.settings.chat_model,
            temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return parse_json_object(response.choices[0].message.content or "")

    # ---- public API ---------------------------------------------------------

    def extract_profile(self, text: str, url: str = "", name_hint: str = "") -> Profile:
        """One LLM call turning profile text (PDF export, consented data, pasted text) into a Profile (no embedding yet)."""
        data = self._chat_json(EXTRACTION_PROMPT, text[:8000])
        name = str(data.get("name") or name_hint or "Unknown")
        return Profile(
            id=make_person_id(name, url),
            name=name,
            url=url,
            headline=str(data.get("headline") or ""),
            summary=str(data.get("summary") or ""),
            building=str(data.get("building") or ""),
            technologies=_clean_list(data.get("technologies")),
            interests=_clean_list(data.get("interests")),
            can_offer=_clean_list(data.get("can_offer")),
            looking_for=_clean_list(data.get("looking_for")),
            companies=_names(data.get("companies")),
            schools=_names(data.get("schools")),
            role=normalize_role(data.get("role")),
            statement=str(data.get("statement") or "")[:600],
        )

    def analyze_project(self, description: str, profile: Profile) -> Project:
        """One LLM call: project description + profile -> pain points, needs, domains, connection ideas."""
        context = (f"Profile: {profile.name} | {profile.headline}\nSummary: {profile.summary}\n"
                   f"Technologies: {', '.join(profile.technologies)}\nCan offer: {', '.join(profile.can_offer)}\n\n"
                   f"Project description:\n{description[:4000]}")
        data = self._chat_json(PROJECT_PROMPT, context)
        return Project(
            description=description,
            summary=str(data.get("summary") or ""),
            pain_points=[str(x).strip() for x in data.get("pain_points") or [] if str(x).strip()][:6],
            needs=_clean_list(data.get("needs")),
            domains=_clean_list(data.get("domains")),
            connection_ideas=[str(x).strip() for x in data.get("connection_ideas") or [] if str(x).strip()][:4],
        )

    def embed(self, text: str) -> list[float]:
        """Embedding from the endpoint; hashed fallback if the endpoint cannot embed."""
        try:
            response = self.client.embeddings.create(model=self.settings.embed_model, input=text)
            return list(response.data[0].embedding)
        except Exception:
            return hash_embedding(text)

    def rank_for_question(self, question: str, candidates: list[Profile], top: int = 3) -> list[dict]:
        """Ask the model to pick the best `top` among a pre-filtered shortlist. Falls back to shortlist order."""
        shortlist = "\n".join(
            f"- id={p.id} | {p.name} | {p.headline} | tech: {', '.join(p.technologies)} | "
            f"interests: {', '.join(p.interests)} | offers: {', '.join(p.can_offer)}"
            for p in candidates
        )
        by_id = {p.id: p for p in candidates}
        try:
            data = self._chat_json(ROUTING_PROMPT, f"Question: {question}\n\nShortlist:\n{shortlist}")
            picks = [
                {"id": pk["id"], "name": by_id[pk["id"]].name, "reason": str(pk.get("reason", ""))}
                for pk in data.get("picks", [])
                if isinstance(pk, dict) and pk.get("id") in by_id
            ][:top]
            if picks:
                return picks
        except Exception:
            pass
        return [{"id": p.id, "name": p.name, "reason": "closest profile match"} for p in candidates[:top]]
