from tests.conftest import seed_room


def test_full_demo_flow(client):
    assert client.get("/api/attendees").json() == []
    assert len(seed_room(client)) == 14
    people = client.get("/api/attendees").json()
    assert len(people) == 14 and "embedding" not in people[0]
    maya = next(p for p in people if p["name"] == "Maya Okonkwo")

    # 1. complementary matching
    m = client.get(f"/api/matches/{maya['id']}").json()
    assert m["matches"][0]["person"]["name"] == "Daniel Reyes"

    # 2. ask the room -> routed, stored, visible in the pick's inbox
    q = client.post("/api/questions", json={"text": "anyone used Temporal in production?", "asker_id": maya["id"]}).json()
    assert len(q["routed_to"]) == 1 and q["routed_to"][0]["id"] != maya["id"]
    assert "temporal" in q["routed_to"][0]["hits"]
    pick = q["routed_to"][0]["id"]
    assert client.get(f"/api/inbox/{pick}").json()[0]["id"] == q["id"]
    assert client.get(f"/api/inbox/{maya['id']}").json() == []
    assert client.get("/api/questions").json()[0]["text"].startswith("anyone used Temporal")

    # 3. room graph
    g = client.get("/api/room-graph").json()
    assert len(g["nodes"]) == 14 and g["bridges"]

    # paste-a-profile path goes through the LLM
    p = client.post("/api/attendees/text", json={"name": "Jane Tester", "text": "I lead QA."}).json()
    assert p["id"].startswith("jane-tester-") and p["technologies"] == ["pytest", "python"]
    assert client.get("/api/attendee" + "s").json().__len__() == 15

    # delete + reset
    assert client.delete(f"/api/attendees/{p['id']}").json() == {"deleted": p["id"]}
    assert client.delete("/api/attendees").json() == {"cleared": True}
    assert client.get("/api/attendees").json() == []


def test_validation_errors(client):
    assert client.post("/api/questions", json={"text": "   "}).status_code == 400
    assert client.post("/api/questions", json={"text": "hi"}).status_code == 409  # empty room
    assert client.get("/api/matches/nobody").status_code == 404

