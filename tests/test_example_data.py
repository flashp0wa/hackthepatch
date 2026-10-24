"""The larger fictional room (tests/fixtures): valid, distinct from the seed, and rich enough that every feature has something to show."""
import json
from pathlib import Path

from app.llm import hash_embedding
from app.matching import complementary_matches, project_connections
from app.models import Profile, make_person_id
from app.roomgraph import build_room_graph
from tests.conftest import seed_profiles

EXAMPLE = json.loads((Path(__file__).resolve().parent / "fixtures" / "example_profiles.json").read_text())


def example_profiles() -> list[Profile]:
    return [Profile(id=make_person_id(r["name"], r.get("url", "")), **r) for r in EXAMPLE]


def full_room() -> list[Profile]:
    room = seed_profiles() + example_profiles()
    for p in room:
        p.embedding = hash_embedding(p.text_for_embedding())
    return room


def by_name(profiles, name):
    return next(p for p in profiles if p.name == name)


def test_example_records_are_valid_and_distinct_from_the_seed():
    room = full_room()
    assert len(EXAMPLE) == 20 and len(room) == 34
    assert len({p.id for p in room}) == 34
    assert all(p.url.endswith("-demo") for p in room), "every fictional attendee is marked -demo"
    projects = [p for p in example_profiles() if p.project]
    assert len(projects) == 3
    for p in projects:
        assert p.project.pain_points and p.project.needs and p.project.domains and p.project.connection_ideas
    sparse = by_name(room, "Rohan Iyer")  # what a masked LinkedIn scrape looks like
    assert sparse.technologies == [] and sparse.building == ""


def test_example_projects_find_their_unblockers_in_the_room():
    room = full_room()
    fatima = project_connections(by_name(room, "Fatima El-Sayed"), room, top=4)
    assert "Sofia Bianchi" in {c.person.name for c in fatima}  # agent identity: SPIFFE + security
    samuel = project_connections(by_name(room, "Samuel Adeyemi"), room, top=4)
    assert "Oliver Schmidt" in {c.person.name for c in samuel}  # payments + ledgers
    assert any("payments" in c.covers for c in samuel)


def test_example_people_match_across_the_two_datasets():
    room = full_room()
    for_maya = complementary_matches(by_name(room, "Maya Okonkwo"), room, top=5)
    # Maya (founder, no designer) now gets Imani, the designer seeking a founding-designer seat, ahead of Daniel
    assert [m.person.name for m in for_maya[:2]] == ["Imani Carter", "Daniel Reyes"]
    assert for_maya[0].pair == "founder \u2194 open to work" and "product design" in for_maya[0].fills
    for_priya = complementary_matches(by_name(room, "Priya Natarajan"), room, top=5)
    assert "Sebastián Cruz" in {m.person.name for m in for_priya}  # the room finally has a technical writer


def test_full_room_graph_still_has_a_few_bridges():
    g = build_room_graph(full_room())
    assert len(g["nodes"]) == 34 and g["clusters"] >= 3
    assert 1 <= len(g["bridges"]) <= 5


def test_every_group_is_represented_with_a_statement():
    room = full_room()
    by_role = {}
    for p in room:
        by_role.setdefault(p.role, []).append(p)
    assert set(by_role) == {"investor", "founder", "hiring", "open_to_work", "connecting"}
    assert all(p.statement for p in room)
    assert all(p.looking_for for p in room if p.role in ("investor", "founder", "hiring", "open_to_work"))


def test_groups_match_across_their_gaps():
    room = full_room()
    katrin = complementary_matches(by_name(room, "Katrin Hoffmann"), room, top=5)        # investor
    assert katrin[0].pair == "investor \u2194 founder" and katrin[0].person.role == "founder"
    assert {m.person.name for m in katrin[:3]} <= {"Samuel Adeyemi", "Fatima El-Sayed", "Hannah Lindqvist", "Grace Mwangi"}
    assert all("funding" in m.they_need or "fundraising" in m.they_need for m in katrin[:3])

    henrik = complementary_matches(by_name(room, "Henrik Dahl"), room, top=5)            # hiring ml + frontend + devrel
    names = [m.person.name for m in henrik]
    assert names[0] in ("Ethan Brooks", "Sebastián Cruz") and henrik[0].person.role == "open_to_work"
    assert "Sebastián Cruz" in names and "Ethan Brooks" in names

    pavel = complementary_matches(by_name(room, "Pavel Novák"), room, top=5)             # open to work, backend/k8s
    assert pavel[0].person.role in ("hiring", "founder"), [(m.person.name, m.person.role) for m in pavel]
    assert any(m.person.name == "Fatima El-Sayed" and "kubernetes" in m.they_need for m in pavel)

    imani = complementary_matches(by_name(room, "Imani Carter"), room, top=5)            # open to work, designer
    assert {m.person.name for m in imani} & {"Samuel Adeyemi", "Maya Okonkwo"}
