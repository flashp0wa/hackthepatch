from app.graph import InMemoryStore
from app.models import Profile, Project


def test_merge_scraped_keeps_identity_and_project():
    me = Profile(id="li-1", name="Jane", email="j@x", picture="pic", linkedin_sub="s",
                 project=Project(description="d", needs=["marketing"]))
    scraped = Profile(id="jane-t", name="Jane T.", url="https://www.linkedin.com/in/jane-t", headline="QA",
                      technologies=["pytest"], looking_for=["backend engineering"])
    merged = me.merge_scraped(scraped)
    assert merged.id == "li-1" and merged.email == "j@x" and merged.picture == "pic" and merged.linkedin_sub == "s"
    assert merged.name == "Jane" and merged.url.endswith("jane-t") and merged.headline == "QA"
    assert merged.project and merged.project.needs == ["marketing"]
    assert merged.all_needs() == ["backend engineering", "marketing"]
    assert "working on: d" in merged.text_for_embedding()


def test_in_memory_find_by_sub():
    store = InMemoryStore()
    store.upsert_person(Profile(id="a", name="A", linkedin_sub="sub-a"))
    assert store.find_by_sub("sub-a").id == "a" and store.find_by_sub("nope") is None
