from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["providers"] == 25


def test_full_conversation_creates_persisted_lead():
    conv = client.post("/api/conversations").json()
    cid = conv["conversation_id"]
    last = None
    for msg in [
        "Water came into my basement after the storm",
        "95050",
        "no it stopped",
        "today please",
        "Test User, 408-555-0142",
        "yes",
    ]:
        last = client.post(f"/api/conversations/{cid}/messages", json={"content": msg}).json()
    assert last["dispatchable"] is True
    lead = client.get(f"/api/leads/{last['lead_id']}").json()
    assert "NEW SERVICE LEAD" in lead["text"]
    assert "Pending" in lead["packet"]["property"]["address"]
    transcript = client.get(f"/api/conversations/{cid}").json()["messages"]
    assert len(transcript) == 13  # greeting + 6 user + 6 assistant


def test_unknown_conversation_404():
    assert client.post("/api/conversations/nope/messages", json={"content": "hi"}).status_code == 404
