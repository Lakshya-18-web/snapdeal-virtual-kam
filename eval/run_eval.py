import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "backend" / ".env")
load_dotenv(Path(__file__).parent.parent / ".env")

from agent import Agent, build_llm


def sentence_count(text):
    parts = re.split(r"[.!?]+(?:\s+|$)", text)
    count = 0
    for part in parts:
        if part.strip() != "":
            count = count + 1
    return count


def run_scenario(agent, scenario):
    session = agent.new_session()
    replies = []
    tools_used = []
    for line in scenario["turns"]:
        result = agent.turn(session, line)
        if result["error"] != "":
            print("  ERROR:", result["error"][:200])
        time.sleep(float(os.environ.get("EVAL_PAUSE", "8")))
        replies.append(result["reply"])
        for event in result["events"]:
            tools_used.append(event["name"])
    checks = {}
    checks["no_errors"] = all(turn["error"] == "" for turn in session["turns"])
    checks["short_replies"] = all(sentence_count(r) <= 4 for r in replies)
    checks["no_markdown"] = all(("*" not in r and "#" not in r) for r in replies)
    name = scenario["name"]
    if name in ("cooperative", "hinglish", "vague", "pricing_advice"):
        checks["used_analysis_tool"] = "analyze_decline" in tools_used
    if name in ("cooperative", "hinglish"):
        checks["created_tasks"] = "create_task" in tools_used
        checks["finished_with_summary"] = session["finished"] and session["summary"] is not None
    if name == "angry":
        checks["escalated"] = "escalate_to_human" in tools_used
    if name == "off_topic":
        checks["returned_to_topic"] = "analyze_decline" in tools_used or "get_seller_snapshot" in tools_used
    return {"name": name, "checks": checks, "replies": replies, "tools": tools_used}


def main():
    llm = build_llm()
    if llm is None:
        print("Set GEMINI_API_KEY in .env first.")
        return
    agent = Agent(llm)
    scenarios = json.loads((Path(__file__).parent / "scenarios.json").read_text())
    total = 0
    passed = 0
    for scenario in scenarios:
        result = run_scenario(agent, scenario)
        print("\n== " + result["name"])
        for i, reply in enumerate(result["replies"]):
            print("  bot %d: %s" % (i + 1, reply))
        print("  tools:", ", ".join(result["tools"]))
        for check in result["checks"]:
            ok = result["checks"][check]
            total = total + 1
            if ok:
                passed = passed + 1
            print("  [%s] %s" % ("PASS" if ok else "FAIL", check))
    print("\n%d of %d checks passed" % (passed, total))


main()