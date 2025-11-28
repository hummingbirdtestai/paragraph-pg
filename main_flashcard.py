from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from supabase_client import call_rpc, supabase
from gpt_utils import chat_with_gpt
import json, uuid

# ───────────────────────────────────────────────
# Initialize FastAPI app
# ───────────────────────────────────────────────
app = FastAPI(title="Flashcard Orchestra API", version="4.1.0")

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
# ⭐ NEW: FETCH CHAT FOR BOOKMARKED FLASHCARDS
# ───────────────────────────────────────────────
def fetch_bookmark_chat(student_id, subject_id, flashcard_id, updated_time):
    try:
        res = (
            supabase.table("flashcard_review_bookmarks_chat")
            .select("conversation_log")
            .eq("student_id", student_id)
            .eq("subject_id", subject_id)
            .eq("flashcard_id", flashcard_id)
            .eq("flashcard_updated_time", updated_time)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0].get("conversation_log", [])
    except:
        pass

    return []


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
        rpc_data = call_rpc(
            "start_flashcard_orchestra",
            {"p_student_id": student_id, "p_subject_id": subject_id},
        )

        if not rpc_data:
            return {
                "completed": True,
                "message": "No more flashcards available"
            }

        safe_phase = make_json_safe(rpc_data.get("phase_json"))
        safe_reply = make_json_safe(rpc_data.get("mentor_reply"))

        try:
            call_rpc(
                "update_flashcard_pointer_status",
                {
                    "p_student_id": student_id,
                    "p_subject_id": subject_id,
                    "p_react_order_final": rpc_data.get("react_order_final"),
                    "p_phase_json": safe_phase,
                    "p_mentor_reply": safe_reply,
                },
            )
        except:
            pass

        return {
            "student_id": student_id,
            "subject_id": subject_id,
            "react_order_final": rpc_data.get("react_order_final"),
            "phase_json": safe_phase,
            "mentor_reply": safe_reply,
            "concept": rpc_data.get("concept"),
            "seq_num": rpc_data.get("seq_num"),
            "total_count": rpc_data.get("total_count"),
            "phase_type": rpc_data.get("phase_type"),
            "element_id": rpc_data.get("element_id"),
            "is_bookmark": rpc_data.get("is_bookmark"),
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
            convo_log.append(
                {
                    "role": "student",
                    "content": message,
                    "ts": datetime.utcnow().isoformat(),
                }
            )
        except:
            return {"error": "❌ Chat pointer fetch failed"}

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

        convo_log.append(
            {
                "role": "assistant",
                "content": mentor_reply,
                "ts": datetime.utcnow().isoformat(),
            }
        )

        try:
            supabase.table("student_flashcard_pointer").update(
                {"conversation_log": convo_log}
            ).eq("pointer_id", pointer_id).execute()
        except:
            pass

        return {"mentor_reply": mentor_reply, "status": status}


    # ======================================================
    # 3️⃣ NEXT FLASHCARD IN LEARNING FLOW
    # ======================================================
    elif action == "next_flashcard":
        rpc_data = call_rpc(
            "next_flashcard_orchestra",
            {"p_student_id": student_id, "p_subject_id": subject_id},
        )

        if not rpc_data:
            return {
                "completed": True,
                "message": "All flashcards completed"
            }

        safe_phase = make_json_safe(rpc_data.get("phase_json"))
        safe_reply = make_json_safe(rpc_data.get("mentor_reply"))

        try:
            call_rpc(
                "update_flashcard_pointer_status",
                {
                    "p_student_id": student_id,
                    "p_subject_id": subject_id,
                    "p_react_order_final": rpc_data.get("react_order_final"),
                    "p_phase_json": safe_phase,
                    "p_mentor_reply": safe_reply,
                },
            )
        except:
            pass

        return {
            "student_id": student_id,
            "subject_id": subject_id,
            "react_order_final": rpc_data.get("react_order_final"),
            "phase_json": safe_phase,
            "mentor_reply": safe_reply,
            "concept": rpc_data.get("concept"),
            "seq_num": rpc_data.get("seq_num"),
            "total_count": rpc_data.get("total_count"),
            "phase_type": rpc_data.get("phase_type"),
            "element_id": rpc_data.get("element_id"),
            "is_bookmark": rpc_data.get("is_bookmark"),
        }


    # ======================================================
    # 4️⃣ REVIEW COMPLETED FLASHCARDS — START
    # ======================================================
    elif action == "review_completed_start_flashcard":
        rpc_data = call_rpc(
            "review_completed_start_flashcard",
            {"p_student_id": student_id, "p_subject_id": subject_id},
        )

        if not rpc_data:
            return {
                "review_item": None,
                "review_completed": False,
                "no_bookmarks": True
            }

        return {
            "review_item": make_json_safe(rpc_data),
            "review_completed": False,
            "no_bookmarks": False
        }


    # ======================================================
    # 5️⃣ REVIEW COMPLETED FLASHCARDS — NEXT
    # ======================================================
    elif action == "review_completed_next_flashcard":
        current_order = payload.get("react_order_final")

        rpc_data = call_rpc(
            "review_completed_next_flashcard",
            {
                "p_student_id": student_id,
                "p_subject_id": subject_id,
                "p_react_order_final": current_order,
            }
        )

        if not rpc_data:
            return {
                "review_item": None,
                "review_completed": True
            }

        return {
            "review_item": make_json_safe(rpc_data),
            "review_completed": False
        }


    # ======================================================
    # 6️⃣ BOOKMARK REVIEW — START  (UPDATED)
    # ======================================================
    elif action == "start_bookmarked_revision":
        rpc_data = call_rpc(
            "get_bookmarked_flashcards",
            {"p_student_id": student_id, "p_subject_id": subject_id},
        )

        if not rpc_data:
            return None

        item = make_json_safe(rpc_data)

        # ⭐ Inject bookmark chat history
        item["conversation_log"] = fetch_bookmark_chat(
            student_id,
            subject_id,
            item.get("element_id") or item.get("flashcard_json", {}).get("id"),
            item.get("updated_time")
        )

        return item


    # ======================================================
    # 7️⃣ BOOKMARK REVIEW — NEXT  (UPDATED)
    # ======================================================
    elif action == "next_bookmarked_flashcard":
        last_ts = payload.get("last_updated_time")

        rpc_data = call_rpc(
            "get_next_bookmarked_flashcard",
            {
                "p_student_id": student_id,
                "p_subject_id": subject_id,
                "p_last_updated_time": last_ts,
            },
        )

        item = make_json_safe(rpc_data)

        if item:
            # ⭐ Inject chat history
            item["conversation_log"] = fetch_bookmark_chat(
                student_id,
                subject_id,
                item.get("element_id") or item.get("flashcard_json", {}).get("id"),
                item.get("updated_time")
            )

        return item


    # ======================================================
    # 8️⃣ BOOKMARK REVIEW CHAT (stores conversation in DB)
    # ======================================================
    elif action == "chat_review_flashcard_bookmarks":
        flashcard_id = payload.get("flashcard_id")
        flashcard_updated_time = payload.get("flashcard_updated_time")
        message = payload.get("message")

        if not flashcard_id or not flashcard_updated_time:
            return {"error": "Missing flashcard_id or flashcard_updated_time in bookmark chat"}

        try:
            res = (
                supabase.table("flashcard_review_bookmarks_chat")
                .select("id, conversation_log")
                .eq("student_id", student_id)
                .eq("subject_id", subject_id)
                .eq("flashcard_id", flashcard_id)
                .eq("flashcard_updated_time", flashcard_updated_time)
                .order("updated_at", desc=True)
                .limit(1)
                .execute()
            )
        except:
            res = None

        if res and res.data:
            chat_row = res.data[0]
            chat_id = chat_row["id"]
            convo_log = chat_row["conversation_log"] or []
        else:
            chat_id = None
            convo_log = []

        convo_log.append({
            "role": "student",
            "content": message,
            "ts": datetime.utcnow().isoformat()
        })

        prompt = """
You are a senior NEET-PG mentor with 30 years of experience.
Reply concisely (≤80 words), clinically relevant, exam-focused.
"""

        try:
            mentor_reply = chat_with_gpt(prompt, convo_log)
        except:
            mentor_reply = "⚠️ I'm facing a temporary glitch. Try again."

        convo_log.append({
            "role": "assistant",
            "content": mentor_reply,
            "ts": datetime.utcnow().isoformat()
        })

        try:
            if chat_id:
                supabase.table("flashcard_review_bookmarks_chat").update({
                    "conversation_log": convo_log,
                    "updated_at": datetime.utcnow().isoformat()
                }).eq("id", chat_id).execute()
            else:
                supabase.table("flashcard_review_bookmarks_chat").insert({
                    "student_id": student_id,
                    "subject_id": subject_id,
                    "flashcard_id": flashcard_id,
                    "flashcard_updated_time": flashcard_updated_time,
                    "conversation_log": convo_log
                }).execute()
        except:
            pass

        return {
            "mentor_reply": mentor_reply,
            "conversation_log": convo_log
        }


    # ======================================================
    # ❌ UNKNOWN ACTION
    # ======================================================
    else:
        return {"error": f"Unknown action '{action}'"}


# ───────────────────────────────────────────────
# Health Check
# ───────────────────────────────────────────────
@app.get("/")
def home():
    return {"message": "🧠 Flashcard Orchestra API v4.1 running with enriched review flow ✅"}
