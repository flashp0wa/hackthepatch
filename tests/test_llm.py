import json

import pytest

from app.config import Settings
from app.llm import LLM, hash_embedding, parse_json_object
from app.models import make_person_id
from tests.conftest import FakeOpenAI


def test_parse_json_object_tolerates_fences_and_prose():
    assert parse_json_object('Sure:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('{"a": {"b": 2}} trailing') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        parse_json_object("no json here")


def test_hash_embedding_is_deterministic_and_unit_length():
    a, b = hash_embedding("python kafka"), hash_embedding("python kafka")
    assert a == b and abs(sum(x * x for x in a) - 1.0) < 1e-9
    assert hash_embedding("python") != hash_embedding("rust")


def test_extract_profile_drops_placeholder_names():
    llm = LLM(Settings(openai_api_key="x"), client=FakeOpenAI(lambda _m: json.dumps(
        {"name": "L", "schools": ["UNH", "unknown school", "*****"], "companies": ["Siemens", "Unknown"]})))
    p = llm.extract_profile("L studied at UNH and works at Siemens.")
    assert p.schools == ["UNH"] and p.companies == ["Siemens"]


def test_extract_profile_normalises_lists_and_builds_id():
    reply = lambda _m: json.dumps({"name": "Ada Lovelace", "technologies": ["Python ", "python", "SQL"],
                                   "looking_for": ["Frontend Engineering"], "companies": [" Acme "],
                                   "role": "Open to Work", "statement": "Seeking a frontend role."})
    llm = LLM(Settings(openai_api_key="x"), client=FakeOpenAI(reply))
    p = llm.extract_profile("Ada Lovelace, engineer.", url="https://www.linkedin.com/in/ada-l/")
    assert p.id == "ada-l" and p.technologies == ["python", "sql"]
    assert p.looking_for == ["frontend engineering"] and p.companies == ["Acme"]
    assert p.role == "open_to_work" and p.statement == "Seeking a frontend role."
    from app.models import normalize_role
    assert normalize_role("VC") == "investor" and normalize_role("Co-Founder") == "founder" and normalize_role("") == "connecting"
    assert normalize_role("Hiring Manager") == "hiring" and normalize_role("Building connections") == "connecting"


def test_embed_falls_back_to_hash_when_endpoint_missing():
    llm = LLM(Settings(openai_api_key="x"), client=FakeOpenAI(embeddings_fail=True))
    assert llm.embed("hello") == hash_embedding("hello")
    llm_ok = LLM(Settings(openai_api_key="x"), client=FakeOpenAI())
    assert len(llm_ok.embed("hello")) == 3


def test_rank_for_question_falls_back_when_model_output_is_garbage():
    from app.models import Profile
    people = [Profile(id="a", name="A"), Profile(id="b", name="B")]
    llm = LLM(Settings(openai_api_key="x"), client=FakeOpenAI(lambda _m: "not json"))
    picks = llm.rank_for_question("q", people, top=1)
    assert picks == [{"id": "a", "name": "A", "reason": "closest profile match"}]


def test_make_person_id():
    assert make_person_id("X", "https://linkedin.com/in/Jane_Doe-1?x=1") == "jane-doe-1"
    assert make_person_id("Jane Doe").startswith("jane-doe-")
