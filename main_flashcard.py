from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from supabase_client import call_rpc, supabase
from gpt_utils import chat_with_gpt
import json, uuid

# ───────────────────────────────────────────────
# Initialize FastAPI app
# ───────────────────────────────────────────────
app = FastAPI(title="Flashcard Orchestra API", version="2.4.0")

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
    # 1️⃣ START_FLASHCARD (unchanged)
    # ───────────────────────────────
    if action == "start_flashcard":
        rpc_data = call_rpc("start_flashcard_orchestra", {
            "p_student_id": student_id,
            "p_subject_id": subject_id
        })
        if not rpc_data:
            return {"error": "❌ start_flashcard_orchestra RPC failed"}

        safe_phase_json = _make_json_safe(rpc_data.get("phase_json"))
        safe_mentor_reply = _make_json_safe(rpc_data.get("mentor_reply"))

        try:
            call_rpc("update_flashcard_pointer_status", {
                "p_student_id": student_id,
                "p_subject_id": subject_id,
                "p_react_order_final": rpc_data.get("react_order_final"),
                "p_phase_json": safe_phase_json,
                "p_mentor_reply": safe_mentor_reply
            })
        except Exception as e:
            print(f"⚠️ RPC update_flashcard_pointer_status failed: {e}")

        return {
            "student_id": student_id,
            "react_order_final": rpc_data.get("react_order_final"),
            "phase_type": rpc_data.get("phase_type"),
            "phase_json": safe_phase_json,
            "mentor_reply": safe_mentor_reply,
            "concept": rpc_data.get("concept"),
            "subject": rpc_data.get("subject"),
            "seq_num": rpc_data.get("seq_num"),
            "total_count": rpc_data.get("total_count")
        }

    # ───────────────────────────────
    # 2️⃣ CHAT_FLASHCARD (unchanged)
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

        prompt = """
You are a senior NEET-PG mentor with 30 years’ experience.
You are helping a student with flashcard-based rapid revision.
You are given the full flashcard conversation log — a list of chat objects:
[{ "role": "mentor" | "student", "content": "..." }]
👉 Reply only to the latest student message.
🧠 Reply in Markdown using Unicode symbols, ≤100 words, concise and high-yield.
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

        try:
            supabase.table("student_flashcard_pointer") \
                .update({"conversation_log": convo_log}) \
                .eq("pointer_id", pointer_id) \
                .execute()
        except Exception as e:
            print(f"⚠️ DB update failed for flashcard conversation: {e}")

        return {
            "mentor_reply": mentor_reply,
            "context_used": True,
            "gpt_status": gpt_status
        }

    # ───────────────────────────────
    # 3️⃣ START_BOOKMARKED_REVISION (✅ updated)
    # ───────────────────────────────
    elif action == "start_bookmarked_revision":
        rpc_data = call_rpc("get_bookmarked_flashcards", {
            "p_student_id": student_id,
            "p_subject_id": subject_id
        })
        if not rpc_data:
            return {"error": "❌ get_bookmarked_flashcards RPC failed"}

        safe_data = _make_json_safe(rpc_data)
        element_id = safe_data.get("element_id")  # 🔗 flashcard_id = element_id
        updated_time = safe_data.get("updated_time")

        # ✅ Try to fetch existing chat for this flashcard
        chat_log = []
        try:
            chat_res = (
                supabase.table("flashcard_review_bookmarks_chat")
                .select("conversation_log")
                .eq("student_id", student_id)
                .eq("flashcard_id", element_id)
                .eq("flashcard_updated_time", updated_time)
                .limit(1)
                .execute()
            )
            if chat_res.data and len(chat_res.data) > 0:
                chat_log = chat_res.data[0].get("conversation_log", [])
        except Exception as e:
            print(f"⚠️ Could not fetch existing review chat: {e}")

        return {
            "student_id": student_id,
            "subject_id": safe_data.get("subject_id"),
            "subject_name": safe_data.get("subject_name"),
            "type": safe_data.get("type"),
            "flashcard_json": safe_data.get("flashcard_json"),
            "mentor_reply": safe_data.get("mentor_reply"),
            "concept": safe_data.get("concept"),
            "updated_time": updated_time,
            "seq_num": safe_data.get("seq_num"),
            "total_count": safe_data.get("total_count"),
            "conversation_log": chat_log  # ✅ merged chat
        }

    # ───────────────────────────────
    # 4️⃣ NEXT_BOOKMARKED_FLASHCARD (✅ updated)
    # ───────────────────────────────
    elif action == "next_bookmarked_flashcard":
        last_updated_time = payload.get("last_updated_time")

        rpc_data = call_rpc("get_next_bookmarked_flashcard", {
            "p_student_id": student_id,
            "p_subject_id": subject_id,
            "p_last_updated_time": last_updated_time
        })
        if not rpc_data:
            return {"error": "❌ get_next_bookmarked_flashcard RPC failed"}

        safe_data = _make_json_safe(rpc_data)
        element_id = safe_data.get("element_id")
        updated_time = safe_data.get("updated_time")

        chat_log = []
        try:
            chat_res = (
                supabase.table("flashcard_review_bookmarks_chat")
                .select("conversation_log")
                .eq("student_id", student_id)
                .eq("flashcard_id", element_id)
                .eq("flashcard_updated_time", updated_time)
                .limit(1)
                .execute()
            )
            if chat_res.data and len(chat_res.data) > 0:
                chat_log = chat_res.data[0].get("conversation_log", [])
        except Exception as e:
            print(f"⚠️ Could not fetch chat in NEXT: {e}")

        return {
            "student_id": student_id,
            "subject_id": safe_data.get("subject_id"),
            "subject_name": safe_data.get("subject_name"),
            "type": safe_data.get("type"),
            "flashcard_json": safe_data.get("flashcard_json"),
            "mentor_reply": safe_data.get("mentor_reply"),
            "concept": safe_data.get("concept"),
            "updated_time": updated_time,
            "seq_num": safe_data.get("seq_num"),
            "total_count": safe_data.get("total_count"),
            "conversation_log": chat_log  # ✅ merged chat
        }

    # ───────────────────────────────
    # 5️⃣ CHAT_REVIEW_FLASHCARD_BOOKMARKS (✅ flashcard_id auto-fill)
    # ───────────────────────────────
    elif action == "chat_review_flashcard_bookmarks":
        subject_id = payload.get("subject_id")
        flashcard_id = payload.get("flashcard_id")
        flashcard_updated_time = payload.get("flashcard_updated_time")
        message = payload.get("message")

        print(f"💬 [Review Flashcard Chat] Student={student_id}, Flashcard={flashcard_id}")

        convo_log = []
        chat_id = None

        # 1️⃣ Fetch existing conversation
        try:
            res = (
                supabase.table("flashcard_review_bookmarks_chat")
                .select("id, conversation_log")
                .eq("student_id", student_id)
                .eq("flashcard_updated_time", flashcard_updated_time)
                .limit(1)
                .execute()
            )
            if res.data:
                chat_id = res.data[0]["id"]
                convo_log = res.data[0].get("conversation_log", [])
        except Exception as e:
            print(f"⚠️ Fetch existing chat failed: {e}")

        # 2️⃣ Append new student message
        convo_log.append({
            "role": "student",
            "content": message,
            "ts": datetime.utcnow().isoformat() + "Z"
        })

        # 3️⃣ GPT mentor reply
        prompt = """
You are a senior NEET-PG mentor with 30 years’ experience.
You are helping a student with flashcard-based rapid revision.
You are given the full flashcard conversation log — a list of chat objects:
[{ "role": "mentor" | "student", "content": "..." }]
👉 Reply only to the latest student message.
🧠 Reply in Markdown using Unicode symbols, ≤100 words, concise and high-yield.
"""
        mentor_reply = None
        gpt_status = "success"
        try:
            mentor_reply = chat_with_gpt(prompt, convo_log)
        except Exception as e:
            print(f"❌ GPT failed: {e}")
            mentor_reply = "⚠️ I'm facing a small technical hiccup 🤖. Please try again!"
            gpt_status = "failed"

        convo_log.append({
            "role": "assistant",
            "content": mentor_reply,
            "ts": datetime.utcnow().isoformat() + "Z"
        })

        # 4️⃣ Insert or update DB (auto-fill flashcard_id)
        try:
            if chat_id:
                supabase.table("flashcard_review_bookmarks_chat").update({
                    "conversation_log": convo_log,
                    "updated_at": datetime.utcnow().isoformat() + "Z"
                }).eq("id", chat_id).execute()
            else:
                supabase.table("flashcard_review_bookmarks_chat").insert({
                    "student_id": student_id,
                    "subject_id": subject_id,
                    "flashcard_id": flashcard_id,  # ✅ auto from element_id
                    "flashcard_updated_time": flashcard_updated_time,
                    "conversation_log": convo_log
                }).execute()
        except Exception as e:
            print(f"⚠️ DB insert/update failed: {e}")

        return {
            "mentor_reply": mentor_reply,
            "gpt_status": gpt_status,
            "student_id": student_id,
            "flashcard_id": flashcard_id,
            "flashcard_updated_time": flashcard_updated_time,
            "context_used": True
        }

    else:
        return {"error": f"Unknown flashcard action '{action}'"}


# ───────────────────────────────────────────────
# Health Check
# ───────────────────────────────────────────────
@app.get("/")
def home():
    return {"message": "🧠 Flashcard Orchestra API is running successfully!"}
