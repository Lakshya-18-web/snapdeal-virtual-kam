import os
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent.parent / ".env")

from agent import Agent, build_llm
from tools import TOOLS, load_seller, run_tool

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "30"))
MAX_USER_TEXT = 500
VOICE_NAME = os.environ.get("VOICE_NAME", "en-IN-NeerjaNeural")
VOICE_RATE = os.environ.get("VOICE_RATE", "+8%")

app = FastAPI(title="Snapdeal Virtual KAM")
agent = Agent(build_llm())
hits = {}


class TurnBody(BaseModel):
    session_id: str
    text: str


class SpeakBody(BaseModel):
    text: str


class ToolBody(BaseModel):
    session_id: str
    args: dict = {}


def check_rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    recent = [t for t in hits.get(ip, []) if now - t < 60]
    if len(recent) >= RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Too many requests, please wait a minute.")
    recent.append(now)
    hits[ip] = recent


def find_session(session_id):
    session = agent.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown session. Start a new call.")
    return session


@app.get("/api/health")
def health():
    return {"ok": True, "llm_ready": agent.llm is not None}


@app.post("/api/session")
def create_session(request: Request):
    check_rate_limit(request)
    session = agent.new_session()
    seller = load_seller()
    return {
        "session_id": session["id"],
        "greeting": session["greeting"],
        "seller": {
            "name": seller["seller_name"],
            "business": seller["business_name"],
            "category": seller["category"],
            "city": seller["city"],
            "last_month": seller["metrics"]["last_month"],
            "this_month": seller["metrics"]["this_month"],
        },
    }


@app.post("/api/turn")
def turn(body: TurnBody, request: Request):
    check_rate_limit(request)
    if agent.llm is None:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is not set on the server.")
    session = find_session(body.session_id)
    text = body.text.strip()[:MAX_USER_TEXT]
    if text == "":
        raise HTTPException(status_code=400, detail="Empty text.")
    return agent.turn(session, text)


@app.post("/api/stt")
async def speech_to_text(request: Request):
    check_rate_limit(request)
    if agent.llm is None:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is not set on the server.")
    audio = await request.body()
    if len(audio) < 2000 or len(audio) > 3000000:
        raise HTTPException(status_code=400, detail="Bad audio size.")
    try:
        text = agent.llm.transcribe(audio, "audio/wav")
    except Exception as error:
        raise HTTPException(status_code=502, detail="Transcription failed: " + str(error)[:150])
    return {"text": text}


@app.post("/api/tts")
async def text_to_speech(body: SpeakBody, request: Request):
    check_rate_limit(request)
    text = body.text.strip()[:600]
    if text == "":
        raise HTTPException(status_code=400, detail="Empty text.")
    try:
        import edge_tts

        communicate = edge_tts.Communicate(text, VOICE_NAME, rate=VOICE_RATE)
        audio = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio = audio + chunk["data"]
    except Exception as error:
        raise HTTPException(status_code=502, detail="Voice failed: " + str(error)[:150])
    if len(audio) == 0:
        raise HTTPException(status_code=502, detail="No audio produced.")
    return Response(content=audio, media_type="audio/mpeg")


@app.get("/api/session/{session_id}")
def get_session(session_id: str):
    session = find_session(session_id)
    return {
        "actions": session["actions"],
        "summary": session["summary"],
        "finished": session["finished"],
        "turns": session["turns"],
    }


@app.post("/api/tool/{name}")
def call_tool(name: str, body: ToolBody, request: Request):
    check_rate_limit(request)
    session = find_session(body.session_id)
    if name not in TOOLS:
        raise HTTPException(status_code=404, detail="Unknown tool.")
    result = run_tool(session, name, body.args)
    return {"result": result, "actions": session["actions"], "finished": session["finished"], "summary": session["summary"]}


@app.get("/api/tool-specs")
def tool_specs():
    specs = []
    for name in TOOLS:
        specs.append({"name": name, "description": TOOLS[name]["description"], "parameters": TOOLS[name]["parameters"]})
    return specs


@app.get("/")
def index():
    page = FRONTEND_DIR / "index.html"
    if page.exists():
        return FileResponse(page)
    return JSONResponse({"message": "Frontend not built yet."})


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")