# revisionmain.py
# ----------------------------------------
# Concept → MCQ Revision Orchestrator
# In-memory, frontend-timer driven
# ----------------------------------------

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional
from uuid import uuid4

from supabase_client import supabase   # uses your existing client


app = FastAPI(title="Revision Orchestrator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------
# In-memory session store (INTENTIONAL)
# -------------------------------------------------
REVISION_SESSIONS: Dict[str, Dict[str, Any]] = {}


# -------------------------------------------------
# Request / Response Models
# -------------------------------------------------

class StartRevisionRequest(BaseModel):
    topic_id: str


class NextStepRequest(BaseModel):
    session_id: str
    event: Optional[str] = None   # "timer_elapsed" | "answered"


class SubmitAnswerRequest(BaseModel):
    session_id: str
    mcq_index: int
    selected_option: str


# -------------------------------------------------
# Health check
# -------------------------------------------------

@app.get("/health")
def health():
    return {"status": "revision api running"}


# -------------------------------------------------
# START REVISION
# -------------------------------------------------

@app.post("/revision/start")
def start_revision(payload: StartRevisionRequest):
    """
    1. Fetch concept_json + concept_mcq_json via RPC
    2. Initialize orchestration state
    3. Return first concept
    """

    rpc = supabase.rpc(
        "get_topic_content_v1",
        {"topic_id": payload.topic_id}
    ).execute()

    if not rpc.data:
        raise HTTPException(status_code=404, detail="Topic not found")

    data = rpc.data[0]["get_topic_content_v1"]

    concepts = data.get("concept_json", [])
    mcqs = data.get("concept_mcq_json", [])

    if not concepts:
        raise HTTPException(status_code=400, detail="No concepts found")

    session_id = str(uuid4())

    REVISION_SESSIONS[session_id] = {
        "topic_id": payload.topic_id,
        "concepts": concepts,
        "mcqs": mcqs,
        "current_index": 0,
        "phase": "concept",        # concept | mcq | complete
        "answers": [],             # [{mcq_index, selected, correct}]
        "started_at": None,
    }

    return {
        "session_id": session_id,
        "type": "concept",
        "index": 0,
        "payload": concepts[0],
        "total_concepts": len(concepts),
    }


# -------------------------------------------------
# NEXT STEP (Timer or UI driven)
# -------------------------------------------------

@app.post("/revision/next")
def next_step(payload: NextStepRequest):
    """
    Called when:
    - frontend timer expires
    - user taps continue
    """

    session = REVISION_SESSIONS.get(payload.session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session expired")

    idx = session["current_index"]

    # -----------------------------
    # CONCEPT → MCQ
    # -----------------------------
    if session["phase"] == "concept":
        if idx >= len(session["mcqs"]):
            raise HTTPException(status_code=400, detail="MCQ missing for concept")

        session["phase"] = "mcq"

        return {
            "type": "mcq",
            "index": idx,
            "payload": session["mcqs"][idx],
        }

    # -----------------------------
    # MCQ → NEXT CONCEPT
    # -----------------------------
    if session["phase"] == "mcq":
        session["current_index"] += 1
        idx = session["current_index"]

        if idx >= len(session["concepts"]):
            session["phase"] = "complete"

            return {
                "type": "complete",
                "summary": {
                    "total_concepts": len(session["concepts"]),
                    "mcqs_attempted": len(session["answers"]),
                    "correct": sum(1 for a in session["answers"] if a["correct"]),
                    "incorrect": sum(1 for a in session["answers"] if not a["correct"]),
                },
            }

        session["phase"] = "concept"

        return {
            "type": "concept",
            "index": idx,
            "payload": session["concepts"][idx],
        }

    return {"type": "idle"}


# -------------------------------------------------
# SUBMIT MCQ ANSWER (Optional but recommended)
# -------------------------------------------------

@app.post("/revision/answer")
def submit_answer(payload: SubmitAnswerRequest):
    """
    Stores MCQ response in memory for analytics
    """

    session = REVISION_SESSIONS.get(payload.session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session expired")

    mcqs = session["mcqs"]

    if payload.mcq_index >= len(mcqs):
        raise HTTPException(status_code=400, detail="Invalid MCQ index")

    mcq = mcqs[payload.mcq_index]
    correct = payload.selected_option == mcq.get("correct_answer")

    session["answers"].append({
        "mcq_index": payload.mcq_index,
        "selected": payload.selected_option,
        "correct": correct,
        "concept_value": mcq.get("concept_value"),
    })

    return {
        "status": "recorded",
        "correct": correct,
        "correct_answer": mcq.get("correct_answer"),
        "learning_gap": mcq.get("learning_gap"),
    }
