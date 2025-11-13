from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from supabase_client import call_rpc, supabase
from gpt_utils import chat_with_gpt
import json, uuid

# ───────────────────────────────────────────────
# Initialize FastAPI app
# ───────────────────────────────────────────────
app = FastAPI(title="Flashcard Orchestra API", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────────────────────────────────────────────
# JSON-safe UUID conversion
# ───────────────────────────────────────────────
def make_json_safe(data):
    if isinstance(data, uuid.UUID):
        return str(data)
    if isinstance(data, dict):
        return {k: make_json_safe(v) for k, v in data.items()}
    if isinstance(data, list):
        return [make_json_safe(v) for v in data]
    return data


# ───────────────────────────────────────────────
# MASTER ROUTE
# ───────────────────────────────────────────────
@app.post("/flashcard_orchestrate")
async def flashcard_orchestrate(request: Request):
    payload = await request.json()
    action = payload.get("action")
    student_id = payload.get("student_id")
    subject_id = payload.get("subject_id")
    message = payload.get("message")

    print(f"⚡ Flashcard Action = {action} | Student = {student_id}")

    # ======================================================
    # 1️⃣ START FLASHCARD LEARNING FLOW
    # ======================================================
    if action == "start_flashcard":
        rpc_data = call_rpc("start_flashcard_orchestra", {
            "p_student_id": student_id,
            "p_subject_id": subject_id
        })

        if not rpc_data:
            return {"error": "❌ start_flashcard_orchestra RPC failed"}

        safe_phase = make_json_safe(rpc_data.get("phase_json"))
        safe_reply = make_json_safe(rpc_data.get("mentor_reply"))

        # UPDATE POINTER
        try:
            call_rpc("update_flashcard_pointer_status", {
                "p_student_id": student_id,
                "p_subject_id": subject_id,
                "p_react_order_final": rpc_data.get("react_order_final"),
                "p_phase_json": safe_phase,
                "p_mentor_reply": safe_reply
            })
        except Exception as e:
            print(f"⚠️ update_flashcard_pointer_status failed: {e}")

        return {
            "student_id": student_id,
            "subject_id": subject_id,
            "react_order_final": rpc_data.get("react_order_final"),
            "phase_json": safe_phase,
            "mentor_reply": safe_reply,
            "concept": rpc_data.get("concept"),
            "seq_num": rpc_data.get("seq_num"),
            "total_count": rpc_data.get("total_count"),
            "phase_type": rpc_data.get("phase_type")
        }

    # ======================================================
    # 2️⃣ CHAT INSIDE FLASHCARD FLOW
    # ======================================================
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
                return {"error": "⚠️ No active flashcard pointer found"}

            pointer = res.data[0]
            pointer_id = pointer["pointer_id"]
            convo_log = pointer.get("conversation_log", [])
            convo_log.append({"role": "student", "content": message, "ts": datetime.utcnow().isoformat()})
        except Exception as e:
            print(f"⚠️ chat fetch failed: {e}")
            return {"error": "❌ Chat pointer fetch failed"}

        # GPT RESPONSE
        prompt = """
You are a senior NEET-PG mentor with 30 years of experience.
Reply concisely (≤80 words), clinically relevant, using Unicode where useful.
"""

        try:
            mentor_reply = chat_with_gpt(prompt, convo_log)
            status = "success"
        except:
            mentor_reply = "⚠️ I'm facing a temporary glitch. Try again."
            status = "failed"

        convo_log.append({"role": "assistant", "content": mentor_reply, "ts": datetime.utcnow().isoformat()})

        # UPDATE DB
        try:
            supabase.table("student_flashcard_pointer")\
                .update({"conversation_log": convo_log})\
                .eq("pointer_id", pointer_id)\
                .execute()
        except Exception as e:
            print(f"⚠️ chat save failed: {e}")

        return {
            "mentor_reply": mentor_reply,
            "status": status
        }

    # ======================================================
    # 3️⃣ NEXT FLASHCARD IN LEARNING FLOW
    # ======================================================
    elif action == "next_flashcard":
        rpc_data = call_rpc("next_flashcard_orchestra", {
            "p_student_id": student_id,
            "p_subject_id": subject_id
        })

        if not rpc_data:
            return {"error": "❌ next_flashcard_orchestra RPC failed"}

        safe_phase = make_json_safe(rpc_data.get("phase_json"))
        safe_reply = make_json_safe(rpc_data.get("mentor_reply"))

        # UPDATE POINTER
        try:
            call_rpc("update_flashcard_pointer_status", {
                "p_student_id": student_id,
                "p_subject_id": subject_id,
                "p_react_order_final": rpc_data.get("react_order_final"),
                "p_phase_json": safe_phase,
                "p_mentor_reply": safe_reply
            })
        except Exception as e:
            print(f"⚠️ pointer update failed: {e}")

        return {
            "student_id": student_id,
            "subject_id": subject_id,
            "react_order_final": rpc_data.get("react_order_final"),
            "phase_json": safe_phase,
            "mentor_reply": safe_reply,
            "concept": rpc_data.get("concept"),
            "seq_num": rpc_data.get("seq_num"),
            "total_count": rpc_data.get("total_count"),
            "phase_type": rpc_data.get("phase_type")
        }

    # ======================================================
    # 4️⃣ REVIEW COMPLETED FLASHCARDS — START
    # ======================================================
    elif action == "review_completed_start_flashcard":
        print("🔍 Fetching first completed flashcard…")

        res = (
            supabase.table("student_flashcard_pointer")
            .select("*")
            .eq("student_id", student_id)
            .eq("subject_id", subject_id)
            .eq("is_completed", True)
            .order("react_order_final", asc=True)
            .limit(1)
            .execute()
        )

        return {"review_item": make_json_safe(res.data[0]) if res.data else None}

    # ======================================================
    # 5️⃣ REVIEW COMPLETED FLASHCARDS — NEXT
    # ======================================================
    elif action == "review_completed_next_flashcard":
        current_order = payload.get("react_order_final")

        res = (
            supabase.table("student_flashcard_pointer")
            .select("*")
            .eq("student_id", student_id)
            .eq("subject_id", subject_id)
            .eq("is_completed", True)
            .gt("react_order_final", current_order)
            .order("react_order_final", asc=True)
            .limit(1)
            .execute()
        )

        return {"review_item": make_json_safe(res.data[0]) if res.data else None}

    # ======================================================
    # 6️⃣ BOOKMARK REVIEW — START
    # ======================================================
    elif action == "start_bookmarked_revision":
        rpc_data = call_rpc("get_bookmarked_flashcards", {
            "p_student_id": student_id,
            "p_subject_id": subject_id
        })

        if not rpc_data:
            return {"error": "❌ get_bookmarked_flashcards failed"}

        return make_json_safe(rpc_data)

    # ======================================================
    # 7️⃣ BOOKMARK REVIEW — NEXT
    # ======================================================
    elif action == "next_bookmarked_flashcard":
        last_ts = payload.get("last_updated_time")

        rpc_data = call_rpc("get_next_bookmarked_flashcard", {
            "p_student_id": student_id,
            "p_subject_id": subject_id,
            "p_last_updated_time": last_ts
        })

        return make_json_safe(rpc_data)

    # ======================================================
    # ❌ UNKNOWN ACTION
    # ======================================================
    else:
        return {"error": f"Unknown action '{action}'"}


# ───────────────────────────────────────────────
# Health
# ───────────────────────────────────────────────
@app.get("/")
def home():
    return {"message": "🧠 Flashcard Orchestra API v4.0 is running!"}
