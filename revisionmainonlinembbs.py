# revisionmainonlinembbs.py
# ---------------------------------------------------------
# Concept + MCQ Revision Orchestrator (PROD, DETERMINISTIC)
# In-memory | Stateless frontend | No phase alternation
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
    event: Optional[str] = None


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
# START REVISION (SEND CONCEPT + MCQ)
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
        "answers": [],
        "started_at": start_ts,
    }

    log.info(f"🧠 Session created: {session_id}")
    log.info("📤 Sending FIRST CONCEPT + MCQ (paired)")

    return {
        "session_id": session_id,
        "type": "concept_mcq",
        "index": 0,
        "payload": {
            "concept": concepts[0],
            "mcq": mcqs[0] if mcqs else None,
        },
        "total_concepts": len(concepts),
    }


# ---------------------------------------------------------
# NEXT STEP (ALWAYS SEND CURRENT INDEX PAIR)
# ---------------------------------------------------------

@app.post("/revision/next")
def next_step(payload: NextStepRequest):
    log.info("⏭️ /revision/next called")
    log.info(f"🆔 session_id: {payload.session_id}")

    session = REVISION_SESSIONS.get(payload.session_id)

    if not session:
        log.error("❌ Session not found / expired")
        raise HTTPException(status_code=404, detail="Session expired")

    idx = session["current_index"]
    concepts = session["concepts"]
    mcqs = session["mcqs"]

    log.info(f"📍 Current index: {idx}")

    # -------------------------------
    # COMPLETE
    # -------------------------------
    if idx >= len(concepts):
        correct = sum(1 for a in session["answers"] if a["correct"])
        incorrect = sum(1 for a in session["answers"] if not a["correct"])

        log.info("🏁 SESSION COMPLETE")
        log.info(f"✅ Correct: {correct} | ❌ Incorrect: {incorrect}")

        return {
            "type": "complete",
            "summary": {
                "total_concepts": len(concepts),
                "mcqs_attempted": len(session["answers"]),
                "correct": correct,
                "incorrect": incorrect,
            },
        }

    log.info(f"📤 Sending CONCEPT + MCQ pair for index {idx}")

    return {
        "type": "concept_mcq",
        "index": idx,
        "payload": {
            "concept": concepts[idx],
            "mcq": mcqs[idx] if idx < len(mcqs) else None,
        },
    }


# ---------------------------------------------------------
# SUBMIT MCQ ANSWER (ADVANCES INDEX)
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

    session["current_index"] += 1

    log.info(
        f"✅ Answer recorded | correct={is_correct} | next_index={session['current_index']}"
    )

    return {
        "status": "recorded",
        "correct": is_correct,
        "correct_answer": correct_answer,
        "learning_gap": mcq.get("learning_gap"),
    }
