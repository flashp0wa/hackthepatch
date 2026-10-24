"""Persistence. FalkorDB holds the room graph; an in-memory store mirrors the same interface for tests.

Graph model
    (:Person {id, name, headline, url, summary, building, embedding_json})
    (:Person)-[:SKILLED_IN]->(:Skill)      technologies
    (:Person)-[:OFFERS]->(:Skill)          can_offer
    (:Person)-[:NEEDS]->(:Skill)           looking_for
    (:Person)-[:INTERESTED_IN]->(:Interest)
    (:Person)-[:WORKED_AT]->(:Company)
    (:Person)-[:STUDIED_AT]->(:School)
    (:Person)-[:HAS_PAIN_POINT]->(:PainPoint)      from the active project
    (:Question {id, text, asker_id})-[:ROUTED_TO {reason}]->(:Person)
"""
from __future__ import annotations

import json
from typing import Protocol

from .models import Profile, Project, Question

PERSON_FIELDS = ("id", "name", "headline", "url", "summary", "building", "email", "picture", "linkedin_sub",
                 "role", "statement")
LIST_EDGES = {
    # profile field -> (relationship, target label)
    "technologies": ("SKILLED_IN", "Skill"),
    "can_offer": ("OFFERS", "Skill"),
    "looking_for": ("NEEDS", "Skill"),
    "interests": ("INTERESTED_IN", "Interest"),
    "companies": ("WORKED_AT", "Company"),
    "schools": ("STUDIED_AT", "School"),
}


class Store(Protocol):
    def upsert_person(self, profile: Profile) -> None: ...
    def get_person(self, person_id: str) -> Profile | None: ...
    def list_persons(self) -> list[Profile]: ...
    def delete_person(self, person_id: str) -> bool: ...
    def find_by_sub(self, sub: str) -> Profile | None: ...
    def save_question(self, question: Question) -> None: ...
    def list_questions(self) -> list[Question]: ...
    def clear(self) -> None: ...


class InMemoryStore:
    def __init__(self) -> None:
        self.persons: dict[str, Profile] = {}
        self.questions: dict[str, Question] = {}

    def upsert_person(self, profile: Profile) -> None:
        self.persons[profile.id] = profile

    def get_person(self, person_id: str) -> Profile | None:
        return self.persons.get(person_id)

    def list_persons(self) -> list[Profile]:
        return sorted(self.persons.values(), key=lambda p: p.name)

    def delete_person(self, person_id: str) -> bool:
        return self.persons.pop(person_id, None) is not None

    def find_by_sub(self, sub: str) -> Profile | None:
        return next((p for p in self.persons.values() if p.linkedin_sub == sub), None)

    def save_question(self, question: Question) -> None:
        self.questions[question.id] = question

    def list_questions(self) -> list[Question]:
        return list(self.questions.values())

    def clear(self) -> None:
        self.persons.clear()
        self.questions.clear()


class FalkorDBStore:
    def __init__(self, host: str, port: int, graph_name: str) -> None:
        from falkordb import FalkorDB  # imported here so tests never need the driver

        self.db = FalkorDB(host=host, port=port)
        self.graph = self.db.select_graph(graph_name)
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        for label in ("Person", "Skill", "Interest", "Company", "School", "PainPoint", "Question", "Role"):
            key = "id" if label in ("Person", "Question") else "name"
            try:
                self.graph.query(f"CREATE INDEX FOR (n:{label}) ON (n.{key})")
            except Exception:
                pass  # index already exists

    # ---- persons ------------------------------------------------------------

    def upsert_person(self, profile: Profile) -> None:
        params = {f: getattr(profile, f) for f in PERSON_FIELDS}
        params["embedding_json"] = json.dumps(profile.embedding)
        params["project_json"] = profile.project.model_dump_json() if profile.project else ""
        self.graph.query(
            "MERGE (p:Person {id: $id}) SET p.name = $name, p.headline = $headline, p.url = $url, "
            "p.summary = $summary, p.building = $building, p.email = $email, p.picture = $picture, "
            "p.linkedin_sub = $linkedin_sub, p.role = $role, p.statement = $statement, "
            "p.embedding_json = $embedding_json, p.project_json = $project_json",
            params,
        )
        # Replace the person's outgoing profile edges wholesale (questions point *to* persons, so they survive).
        self.graph.query("MATCH (p:Person {id: $id})-[r]->() DELETE r", {"id": profile.id})
        self.graph.query("MATCH (p:Person {id: $id}) MERGE (r:Role {name: $role}) MERGE (p)-[:HAS_ROLE]->(r)",
                         {"id": profile.id, "role": profile.role})
        for field, (rel, label) in LIST_EDGES.items():
            values = getattr(profile, field)
            if values:
                self.graph.query(
                    f"MATCH (p:Person {{id: $id}}) UNWIND $values AS v "
                    f"MERGE (t:{label} {{name: v}}) MERGE (p)-[:{rel}]->(t)",
                    {"id": profile.id, "values": values},
                )
        if profile.project and profile.project.pain_points:
            self.graph.query(
                "MATCH (p:Person {id: $id}) UNWIND $values AS v "
                "MERGE (t:PainPoint {name: v}) MERGE (p)-[:HAS_PAIN_POINT]->(t)",
                {"id": profile.id, "values": profile.project.pain_points},
            )

    def get_person(self, person_id: str) -> Profile | None:
        rows = self._person_rows("WHERE p.id = $id", {"id": person_id})
        return rows[0] if rows else None

    def list_persons(self) -> list[Profile]:
        return self._person_rows("", {})

    def _person_rows(self, where: str, params: dict) -> list[Profile]:
        result = self.graph.query(
            f"MATCH (p:Person) {where} "
            "OPTIONAL MATCH (p)-[r]->(t) WHERE NOT t:Person "
            "WITH p, collect([type(r), t.name]) AS edges "
            "RETURN p.id, p.name, p.headline, p.url, p.summary, p.building, p.email, p.picture, "
            "p.linkedin_sub, p.role, p.statement, p.project_json, p.embedding_json, edges "
            "ORDER BY p.name",
            params,
        )
        profiles = []
        rel_to_field = {rel: field for field, (rel, _) in LIST_EDGES.items()}
        for row in result.result_set:
            (pid, name, headline, url, summary, building, email, picture, sub, role, statement,
             project_json, emb_json, edges) = row
            lists: dict[str, list[str]] = {field: [] for field in LIST_EDGES}
            for rel, target in edges or []:
                if rel in rel_to_field and target:
                    lists[rel_to_field[rel]].append(target)
            profiles.append(
                Profile(
                    id=pid, name=name or "", headline=headline or "", url=url or "", summary=summary or "",
                    building=building or "", email=email or "", picture=picture or "", linkedin_sub=sub or "",
                    role=role or "connecting", statement=statement or "",
                    project=Project.model_validate_json(project_json) if project_json else None,
                    embedding=json.loads(emb_json or "[]"), **lists,
                )
            )
        return profiles

    def delete_person(self, person_id: str) -> bool:
        result = self.graph.query("MATCH (p:Person {id: $id}) DETACH DELETE p", {"id": person_id})
        return bool(result.nodes_deleted)

    def find_by_sub(self, sub: str) -> Profile | None:
        rows = self._person_rows("WHERE p.linkedin_sub = $sub", {"sub": sub})
        return rows[0] if rows else None

    # ---- questions ----------------------------------------------------------

    def save_question(self, question: Question) -> None:
        self.graph.query(
            "MERGE (q:Question {id: $id}) SET q.text = $text, q.asker_id = $asker_id",
            {"id": question.id, "text": question.text, "asker_id": question.asker_id},
        )
        for pick in question.routed_to:
            self.graph.query(
                "MATCH (q:Question {id: $qid}), (p:Person {id: $pid}) "
                "MERGE (q)-[r:ROUTED_TO]->(p) SET r.reason = $reason",
                {"qid": question.id, "pid": pick["id"], "reason": pick.get("reason", "")},
            )

    def list_questions(self) -> list[Question]:
        result = self.graph.query(
            "MATCH (q:Question) OPTIONAL MATCH (q)-[r:ROUTED_TO]->(p:Person) "
            "WITH q, collect([p.id, p.name, r.reason]) AS picks "
            "RETURN q.id, q.text, q.asker_id, picks ORDER BY q.id"
        )
        questions = []
        for qid, text, asker, picks in result.result_set:
            routed = [{"id": pid, "name": pname, "reason": reason or ""} for pid, pname, reason in picks if pid]
            questions.append(Question(id=qid, text=text or "", asker_id=asker or "", routed_to=routed))
        return questions

    def clear(self) -> None:
        self.graph.query("MATCH (n) DETACH DELETE n")


def make_store(settings) -> Store:
    if settings.store == "memory":
        return InMemoryStore()
    return FalkorDBStore(settings.falkordb_host, settings.falkordb_port, settings.graph_name)
