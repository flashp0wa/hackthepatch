"""Event agenda and 'Interests': rank the keynotes against the signed-in attendee's profile.

The LLM gets the profile and the sessions in one call and returns a 0-100 fit per session with a reason.
If the model is unreachable the text-overlap score below is used instead: sessions carry no tags, only a
title, a speaker and an abstract, so the fallback looks for the attendee's own tags in that text.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .matching import tag_set
from .models import Profile

SESSIONS_FILE = Path(__file__).resolve().parent.parent / "data" / "event_sessions.json"

INTERESTS_PROMPT = """An attendee's LinkedIn-derived profile and a conference agenda follow.
Score how much each session fits this specific attendee: their technologies, interests, what they can offer,
what they are looking for, and their active project. Return ONLY JSON:
{"matches": [{"id": "<session id>", "score": <0-100>, "reason": "<one sentence tied to their profile>"}]}
Include every session exactly once. Do not invent facts about the attendee."""


def load_sessions() -> list[dict]:
    return json.loads(SESSIONS_FILE.read_text())


def profile_tags(profile: Profile) -> set[str]:
    tags = tag_set(profile.technologies) | tag_set(profile.interests) | tag_set(profile.can_offer) | tag_set(profile.looking_for)
    if profile.project:
        tags |= tag_set(profile.project.domains) | tag_set(profile.project.needs)
    return tags


def session_text(session: dict) -> str:
    """Title, track, speaker and abstract as one lowercase string; hyphens become spaces so 'multi-tenant' == 'multi tenant'."""
    text = " ".join(str(session.get(k, "")) for k in ("title", "track", "speaker", "abstract")).lower()
    return re.sub(r"[\s-]+", " ", text)


def tag_in_text(tag: str, text: str) -> bool:
    """The whole tag appears in the text as a phrase (plural tolerated). Stricter than tags_overlap on purpose:
    a 400-word abstract contains 'engineers' and 'data' somewhere, and those must not count as hits."""
    phrase = re.escape(re.sub(r"[\s-]+", " ", tag).rstrip("s"))
    return re.search(rf"\b{phrase}(?:s|es)?\b", text) is not None


FULL_SCORE_HITS = 3  # three of the attendee's tags found in the session text counts as a full match


def overlap_rank(profile: Profile, sessions: list[dict]) -> list[dict]:
    """Deterministic fallback: how many of the attendee's tags appear in the session text."""
    mine = profile_tags(profile)
    ranked = []
    for s in sessions:
        text = session_text(s)
        hits = {t for t in mine if len(t) >= 3 and tag_in_text(t, text)}
        score = min(100, round(100 * len(hits) / FULL_SCORE_HITS))
        reason = ("matches " + ", ".join(sorted(hits))) if hits else "no overlap with the profile"
        ranked.append({**s, "score": score, "reason": reason, "hits": sorted(hits)})
    ranked.sort(key=lambda s: (-s["score"], s["time"]))
    return ranked


def rank_sessions(llm, profile: Profile, sessions: list[dict]) -> tuple[list[dict], str]:
    """LLM-ranked sessions, each with score, reason and the tag hits, plus how they were ranked: "llm", or
    "fallback: <error>" when the model could not be used and overlap_rank stood in."""
    by_id = {s["id"]: s for s in sessions}
    fallback = {s["id"]: s for s in overlap_rank(profile, sessions)}
    agenda = "\n".join(f"- id={s['id']} | {s['title']} | {s['speaker']}\n  {s['abstract']}" for s in sessions)
    try:
        data = llm._chat_json(INTERESTS_PROMPT, f"Attendee:\n{profile.text_for_embedding()}\n\nAgenda:\n{agenda}")
        matches = {m["id"]: m for m in data.get("matches", []) if isinstance(m, dict) and m.get("id") in by_id}
        if not matches:
            raise ValueError("no usable matches in the model reply")
    except Exception as exc:
        return list(fallback.values()), f"fallback: {type(exc).__name__}: {str(exc)[:200]}"
    ranked = []
    for sid, s in by_id.items():
        m = matches.get(sid, {})
        score = max(0, min(100, int(float(m.get("score", fallback[sid]["score"])))))
        ranked.append({**s, "score": score, "reason": str(m.get("reason") or fallback[sid]["reason"]),
                       "hits": fallback[sid]["hits"]})
    ranked.sort(key=lambda s: (-s["score"], s["time"]))
    return ranked, "llm"
