import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from fastapi.testclient import TestClient

import main
from agent import Agent, FakeClient
from tools import run_tool, load_seller


def make_session():
    return {"actions": []}


def test_decline_numbers():
    result = run_tool(make_session(), "analyze_decline", {})
    assert "error" not in result
    assert len(result["ranked_causes"]) >= 3


def test_unknown_tool_returns_error():
    result = run_tool(make_session(), "does_not_exist", {})
    assert "error" in result


def test_oos_top_products():
    result = run_tool(make_session(), "get_oos_products", {"top_n": 3})
    assert "error" not in result


def test_task_creates_action():
    session = make_session()
    run_tool(session, "create_task", {"title": "Restock top 5 products", "due_in_days": 2})
    assert len(session["actions"]) == 1


def test_finish_call_sets_summary():
    session = make_session()
    run_tool(session, "finish_call", {"issues": ["stock-outs"], "recommendations": ["a", "b", "c"], "next_steps": ["follow up"]})
    assert session["finished"] is True
    assert session["summary"] is not None


def test_agent_runs_tools_then_replies():
    llm = FakeClient([
        {"calls": [{"name": "analyze_decline", "args": {}}]},
        {"text": "Sales fell a lot. Did you change prices?"},
    ])
    agent = Agent(llm)
    session = agent.new_session()
    result = agent.turn(session, "sales dropped")
    assert result["reply"].startswith("Sales fell")
    assert result["events"][0]["name"] == "analyze_decline"


def test_agent_recovers_from_llm_error():
    agent = Agent(FakeClient([RuntimeError("boom")]))
    session = agent.new_session()
    before = len(session["messages"])
    result = agent.turn(session, "hello")
    assert "Sorry" in result["reply"]
    assert len(session["messages"]) == before


def test_agent_stops_after_max_rounds():
    loop = [{"calls": [{"name": "get_seller_snapshot", "args": {}}]}] * 10
    agent = Agent(FakeClient(loop))
    session = agent.new_session()
    result = agent.turn(session, "hi")
    assert result["reply"] != ""


def test_api_flow():
    main.agent = Agent(FakeClient([{"text": "Okay Ramesh ji."}]))
    client = TestClient(main.app)
    created = client.post("/api/session").json()
    sid = created["session_id"]
    assert "Ramesh" in created["greeting"]
    reply = client.post("/api/turn", json={"session_id": sid, "text": "hello"}).json()
    assert reply["reply"] == "Okay Ramesh ji."
    assert client.post("/api/turn", json={"session_id": "bad", "text": "x"}).status_code == 404
    assert client.post("/api/turn", json={"session_id": sid, "text": "  "}).status_code == 400
    tool = client.post("/api/tool/get_seller_snapshot", json={"session_id": sid, "args": {}})
    assert tool.status_code == 200
    assert client.post("/api/tool/nope", json={"session_id": sid, "args": {}}).status_code == 404
