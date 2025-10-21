from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from supabase_client import call_rpc, supabase
import json

# ───────────────────────────────────────────────
# Initialize FastAPI app
# ───────────────────────────────────────────────
app = FastAPI(title="Flashcard Orchestra API", version="1.0.0")

# ✅ Allow frontend (Expo / Web / React) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────────────────────────────────────────────
# Master Endpoint — handles all flashcard actions
# ───────────────────────────────────────────────
@app.post("/flashcard_orchestrate")
async def flashcard_orchestrate(request: Request):
    payload = await request.json()
    action = payload.get("action")
    student_id = payload.get("student_id")

    print(f"🎬 Flashcard Action = {action}, Student = {student_id}")

    # ───────────────────────────────
    # 🟢 1️⃣ START_FLASHCARD
    # ───────────────────────────────
    if action == "start_flashcard":
        rpc_data = call_rpc("start_flashcard_orchestra", {"p_student_id": student_id})
        if not rpc_data:
            return {"error": "❌ start_flashcard_orchestra RPC failed"}

        phase_type = rpc_data.get("phase_type")
        phase_json = rpc_data.get("phase_json")
        mentor_reply = rpc_data.get("mentor_reply")
        react_order_final = rpc_data.get("react_order_final")
        concept = rpc_data.get("concept")
        subject = rpc_data.get("subject")

        return {
            "student_id": student_id,
            "react_order_final": react_order_final,
            "phase_type": phase_type,
            "phase_json": phase_json,
            "mentor_reply": mentor_reply,
            "concept": concept,
            "subject": subject
        }

    # ───────────────────────────────
    # 🔵 2️⃣ NEXT_FLASHCARD
    # ───────────────────────────────
    elif action == "next_flashcard":
        rpc_data = call_rpc("next_flashcard_orchestra", {"p_student_id": student_id})
        if not rpc_data:
            return {"error": "❌ next_flashcard_orchestra RPC failed"}

        phase_type = rpc_data.get("phase_type")
        phase_json = rpc_data.get("phase_json")
        mentor_reply = rpc_data.get("mentor_reply")
        react_order_final = rpc_data.get("react_order_final")
        concept = rpc_data.get("concept")
        subject = rpc_data.get("subject")

        return {
            "student_id": student_id,
            "react_order_final": react_order_final,
            "phase_type": phase_type,
            "phase_json": phase_json,
            "mentor_reply": mentor_reply,
            "concept": concept,
            "subject": subject
        }

    else:
        return {"error": f"Unknown flashcard action '{action}'"}


# ───────────────────────────────────────────────
# Optional — for future: Flashcard-specific logs, analytics, or sync
# ───────────────────────────────────────────────
@app.post("/submit_flashcard_progress")
async def submit_flashcard_progress(request: Request):
    """Optionally record per-card progress or time spent per flashcard phase"""
    try:
        data = await request.json()
        student_id = data.get("student_id")
        react_order_final = data.get("react_order_final")
        progress = data.get("progress", {})
        completed = data.get("completed", False)

        supabase.table("student_flashcard_pointer") \
            .update({
                "last_progress": progress,
                "is_completed": completed,
                "updated_at": datetime.utcnow().isoformat() + "Z"
            }) \
            .eq("student_id", student_id) \
            .eq("react_order_final", react_order_final) \
            .execute()

        print(f"✅ Flashcard progress updated for {student_id}, react_order {react_order_final}")
        return {"status": "success"}

    except Exception as e:
        print(f"❌ Error updating flashcard progress: {e}")
        return {"error": str(e)}


# ───────────────────────────────────────────────
# Health Check
# ───────────────────────────────────────────────
@app.get("/")
def home():
    return {"message": "🧠 Flashcard Orchestra API is running successfully!"}
