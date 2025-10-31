from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from supabase_client import call_rpc, supabase
from gpt_utils import chat_with_gpt
import json, uuid

# ───────────────────────────────────────────────
# Initialize FastAPI app
# ───────────────────────────────────────────────
app = FastAPI(title="Flashcard Orchestra API", version="2.3.0")

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

    print("\n" + "═" * 80)
    print(f"🎬 Flashcard Action: {action}")
    print(f"🧑‍🎓 Student ID: {student_id}")
    print(f"📘 Subject ID: {subject_id}")
    print("═" * 80 + "\n")

    # ───────────────────────────────
    # 🟣 1️⃣ START_BOOKMARKED_REVISION
    # ───────────────────────────────
    if action == "start_bookmarked_revision":
        print("🟣 START_BOOKMARKED_REVISION CALLED")
        rpc_data = call_rpc("get_bookmarked_flashcards", {
            "p_student_id": student_id,
            "p_subject_id": subject_id
        })
        print(f"📡 RPC get_bookmarked_flashcards returned:\n{json.dumps(rpc_data, indent=2, default=str)}")

        if not rpc_data:
            return {"error": "❌ get_bookmarked_flashcards RPC failed"}

        safe_data = _make_json_safe(rpc_data)
        flashcard_id = safe_data.get("element_id")
        print(f"🧩 Extracted flashcard_id = {flashcard_id}")

        convo_log = []
        if flashcard_id:
            try:
                chat_res = (
                    supabase.table("flashcard_review_bookmarks_chat")
                    .select("id, conversation_log")
                    .eq("student_id", student_id)
                    .eq("flashcard_id", flashcard_id)
                    .order("updated_at", desc=True)
                    .limit(1)
                    .execute()
                )
                print(f"🔍 Chat lookup result: {chat_res.data}")
                if chat_res.data and chat_res.data[0].get("conversation_log"):
                    convo_log = chat_res.data[0]["conversation_log"]
            except Exception as e:
                print(f"⚠️ Could not fetch existing chat: {e}")

        print(f"💬 Final conversation_log length = {len(convo_log)}")

        return {
            "student_id": student_id,
            "subject_id": safe_data.get("subject_id"),
            "subject_name": safe_data.get("subject_name"),
            "type": safe_data.get("type"),
            "phase_type": safe_data.get("phase_type"),
            "flashcard_json": safe_data.get("flashcard_json"),
            "mentor_reply": safe_data.get("mentor_reply"),
            "concept": safe_data.get("concept"),
            "updated_time": safe_data.get("updated_time"),
            "seq_num": safe_data.get("seq_num"),
            "total_count": safe_data.get("total_count"),
            "flashcard_id": flashcard_id,  # ✅ added
            "conversation_log": convo_log
        }

    # ───────────────────────────────
    # 🟠 2️⃣ NEXT_BOOKMARKED_FLASHCARD
    # ───────────────────────────────
    elif action == "next_bookmarked_flashcard":
        print("🟠 NEXT_BOOKMARKED_FLASHCARD CALLED")
        last_updated_time = payload.get("last_updated_time")
        rpc_data = call_rpc("get_next_bookmarked_flashcard", {
            "p_student_id": student_id,
            "p_subject_id": subject_id,
            "p_last_updated_time": last_updated_time
        })
        print(f"📡 RPC get_next_bookmarked_flashcard returned:\n{json.dumps(rpc_data, indent=2, default=str)}")

        if not rpc_data:
            return {"error": "❌ get_next_bookmarked_flashcard RPC failed"}

        safe_data = _make_json_safe(rpc_data)
        flashcard_id = safe_data.get("element_id")
        print(f"🧩 Extracted flashcard_id = {flashcard_id}")

        convo_log = []
        if flashcard_id:
            try:
                chat_res = (
                    supabase.table("flashcard_review_bookmarks_chat")
                    .select("id, conversation_log")
                    .eq("student_id", student_id)
                    .eq("flashcard_id", flashcard_id)
                    .order("updated_at", desc=True)
                    .limit(1)
                    .execute()
                )
                print(f"🔍 Chat lookup result: {chat_res.data}")
                if chat_res.data and chat_res.data[0].get("conversation_log"):
                    convo_log = chat_res.data[0]["conversation_log"]
            except Exception as e:
                print(f"⚠️ Could not fetch chat for next card: {e}")

        print(f"💬 Final conversation_log length = {len(convo_log)}")

        return {
            "student_id": student_id,
            "subject_id": safe_data.get("subject_id"),
            "subject_name": safe_data.get("subject_name"),
            "type": safe_data.get("type"),
            "phase_type": safe_data.get("phase_type"),
            "flashcard_json": safe_data.get("flashcard_json"),
            "mentor_reply": safe_data.get("mentor_reply"),
            "concept": safe_data.get("concept"),
            "updated_time": safe_data.get("updated_time"),
            "seq_num": safe_data.get("seq_num"),
            "total_count": safe_data.get("total_count"),
            "flashcard_id": flashcard_id,  # ✅ added
            "conversation_log": convo_log
        }

    # ───────────────────────────────
    # 🟣 3️⃣ CHAT_REVIEW_FLASHCARD_BOOKMARKS
    # ───────────────────────────────
    elif action == "chat_review_flashcard_bookmarks":
        print("🟣 CHAT_REVIEW_FLASHCARD_BOOKMARKS CALLED")
        flashcard_id = (
            payload.get("flashcard_id") or
            payload.get("element_id") or
            (payload.get("flashcard_json") or {}).get("id")
        )
        flashcard_updated_time = payload.get("flashcard_updated_time")
        message = payload.get("message")

        if not flashcard_id:
            return {"error": "❌ Missing flashcard_id in payload"}

        convo_log, chat_id = [], None

        # ① Fetch existing chat if available
        try:
            res = (
                supabase.table("flashcard_review_bookmarks_chat")
                .select("id, conversation_log")
                .eq("student_id", student_id)
                .eq("flashcard_id", flashcard_id)
                .order("updated_at", desc=True)
                .limit(1)
                .execute()
            )
            if res.data:
                chat_id = res.data[0]["id"]
                convo_log = res.data[0].get("conversation_log", [])
                if isinstance(convo_log, str):
                    convo_log = json.loads(convo_log)
        except Exception as e:
            print(f"⚠️ Chat lookup failed: {e}")

        # ② Append new messages
        convo_log.append({
            "role": "student",
            "content": message,
            "ts": datetime.utcnow().isoformat() + "Z"
        })

        prompt = """
You are a senior NEET-PG mentor with 30 years’ experience.
You are helping a student revise bookmarked flashcards.
You are given the full chat log — a list of message objects:
[{ "role": "mentor" | "student", "content": "..." }]
👉 Reply only to the latest student message.
🧠 Reply in Markdown using Unicode symbols, ≤100 words, concise and high-yield.
"""
        try:
            mentor_reply = chat_with_gpt(prompt, convo_log)
        except Exception as e:
            print(f"❌ GPT failed: {e}")
            mentor_reply = "⚠️ Sorry, I'm facing a technical hiccup 🤖."

        convo_log.append({
            "role": "assistant",
            "content": mentor_reply,
            "ts": datetime.utcnow().isoformat() + "Z"
        })

        # ③ Save conversation (update or insert)
        try:
            if chat_id:
                print(f"📝 Updating chat id={chat_id}")
                supabase.table("flashcard_review_bookmarks_chat").update({
                    "conversation_log": convo_log,
                    "updated_at": datetime.utcnow().isoformat() + "Z"
                }).eq("id", chat_id).execute()
            else:
                print("🆕 Inserting new chat row...")
                supabase.table("flashcard_review_bookmarks_chat").insert({
                    "student_id": student_id,
                    "subject_id": subject_id,
                    "flashcard_id": flashcard_id,  # ✅ never null now
                    "flashcard_updated_time": flashcard_updated_time,
                    "conversation_log": convo_log
                }).execute()
        except Exception as e:
            print(f"⚠️ DB insert/update failed: {e}")

        return {
            "mentor_reply": mentor_reply,
            "student_id": student_id,
            "flashcard_id": flashcard_id,
            "conversation_log": convo_log,
            "context_used": True
        }

    # ───────────────────────────────
    # Default fallback
    # ───────────────────────────────
    else:
        return {"error": f"Unknown flashcard action '{action}'"}


# ───────────────────────────────────────────────
# Health Check
# ───────────────────────────────────────────────
@app.get("/")
def home():
    return {"message": "🧠 Flashcard Orchestra API is running successfully!"}
