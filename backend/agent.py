import json
import os
import time
import uuid
from pathlib import Path

from prompts import SYSTEM_PROMPT, greeting_text
from tools import TOOLS, load_seller, run_tool

MAX_TOOL_ROUNDS = 6
SORRY_TEXT = "Sorry ji, I had a small connection problem. Could you say that once more?"
LOG_DIR = Path(__file__).parent / "logs"

TOOL_SPECS = []
for tool_name in TOOLS:
    TOOL_SPECS.append(
        {
            "name": tool_name,
            "description": TOOLS[tool_name]["description"],
            "parameters": TOOLS[tool_name]["parameters"],
        }
    )


class GeminiClient:
    def __init__(self, api_key, model):
        from google import genai
        from google.genai import types

        self.types = types
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def build_declarations(self, tool_specs):
        declarations = []
        for spec in tool_specs:
            parameters = spec["parameters"]
            if len(parameters.get("properties", {})) == 0:
                declaration = self.types.FunctionDeclaration(
                    name=spec["name"],
                    description=spec["description"],
                )
            else:
                declaration = self.types.FunctionDeclaration(
                    name=spec["name"],
                    description=spec["description"],
                    parameters=parameters,
                )
            declarations.append(declaration)
        return declarations

    def build_contents(self, messages):
        types = self.types
        contents = []
        for message in messages:
            if message.get("raw") is not None:
                contents.append(message["raw"])
                continue
            if message["role"] == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=message["text"])]))
            elif message["role"] == "model" and "calls" in message:
                parts = []
                for call in message["calls"]:
                    parts.append(
                        types.Part(function_call=types.FunctionCall(name=call["name"], args=call["args"]))
                    )
                contents.append(types.Content(role="model", parts=parts))
            elif message["role"] == "model":
                contents.append(types.Content(role="model", parts=[types.Part(text=message["text"])]))
            elif message["role"] == "tool":
                parts = []
                for result in message["results"]:
                    parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=result["name"], response={"result": result["response"]}
                            )
                        )
                    )
                contents.append(types.Content(role="user", parts=parts))
        return contents

    def fast_config(self, **extra):
        types = self.types
        if "2.5" in self.model:
            extra["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        return types.GenerateContentConfig(**extra)

    def transcribe(self, audio_bytes, mime_type="audio/wav"):
        types = self.types
        prompt = (
            "This is audio of a Snapdeal seller speaking on a phone call. The language may be English, Hindi or Hinglish. "
            "Write exactly what the seller said, in Roman letters (write Hindi words in Roman script like Hinglish). "
            "Output only the transcript, nothing else. If there is no clear speech, output nothing."
        )
        part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
        config = self.fast_config(temperature=0.0)
        last_error = None
        for wait in [0, 3, 8]:
            if wait > 0:
                time.sleep(wait)
            try:
                response = self.client.models.generate_content(
                    model=self.model, contents=[prompt, part], config=config
                )
                return (response.text or "").strip()
            except Exception as error:
                last_error = error
                print("Gemini STT error:", str(error)[:300])
        raise last_error

    def generate(self, system_prompt, messages, tool_specs):
        types = self.types
        config = self.fast_config(
            system_instruction=system_prompt,
            tools=[types.Tool(function_declarations=self.build_declarations(tool_specs))],
            temperature=0.4,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        contents = self.build_contents(messages)
        last_error = None
        waits = [0, 3, 8, 15]
        for wait in waits:
            if wait > 0:
                time.sleep(wait)
            try:
                response = self.client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
                break
            except Exception as error:
                last_error = error
                print("Gemini error:", str(error)[:300])
        else:
            raise last_error

        text = ""
        calls = []
        raw = None
        if response.candidates and response.candidates[0].content:
            raw = response.candidates[0].content
            parts = raw.parts or []
            for part in parts:
                if part.function_call is not None:
                    args = {}
                    if part.function_call.args:
                        args = dict(part.function_call.args)
                    calls.append({"name": part.function_call.name, "args": args})
                elif part.text and not getattr(part, "thought", False):
                    text = text + part.text
        return {"text": text.strip(), "calls": calls, "raw": raw}


class FakeClient:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.seen = []

    def transcribe(self, audio_bytes, mime_type="audio/wav"):
        return "fake transcript"

    def generate(self, system_prompt, messages, tool_specs):
        self.seen.append(list(messages))
        if len(self.scripted) == 0:
            return {"text": "Okay ji.", "calls": [], "raw": None}
        step = self.scripted.pop(0)
        if isinstance(step, Exception):
            raise step
        return {"text": step.get("text", ""), "calls": step.get("calls", []), "raw": None}


def build_llm():
    api_key = os.environ.get("GEMINI_API_KEY", "")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    if api_key == "":
        return None
    return GeminiClient(api_key, model)


class Agent:
    def __init__(self, llm):
        self.llm = llm
        self.sessions = {}

    def new_session(self):
        seller = load_seller()
        greeting = greeting_text(seller)
        session = {
            "id": uuid.uuid4().hex[:12],
            "messages": [{"role": "model", "text": greeting}],
            "actions": [],
            "tool_calls": [],
            "turns": [],
            "summary": None,
            "finished": False,
            "greeting": greeting,
        }
        self.sessions[session["id"]] = session
        return session

    def get_session(self, session_id):
        return self.sessions.get(session_id)

    def write_log(self, session, record):
        try:
            LOG_DIR.mkdir(exist_ok=True)
            path = LOG_DIR / (session["id"] + ".jsonl")
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except OSError:
            pass

    def turn(self, session, user_text):
        started = time.time()
        start_length = len(session["messages"])
        session["messages"].append({"role": "user", "text": user_text})
        events = []
        reply = ""
        error_text = ""
        try:
            for round_number in range(MAX_TOOL_ROUNDS):
                result = self.llm.generate(SYSTEM_PROMPT, session["messages"], TOOL_SPECS)
                calls = result["calls"]
                if len(calls) == 0:
                    reply = result["text"]
                    session["messages"].append({"role": "model", "text": reply, "raw": result.get("raw")})
                    break
                session["messages"].append({"role": "model", "calls": calls, "raw": result.get("raw")})
                results = []
                for call in calls:
                    response = run_tool(session, call["name"], call["args"])
                    record = {
                        "name": call["name"],
                        "args": call["args"],
                        "response": response,
                        "round": round_number,
                    }
                    events.append(record)
                    session["tool_calls"].append(record)
                    results.append({"name": call["name"], "response": response})
                session["messages"].append({"role": "tool", "results": results})
        except Exception as error:
            error_text = str(error)
            del session["messages"][start_length:]
            reply = SORRY_TEXT
        if reply == "" and error_text == "":
            reply = "Sorry ji, could you say that once more?"
            session["messages"].append({"role": "model", "text": reply})
        elapsed_ms = int((time.time() - started) * 1000)
        turn_record = {
            "user": user_text,
            "reply": reply,
            "tools": [event["name"] for event in events],
            "latency_ms": elapsed_ms,
            "error": error_text,
        }
        session["turns"].append(turn_record)
        self.write_log(session, turn_record)
        return {
            "reply": reply,
            "events": events,
            "actions": session["actions"],
            "finished": session["finished"],
            "summary": session["summary"],
            "latency_ms": elapsed_ms,
            "error": error_text,
        }