from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from supabase_client import call_rpc, supabase
from gpt_utils import chat_with_gpt
import json, uuid

# ───────────────────────────────────────────────
# Initialize FastAPI app
# ───────────────────────────────────────────────
app = FastAPI(title="Flashcard Orchestra API", version="2.1.0")

# ✅ Allow frontend (Expo / Web / React) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────────────────────────────────────────────
# Helper: make JSON fully serializable (UUID → string)
# ───────────────────────────────────────────────
def _make_json_safe(data):
    if isinstance(data, uuid.UUID):
        return str(data)
    if isinstance(data, dict):
        return {k: _make_json_safe(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_make_json_safe(v) for v in data]
    return data

# ───────────────────────────────────────────────
# Master Endpoint — handles all flashcard actions
# ───────────────────────────────────────────────
@app.post("/flashcard_orchestrate")
async def flashcard_orchestrate(request: Request):
    payload = await request.json()
    action = payload.get("action")
    student_id = payload.get("student_id")
    subject_id = payload.get("subject_id")
    message = payload.get("message")

    print(f"🎬 Flashcard Action = {action}, Student = {student_id}")

    # ───────────────────────────────
    # 🟢 1️⃣ START_FLASHCARD
    # ───────────────────────────────
    if action == "start_flashcard":
        rpc_data = call_rpc("start_flashcard_orchestra", {
            "p_student_id": student_id,
            "p_subject_id": subject_id
        })
        if not rpc_data:
            return {"error": "❌ start_flashcard_orchestra RPC failed"}

        phase_type = rpc_data.get("phase_type")
        phase_json = rpc_data.get("phase_json")
        mentor_reply = rpc_data.get("mentor_reply")
        react_order_final = rpc_data.get("react_order_final")
        concept = rpc_data.get("concept")
        subject = rpc_data.get("subject")

        # 🧩 Debug print for JSON
        print("🧩 phase_json received from RPC:")
        try:
            print(json.dumps(phase_json, indent=2)[:500])
        except Exception:
            print("⚠️ Could not pretty-print phase_json")

        # ✅ Ensure phase_json is safe before next RPC
        safe_phase_json = _make_json_safe(phase_json)
        safe_mentor_reply = _make_json_safe(mentor_reply)

        # 🟢 Update pointer table safely
        try:
            call_rpc("update_flashcard_pointer_status", {
                "p_student_id": student_id,
                "p_subject_id": subject_id,
                "p_react_order_final": react_order_final,
                "p_phase_json": safe_phase_json,
                "p_mentor_reply": safe_mentor_reply
            })
        except Exception as e:
            print(f"⚠️ RPC update_flashcard_pointer_status failed: {e}")

        return {
            "student_id": student_id,
            "react_order_final": react_order_final,
            "phase_type": phase_type,
            "phase_json": safe_phase_json,
            "mentor_reply": safe_mentor_reply,
            "concept": concept,
            "subject": subject
        }

    # ───────────────────────────────
    # 🟡 2️⃣ CHAT_FLASHCARD
    # ───────────────────────────────
    elif action == "chat_flashcard":
        pointer_id = None
        convo_log = []

        try:
            res = (
                supabase.table("student_flashcard_pointer")
                .select("pointer_id, conversation_log")
                .eq("student_id", student_id)
                .order("updated_at", desc=True)
                .limit(1)
                .execute()
            )
            if not res.data:
                print(f"⚠️ No flashcard pointer found for student {student_id}")
                return {"error": "⚠️ No active flashcard pointer for this student"}

            pointer = res.data[0]
            pointer_id = pointer["pointer_id"]
            convo_log = pointer.get("conversation_log", [])
            convo_log.append({
                "role": "student",
                "content": message,
                "ts": datetime.utcnow().isoformat() + "Z"
            })
        except Exception as e:
            print(f"⚠️ Failed to fetch or append student flashcard message: {e}")
            return {"error": "❌ Failed to fetch pointer or append message"}

        # ✅ GPT mentor reply
        prompt = """
You are a senior NEET-PG mentor with 30 years’ experience.
You are helping a student with flashcard-based rapid revision.

You are given the full flashcard conversation log — a list of chat objects:
[{ "role": "mentor" | "student", "content": "..." }]

👉 Reply only to the latest student message.
🧠 Reply in natural Markdown using Unicode symbols, ≤100 words, concise and high-yield.
"""
        mentor_reply = None
        gpt_status = "success"

        try:
            mentor_reply = chat_with_gpt(prompt, convo_log)
            if not isinstance(mentor_reply, str):
                mentor_reply = str(mentor_reply)
        except Exception as e:
            print(f"❌ GPT call failed for student {student_id}: {e}")
            mentor_reply = "⚠️ I'm having a small technical hiccup 🤖. Please try again soon!"
            gpt_status = "failed"

        convo_log.append({
            "role": "assistant",
            "content": mentor_reply,
            "ts": datetime.utcnow().isoformat() + "Z"
        })

        db_status = "success"
        try:
            supabase.table("student_flashcard_pointer") \
                .update({"conversation_log": convo_log}) \
                .eq("pointer_id", pointer_id) \
                .execute()
        except Exception as e:
            db_status = "failed"
            print(f"⚠️ DB update failed for flashcard conversation: {e}")

        return {
            "mentor_reply": mentor_reply,
            "context_used": True,
            "db_update_status": db_status,
            "gpt_status": gpt_status
        }

    # ───────────────────────────────
    # 🔵 3️⃣ NEXT_FLASHCARD
    # ───────────────────────────────
    elif action == "next_flashcard":
        rpc_data = call_rpc("next_flashcard_orchestra", {
            "p_student_id": student_id,
            "p_subject_id": subject_id
        })
        if not rpc_data:
            return {"error": "❌ next_flashcard_orchestra RPC failed"}

        phase_type = rpc_data.get("phase_type")
        phase_json = rpc_data.get("phase_json")
        mentor_reply = rpc_data.get("mentor_reply")
        react_order_final = rpc_data.get("react_order_final")
        concept = rpc_data.get("concept")
        subject = rpc_data.get("subject")

        print("🧩 phase_json for NEXT_FLASHCARD:")
        try:
            print(json.dumps(phase_json, indent=2)[:500])
        except Exception:
            print("⚠️ Could not print phase_json")

        safe_phase_json = _make_json_safe(phase_json)
        safe_mentor_reply = _make_json_safe(mentor_reply)

        try:
            call_rpc("update_flashcard_pointer_status", {
                "p_student_id": student_id,
                "p_subject_id": subject_id,
                "p_react_order_final": react_order_final,
                "p_phase_json": safe_phase_json,
                "p_mentor_reply": safe_mentor_reply
            })
        except Exception as e:
            print(f"⚠️ update_flashcard_pointer_status failed in NEXT: {e}")

        return {
            "student_id": student_id,
            "react_order_final": react_order_final,
            "phase_type": phase_type,
            "phase_json": safe_phase_json,
            "mentor_reply": safe_mentor_reply,
            "concept": concept,
            "subject": subject
        }

    else:
        return {"error": f"Unknown flashcard action '{action}'"}


# ───────────────────────────────────────────────
# 🟠 SUBMIT_FLASHCARD_PROGRESS
# ───────────────────────────────────────────────
@app.post("/submit_flashcard_progress")
async def submit_flashcard_progress(request: Request):
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
