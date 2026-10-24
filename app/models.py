"""Data shapes shared by the store, the matchers and the API."""
from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel, Field


def normalize_tag(value: str) -> str:
    """Lowercase, trim, collapse whitespace. Used for every skill/interest/company label."""
    return re.sub(r"\s+", " ", value.strip().lower())


ROLES = ("investor", "founder", "hiring", "open_to_work", "connecting")
ROLE_LABELS = {"investor": "Investor", "founder": "Founder", "hiring": "Hiring",
               "open_to_work": "Open to work", "connecting": "Building connections"}
_ROLE_ALIASES = {"vc": "investor", "founder/ceo": "founder", "co founder": "founder", "cofounder": "founder",
                 "looking for work": "open_to_work", "building connections": "connecting", "networking": "connecting",
                 "just connecting": "connecting", "connector": "connecting"}


def normalize_role(value: str | None) -> str:
    """Map whatever the model or a form sent onto one of the five attendee groups; unknown -> connecting."""
    key = re.sub(r"[\s_-]+", " ", str(value or "").strip().lower())
    if key.replace(" ", "_") in ROLES:
        return key.replace(" ", "_")
    if key in _ROLE_ALIASES:
        return _ROLE_ALIASES[key]
    for needle, role in (("invest", "investor"), ("angel", "investor"), ("found", "founder"), ("recruit", "hiring"),
                         ("hiring", "hiring"), ("open to", "open_to_work"), ("seeking", "open_to_work"), ("job", "open_to_work")):
        if needle in key:
            return role
    return "connecting"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "person"


def make_person_id(name: str, url: str = "") -> str:
    """Stable id: LinkedIn slug when a URL is given, otherwise name + short hash."""
    if url:
        match = re.search(r"linkedin\.com/in/([^/?#]+)", url)
        if match:
            return slugify(match.group(1))
    digest = hashlib.sha1(f"{name}|{url}".encode()).hexdigest()[:6]
    return f"{slugify(name)}-{digest}"


class Project(BaseModel):
    """What the attendee is working on right now, plus what the LLM read out of it."""
    description: str
    summary: str = ""
    pain_points: list[str] = Field(default_factory=list)   # likely blockers / gaps / risks
    needs: list[str] = Field(default_factory=list)         # roles or skills that would unblock them
    domains: list[str] = Field(default_factory=list)       # topic areas, matched against interests
    connection_ideas: list[str] = Field(default_factory=list)  # kinds of people worth meeting
    updated_at: float = 0.0


class Profile(BaseModel):
    id: str
    name: str
    headline: str = ""
    url: str = ""
    email: str = ""
    picture: str = ""
    linkedin_sub: str = ""      # OIDC subject when the attendee signed in
    role: str = "connecting"    # investor | founder | hiring | open_to_work | connecting
    statement: str = ""         # the About sentence(s) saying what they want from the room: thesis, roles, product
    project: Project | None = None
    summary: str = ""
    building: str = ""
    technologies: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    can_offer: list[str] = Field(default_factory=list)
    looking_for: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    schools: list[str] = Field(default_factory=list)
    embedding: list[float] = Field(default_factory=list)

    def text_for_embedding(self) -> str:
        parts = [
            self.name,
            self.headline,
            f"role: {ROLE_LABELS.get(self.role, self.role)}",
            self.statement,
            self.summary,
            f"building: {self.building}" if self.building else "",
            "technologies: " + ", ".join(self.technologies),
            "interests: " + ", ".join(self.interests),
            "can offer: " + ", ".join(self.can_offer),
            "looking for: " + ", ".join(self.looking_for),
        ]
        if self.project:
            parts += [f"working on: {self.project.description[:800]}",
                      "pain points: " + "; ".join(self.project.pain_points),
                      "needs: " + ", ".join(self.project.needs)]
        return "\n".join(p for p in parts if p)

    def all_needs(self) -> list[str]:
        """Profile-level gaps plus what the active project needs; this is what matching pairs on."""
        needs = list(self.looking_for)
        if self.project:
            needs += [n for n in self.project.needs if n not in needs]
        return needs

    def merge_scraped(self, scraped: "Profile") -> "Profile":
        """Fill this profile from a scrape while keeping identity, login and project data."""
        data = scraped.model_dump(exclude={"id", "email", "picture", "linkedin_sub", "project", "embedding"})
        data["name"] = self.name or scraped.name
        data["url"] = scraped.url or self.url
        return self.model_copy(update=data)

    def public(self) -> dict:
        """Everything except the embedding vector."""
        return self.model_dump(exclude={"embedding"})


class Question(BaseModel):
    id: str
    text: str
    asker_id: str = ""
    routed_to: list[dict] = Field(default_factory=list)  # [{"id", "name", "reason"}]
