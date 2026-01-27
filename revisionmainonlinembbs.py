# revisionmainonlinembbs.py
# ---------------------------------------------------------
# Concept → MCQ Revision Orchestrator (DEBUG ENABLED)
# In-memory | Frontend-timer driven | No persistence
# ---------------------------------------------------------

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional
from uuid import uuid4
import time
import logging

from supabase_client import supabase


# ---------------------------------------------------------
# LOGGING CONFIG
# ---------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

log = logging.getLogger("REVISION")


# ---------------------------------------------------------
# FASTAPI APP
# ---------------------------------------------------------

app = FastAPI(title="Revision Orchestrator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

log.info("🚀 Revision Orchestrator API booting up...")


# ---------------------------------------------------------
# IN-MEMORY SESSION STORE
# ---------------------------------------------------------

REVISION_SESSIONS: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------
# REQUEST MODELS
# ---------------------------------------------------------

class StartRevisionRequest(BaseModel):
    topic_id: str


class NextStepRequest(BaseModel):
    session_id: str
    event: Optional[str] = None   # timer_elapsed | answered | continue


class SubmitAnswerRequest(BaseModel):
    session_id: str
    mcq_index: int
    selected_option: str


# ---------------------------------------------------------
# HEALTH
# ---------------------------------------------------------

@app.get("/health")
def health():
    log.info("❤️ Health check pinged")
    return {"status": "revision api running"}


# ---------------------------------------------------------
# START REVISION
# ---------------------------------------------------------

@app.post("/revision/start")
def start_revision(payload: StartRevisionRequest):
    log.info("▶️ /revision/start called")
    log.info(f"📌 topic_id received: {payload.topic_id}")

    start_ts = time.time()

    rpc = supabase.rpc(
        "get_topic_content_v1",
        {"p_topic_id": payload.topic_id}
    ).execute()

    if not rpc.data:
        log.error("❌ No data returned from RPC")
        raise HTTPException(status_code=404, detail="Topic not found")

    data = rpc.data

    concepts = data.get("concept_json", [])
    mcqs = data.get("concept_mcq_json", [])

    log.info(f"📘 Concepts loaded: {len(concepts)}")
    log.info(f"❓ MCQs loaded: {len(mcqs)}")

    if not concepts:
        raise HTTPException(status_code=400, detail="No concepts found")

    session_id = str(uuid4())

    REVISION_SESSIONS[session_id] = {
        "topic_id": payload.topic_id,
        "concepts": concepts,
        "mcqs": mcqs,
        "current_index": 0,
        "phase": "concept",   # concept | mcq | complete
        "answers": [],
        "started_at": start_ts,
    }

    log.info(f"🧠 Session created: {session_id}")
    log.info("📤 Sending FIRST CONCEPT")

    return {
        "session_id": session_id,
        "type": "concept",
        "index": 0,
        "payload": concepts[0],
        "total_concepts": len(concepts),
    }


# ---------------------------------------------------------
# NEXT STEP (TIMER / UI DRIVEN)
# ---------------------------------------------------------

@app.post("/revision/next")
def next_step(payload: NextStepRequest):
    log.info("⏭️ /revision/next called")
    log.info(f"🆔 session_id: {payload.session_id}")
    log.info(f"📟 event: {payload.event}")

    session = REVISION_SESSIONS.get(payload.session_id)

    if not session:
        log.error("❌ Session not found / expired")
        raise HTTPException(status_code=404, detail="Session expired")

    idx = session["current_index"]
    phase = session["phase"]

    log.info(f"📍 Current index: {idx}")
    log.info(f"🔄 Current phase: {phase}")

    # -------------------------------------------------
    # CONCEPT → MCQ
    # -------------------------------------------------
    if phase == "concept":
        log.info("➡️ Transition: CONCEPT → MCQ")

        if idx >= len(session["mcqs"]):
            log.error("❌ MCQ missing for this concept index")
            raise HTTPException(status_code=400, detail="MCQ missing")

        session["phase"] = "mcq"

        log.info(f"📤 Sending MCQ #{idx}")

        return {
            "type": "mcq",
            "index": idx,
            "payload": session["mcqs"][idx],
        }

    # -------------------------------------------------
    # MCQ → NEXT CONCEPT or COMPLETE
    # -------------------------------------------------
    if phase == "mcq":
        log.info("➡️ Transition: MCQ → NEXT")

        session["current_index"] += 1
        idx = session["current_index"]

        log.info(f"📍 Incremented index to {idx}")

        if idx >= len(session["concepts"]):
            session["phase"] = "complete"

            correct = sum(1 for a in session["answers"] if a["correct"])
            incorrect = sum(1 for a in session["answers"] if not a["correct"])

            log.info("🏁 SESSION COMPLETE")
            log.info(f"✅ Correct answers: {correct}")
            log.info(f"❌ Incorrect answers: {incorrect}")

            return {
                "type": "complete",
                "summary": {
                    "total_concepts": len(session["concepts"]),
                    "mcqs_attempted": len(session["answers"]),
                    "correct": correct,
                    "incorrect": incorrect,
                },
            }

        session["phase"] = "concept"

        log.info(f"📤 Sending NEXT CONCEPT #{idx}")

        return {
            "type": "concept",
            "index": idx,
            "payload": session["concepts"][idx],
        }

    log.warning("⚠️ Unknown phase reached")
    return {"type": "idle"}


# ---------------------------------------------------------
# SUBMIT MCQ ANSWER
# ---------------------------------------------------------

@app.post("/revision/answer")
def submit_answer(payload: SubmitAnswerRequest):
    log.info("📝 /revision/answer called")
    log.info(f"🆔 session_id: {payload.session_id}")
    log.info(f"❓ mcq_index: {payload.mcq_index}")
    log.info(f"🅰️ selected_option: {payload.selected_option}")

    session = REVISION_SESSIONS.get(payload.session_id)

    if not session:
        log.error("❌ Session not found")
        raise HTTPException(status_code=404, detail="Session expired")

    mcqs = session["mcqs"]

    if payload.mcq_index >= len(mcqs):
        log.error("❌ Invalid MCQ index")
        raise HTTPException(status_code=400, detail="Invalid MCQ index")

    mcq = mcqs[payload.mcq_index]
    correct_answer = mcq.get("correct_answer")

    is_correct = payload.selected_option == correct_answer

    session["answers"].append({
        "mcq_index": payload.mcq_index,
        "selected": payload.selected_option,
        "correct": is_correct,
        "concept_value": mcq.get("concept_value"),
    })

    log.info(f"✅ Answer recorded | correct={is_correct}")

    return {
        "status": "recorded",
        "correct": is_correct,
        "correct_answer": correct_answer,
        "learning_gap": mcq.get("learning_gap"),
    }
