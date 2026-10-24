from app.matching import complementary_matches, cosine, route_question, tags_overlap
from app.llm import hash_embedding
from tests.conftest import seed_profiles


def by_name(profiles, name):
    return next(p for p in profiles if p.name == name)


def test_tags_overlap_is_fuzzy_but_not_silly():
    assert tags_overlap("product design", "designer")
    assert tags_overlap("backend engineering", "backend engineering")
    assert tags_overlap("kubernetes", "kubernetes")
    assert not tags_overlap("go", "django")
    assert not tags_overlap("rust", "trust me")  # stem must start a word
    assert not tags_overlap("seed", "security")  # short words are not stemmed: "seed" is not "se"
    assert tags_overlap("backend engineer", "backend engineering") and tags_overlap("product designer", "product design")


def test_tag_aliases_let_roles_meet_skills():
    from app.matching import canonical_tag, matched_tags, tag_set
    assert canonical_tag("ML Engineer") == "machine learning engineer"
    assert canonical_tag("pre-seed investors") == "pre-seed funding" and canonical_tag("k8s") == "kubernetes"
    assert matched_tags(tag_set(["ml engineer"]), tag_set(["machine learning", "nlp"])) == {"machine learning engineer"}
    assert matched_tags(tag_set(["pre-seed investors"]), tag_set(["funding"])) == {"pre-seed funding"}
    assert matched_tags(tag_set(["frontend engineer"]), tag_set(["frontend engineering"])) == {"frontend engineer"}


def test_backend_engineer_with_idea_gets_the_designer_not_another_backend():
    room = seed_profiles()
    maya = by_name(room, "Maya Okonkwo")
    matches = complementary_matches(maya, room, top=3)
    names = [m.person.name for m in matches]
    assert names[0] == "Daniel Reyes", names
    assert "product design" in matches[0].fills
    assert "backend engineering" in matches[0].they_need
    assert "Oliver Schmidt" not in names  # another backend engineer who offers nothing Maya lacks


def test_complementary_excludes_self_and_non_matches():
    room = seed_profiles()
    maya = by_name(room, "Maya Okonkwo")
    assert all(m.person.id != maya.id for m in complementary_matches(maya, room, top=50))


def test_route_question_prefers_explicit_keyword_hits():
    room = seed_profiles()
    for p in room:
        p.embedding = hash_embedding(p.text_for_embedding())
    q = "anyone used Temporal in production?"
    shortlist = route_question(q, hash_embedding(q), room, shortlist=3)
    top_names = {c.person.name for c in shortlist}
    assert top_names <= {"Maya Okonkwo", "Amara Diallo", "Oliver Schmidt"}, top_names
    assert all("temporal" in c.hits for c in shortlist)


def test_cosine_handles_mismatched_and_empty_vectors():
    assert cosine([], [1.0]) == 0.0
    assert cosine([1.0, 0.0], [1.0]) == 0.0
    assert abs(cosine([1.0, 2.0], [1.0, 2.0]) - 1.0) < 1e-9


def test_role_aware_offers_and_needs():
    from app.models import Profile
    investor = Profile(id="i", name="I", role="investor", looking_for=["fintech", "pre-seed"], can_offer=["funding"])
    founder = Profile(id="f", name="F", role="founder", interests=["fintech"], looking_for=["funding", "backend engineering"], can_offer=["product design"])
    hiring = Profile(id="h", name="H", role="hiring", looking_for=["backend engineer"], can_offer=["open roles"])
    candidate = Profile(id="c", name="C", role="open_to_work", looking_for=["backend engineer"], can_offer=["backend engineering", "go"])
    for_investor = complementary_matches(investor, [founder, hiring, candidate], top=3)
    assert for_investor[0].person.id == "f" and for_investor[0].fills == ["fintech"] and "funding" in for_investor[0].they_need
    assert for_investor[0].pair == "investor \u2194 founder"
    for_hiring = complementary_matches(hiring, [investor, founder, candidate], top=3)
    assert for_hiring[0].person.id == "c" and for_hiring[0].fills == ["backend engineer"] and for_hiring[0].they_need == ["backend engineer"]
    for_candidate = complementary_matches(candidate, [investor, founder, hiring], top=3)
    assert [m.person.id for m in for_candidate][:2] == ["h", "f"]  # the job first, then the founder who needs the skill
    assert all(m.person.id != "i" for m in for_candidate)  # an investor has nothing a candidate needs
    assert complementary_matches(hiring, [Profile(id="h2", name="H2", role="hiring", looking_for=["backend engineer"])], top=3) == []
