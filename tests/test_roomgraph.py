from app.models import Profile
from app.roomgraph import build_room_graph
from tests.conftest import seed_profiles


def test_room_graph_has_clusters_and_bridges():
    g = build_room_graph(seed_profiles())
    assert len(g["nodes"]) == 14
    assert g["clusters"] >= 2
    assert g["bridges"], "the seed room is designed to have bridges"
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["from"] in ids and e["to"] in ids and e["weight"] > 0 and e["shared"] for e in g["edges"])
    assert 1 <= len(g["bridges"]) <= 3, g["bridges"]  # the few, not the many
    ravi = next(n for n in g["nodes"] if n["name"] == "Ravi Menon")  # infra + ML + fintech interests
    assert ravi["bridge"]


def test_room_graph_handles_empty_and_single_rooms():
    assert build_room_graph([]) == {"nodes": [], "edges": [], "clusters": 0, "bridges": []}
    g = build_room_graph([Profile(id="a", name="A")])
    assert g["nodes"][0]["bridge"] is False and g["edges"] == []
