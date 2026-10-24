"""The three matching behaviours, as pure functions over Profile lists.

complementary_matches  "who do you need" rather than "who is like you"
route_question         shortlist attendees for an "ask the room" question
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .models import Profile, normalize_tag

STOPWORDS = {"anyone", "used", "using", "with", "have", "has", "does", "know", "about", "what", "which", "who",
             "that", "this", "from", "into", "production", "experience", "here", "there", "some", "someone"}


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


# Word-level aliases applied to every tag before comparison, so a role written one way meets a skill written
# another: "ml engineer" -> "machine learning engineer" (meets "machine learning"), "pre-seed investors" ->
# "pre-seed funding" (meets an investor's "funding"), "k8s" -> "kubernetes".
WORD_ALIASES = {"ml": "machine learning", "ai/ml": "machine learning", "k8s": "kubernetes", "devrel": "developer relations",
                "sdet": "test automation", "pm": "product management", "ux": "product design", "ui/ux": "product design",
                "investor": "funding", "investors": "funding", "angel": "funding", "angels": "funding", "vc": "funding",
                "vcs": "funding", "cheque": "funding", "check": "funding", "fe": "frontend",
                "be": "backend", "swe": "software engineering", "cofounder": "cofounder", "co-founder": "cofounder"}


def canonical_tag(value: str) -> str:
    words = [WORD_ALIASES.get(w, w) for w in normalize_tag(value).split(" ")]
    return re.sub(r"\s+", " ", " ".join(words)).strip()


def tag_set(items: list[str]) -> set[str]:
    return {canonical_tag(i) for i in items if i and i.strip()}


def tags_overlap(a: str, b: str) -> bool:
    """'designer' matches 'product design'; 'go' does not match 'django'."""
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < 4:
        return False
    stem = short[:-2] if short.endswith(("er", "ed")) and len(short) >= 7 else short.rstrip("s")  # designer -> design; seed stays seed
    return len(stem) >= 4 and re.search(rf"\b{re.escape(stem)}", long_) is not None


def matched_tags(needs: set[str], offers: set[str]) -> set[str]:
    """Needs that at least one offer satisfies (returned as the need label)."""
    return {n for n in needs if any(tags_overlap(n, o) for o in offers)}


# ---- 1. complementary matching ------------------------------------------------
#
# Every attendee belongs to one group (investor, founder, hiring, open_to_work, connecting) and their
# About statement says what they want from the room. Matching pairs on gaps, and what counts as an
# "offer" or a "need" depends on the pair:
#   investor  <-> founder       the thesis (investor.looking_for) against what the founder builds
#                               (interests + project domains); the investor offers funding
#   hiring    <-> open_to_work  roles hired for against the candidate's skills, and the roles sought
#                               against the roles on offer
#   founder   <-> open_to_work  the roles the company needs against the candidate's skills
# Everyone else matches on plain skills: what I lack that you offer, and the reverse.

INVESTOR_OFFERS = {"funding", "investment", "capital", "pre-seed funding", "seed funding", "investor intros"}
HIRING_OFFERS = {"open roles", "jobs", "hiring"}
PAIR_BONUS = {frozenset({"investor", "founder"}): 1.5, frozenset({"hiring", "open_to_work"}): 1.5,
              frozenset({"founder", "open_to_work"}): 0.75}
PAIR_LABEL = {frozenset({"investor", "founder"}): "investor \u2194 founder",
              frozenset({"hiring", "open_to_work"}): "hiring \u2194 open to work",
              frozenset({"founder", "open_to_work"}): "founder \u2194 open to work"}


def offers_of(p: Profile, to: Profile) -> set[str]:
    """What p can give `to`, given both groups. The viewer's group decides what counts as an offer at all:
    an investor's thesis is matched only against what founders build, a hiring manager's roles only against
    candidates, and a candidate's sought roles only against jobs (hiring managers) or the roles a founder needs."""
    if to.role == "investor":
        if p.role != "founder":
            return set()
        out = tag_set(p.interests) | tag_set(p.looking_for)        # domains they build in, plus stage words like "pre-seed"
        if p.project:
            out |= tag_set(p.project.domains)
        return out
    if to.role == "hiring":
        if p.role != "open_to_work":
            return set()
        return tag_set(p.can_offer) | tag_set(p.technologies) | tag_set(p.looking_for)   # the roles they seek describe what they are
    if to.role == "open_to_work":
        if p.role == "hiring":
            return tag_set(p.looking_for) | HIRING_OFFERS
        if p.role == "founder":
            return tag_set(p.looking_for)
        return set()
    out = tag_set(p.can_offer) | tag_set(p.technologies)            # founders and connectors: plain skills
    if p.role == "investor":
        out |= INVESTOR_OFFERS
    if p.role == "open_to_work":
        out |= tag_set(p.looking_for)                               # a candidate is the role they seek
    return out


def needs_of(p: Profile) -> set[str]:
    return tag_set(p.all_needs())


@dataclass
class Match:
    person: Profile
    score: float
    fills: list[str]          # their offers that cover my needs
    they_need: list[str]      # my offers that cover their needs
    overlap: list[str]        # what we both already do (penalised: no duplicate skill sets)
    pair: str = ""            # the group pairing that drove the score, when one did

    def public(self) -> dict:
        return {"person": self.person.public(), "score": round(self.score, 2), "fills": self.fills,
                "they_need": self.they_need, "overlap": self.overlap, "pair": self.pair}


def complementary_matches(person: Profile, others: list[Profile], top: int = 5) -> list[Match]:
    my_needs = needs_of(person)
    results: list[Match] = []
    for other in others:
        if other.id == person.id:
            continue
        fills = matched_tags(my_needs, offers_of(other, person))
        they_need = matched_tags(needs_of(other), offers_of(person, other))
        if not fills and not they_need:
            continue
        overlap = matched_tags(tag_set(person.can_offer), tag_set(other.can_offer))
        score = 2.0 * len(fills) + 1.5 * len(they_need) - 0.5 * len(overlap)
        if fills and they_need:
            score += 1.0  # mutual: each fills a gap of the other
        pair = frozenset({person.role, other.role})
        score += PAIR_BONUS.get(pair, 0.0)
        results.append(Match(other, score, sorted(fills), sorted(they_need), sorted(overlap), PAIR_LABEL.get(pair, "")))
    results.sort(key=lambda m: (-m.score, m.person.name))
    return results[:top]


# ---- 2. ask the room -----------------------------------------------------------

@dataclass
class Candidate:
    person: Profile
    score: float
    hits: list[str] = field(default_factory=list)


def question_keywords(question: str) -> set[str]:
    words = {w for w in re.findall(r"[a-z0-9+#.]+", question.lower()) if len(w) >= 3}
    return words - STOPWORDS


def route_question(question: str, question_embedding: list[float], profiles: list[Profile], shortlist: int = 8) -> list[Candidate]:
    """Embedding similarity plus explicit keyword hits on skills/interests. Returns the shortlist for the LLM."""
    keywords = question_keywords(question)
    ranked: list[Candidate] = []
    for p in profiles:
        tags = tag_set(p.technologies) | tag_set(p.interests) | tag_set(p.can_offer)
        hits = sorted({t for t in tags for k in keywords if tags_overlap(k, t) or k in t.split()})
        score = cosine(question_embedding, p.embedding) + 0.25 * len(hits)
        ranked.append(Candidate(p, score, hits))
    ranked.sort(key=lambda c: (-c.score, c.person.name))
    return ranked[:shortlist]


# ---- 3. active project: who in the room can unblock it --------------------------

@dataclass
class Connection:
    person: Profile
    covers: list[str]          # project needs this person can cover
    shared_domains: list[str]  # project domains they are interested in
    score: float

    def public(self) -> dict:
        return {"person": self.person.public(), "covers": self.covers, "shared_domains": self.shared_domains,
                "score": round(self.score, 2)}


def project_connections(person: Profile, others: list[Profile], top: int = 6) -> list[Connection]:
    """Possible connections for the active project: attendees whose offers cover its needs or who share its domain."""
    if not person.project:
        return []
    needs = tag_set(person.project.needs)
    domains = tag_set(person.project.domains)
    results: list[Connection] = []
    for other in others:
        if other.id == person.id:
            continue
        covers = matched_tags(needs, tag_set(other.can_offer) | tag_set(other.technologies))
        shared = matched_tags(domains, tag_set(other.interests))
        if not covers and not shared:
            continue
        score = 2.0 * len(covers) + 1.0 * len(shared)
        if person.embedding and other.embedding:
            score += cosine(person.embedding, other.embedding)
        results.append(Connection(other, sorted(covers), sorted(shared), score))
    results.sort(key=lambda c: (-c.score, c.person.name))
    return results[:top]
