from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from supabase_client import call_rpc, supabase
from gpt_utils import chat_with_gpt
import json

# ───────────────────────────────────────────────
# Initialize FastAPI app
# ───────────────────────────────────────────────
app = FastAPI(title="Paragraph Orchestra API", version="2.4.0")

# ✅ Allow frontend (Expo / Web / React) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────────────────────────────────────────────
# Master Endpoint — handles all actions
# ───────────────────────────────────────────────
@app.post("/orchestrate")
async def orchestrate(request: Request):
    payload = await request.json()
    action = payload.get("action")
    student_id = payload.get("student_id")
    subject_id = payload.get("subject_id")
    message = payload.get("message")

    print(f"🎬 Action = {action}, Student = {student_id}, Subject = {subject_id}")

    # ───────────────────────────────
    # 🟢 1️⃣ START (chapter flow)
    # ───────────────────────────────
    if action == "start":
        rpc_data = call_rpc("start_orchestra", {
            "p_student_id": student_id,
            "p_subject_id": subject_id
        })
        if not rpc_data or "phase_type" not in rpc_data:
            print(f"⚠️ RPC failed or returned empty → {rpc_data}")
            return {"error": "❌ start_orchestra RPC failed"}

        return {
            "student_id": student_id,
            "subject_id": subject_id,
            "react_order_final": rpc_data.get("react_order_final"),
            "phase_type": rpc_data.get("phase_type"),
            "phase_json": rpc_data.get("phase_json"),
            "mentor_reply": rpc_data.get("mentor_reply"),
            "seq_num": rpc_data.get("seq_num"),
            "total_count": rpc_data.get("total_count"),
        }

    # ───────────────────────────────
    # 🟡 2️⃣ CHAT — main chapter chat
    # ───────────────────────────────
    elif action == "chat":
        pointer_id = None
        convo_log = []

        try:
            res = (
                supabase.table("student_phase_pointer")
                .select("pointer_id, conversation_log")
                .eq("student_id", student_id)
                .eq("subject_id", subject_id)
                .order("updated_at", desc=True)
                .limit(1)
                .execute()
            )

            if not res.data:
                return {"error": "⚠️ No active pointer for this subject"}

            pointer = res.data[0]
            pointer_id = pointer["pointer_id"]
            convo_log = pointer.get("conversation_log", [])
            convo_log.append({
                "role": "student",
                "content": message,
                "ts": datetime.utcnow().isoformat() + "Z",
            })
        except Exception as e:
            print(f"⚠️ Failed to fetch/append message: {e}")
            return {"error": "❌ Conversation log fetch failed"}

        # ✅ Mentor prompt
        prompt = """
You are a senior NEET-PG mentor with 30 years’ experience.
Guide the student concisely, in Markdown with Unicode symbols, ≤150 words.
Use headings, **bold**, _italic_, arrows (→, ↑, ↓), subscripts/superscripts (₁, ₂, ³, ⁺, ⁻),
and emojis (💡🧠⚕️📘) naturally. Do NOT output code blocks or JSON.
"""

        mentor_reply = "⚠️ Temporary glitch — please retry."
        gpt_status = "failed"
        try:
            mentor_reply = chat_with_gpt(prompt, convo_log)
            if isinstance(mentor_reply, str):
                gpt_status = "success"
        except Exception as e:
            print(f"❌ GPT call failed: {e}")

        convo_log.append({
            "role": "assistant",
            "content": mentor_reply,
            "ts": datetime.utcnow().isoformat() + "Z",
        })

        try:
            supabase.table("student_phase_pointer") \
                .update({"conversation_log": convo_log}) \
                .eq("pointer_id", pointer_id) \
                .execute()
        except Exception as e:
            print(f"⚠️ DB update failed: {e}")

        return {
            "mentor_reply": mentor_reply,
            "gpt_status": gpt_status,
        }

    # ───────────────────────────────
    # 🔵 3️⃣ NEXT — advance to next phase
    # ───────────────────────────────
    elif action == "next":
        rpc_data = call_rpc("next_orchestra", {
            "p_student_id": student_id,
            "p_subject_id": subject_id
        })

        if not rpc_data or "phase_type" not in rpc_data:
            print(f"⚠️ RPC failed or returned empty → {rpc_data}")
            return {"error": "❌ next_orchestra RPC failed"}

        return {
            "student_id": student_id,
            "subject_id": subject_id,
            "react_order_final": rpc_data.get("react_order_final"),
            "phase_type": rpc_data.get("phase_type"),
            "phase_json": rpc_data.get("phase_json"),
            "mentor_reply": rpc_data.get("mentor_reply"),
            "seq_num": rpc_data.get("seq_num"),
            "total_count": rpc_data.get("total_count"),
        }

    # ───────────────────────────────
    # 🔖 4️⃣ BOOKMARK REVIEW FLOW (concepts)
    # ───────────────────────────────
    elif action == "bookmark_review":
        rpc_data = call_rpc("get_first_bookmarked_phase", {
            "p_student_id": student_id,
            "p_subject_id": subject_id,
        })

        if not rpc_data:
            print(f"⚠️ No bookmarks found for student {student_id}, subject {subject_id}")
            return {"bookmarked_concepts": []}

        print(f"✅ First bookmarked concept returned for subject {subject_id}")
        return {"bookmarked_concepts": [rpc_data]}

    elif action == "bookmark_review_next":
        last_time_str = payload.get("bookmark_updated_time")
        if not last_time_str:
            return {"error": "❌ Missing bookmark_updated_time"}

        try:
            last_time = datetime.fromisoformat(last_time_str.replace("Z", "+00:00"))
        except Exception as e:
            print(f"⚠️ Failed to parse bookmark time {last_time_str}: {e}")
            last_time = None

        rpc_data = call_rpc("get_next_bookmarked_phase", {
            "p_student_id": student_id,
            "p_subject_id": subject_id,
            "p_last_bookmark_time": last_time.isoformat() if last_time else None,
        })

        if not rpc_data:
            print(f"⚠️ No further bookmarks for student {student_id}, subject {subject_id}")
            return {"bookmarked_concepts": []}

        print(f"✅ RPC returned next bookmark → {rpc_data.get('pointer_id')}")
        return {"bookmarked_concepts": [rpc_data]}

    # ───────────────────────────────
    # 🟣 5️⃣ BOOKMARK REVIEW CHAT — GPT chat during bookmarked concept review
    # ───────────────────────────────
    elif action == "bookmark_review_chat":
        phase_type = payload.get("phase_type", "concept")
        bookmark_updated_time = payload.get("bookmark_updated_time")
        phase_json = payload.get("phase_json")  # ✅ capture from frontend

        print(f"💬 bookmark_review_chat → phase_type={phase_type}, time={bookmark_updated_time}")

        # 1️⃣ Get last conversation for this student/subject
        convo_log = []
        try:
            res = (
                supabase.table("concept_review_bookmarks_chat")
                .select("id, conversation_log")
                .eq("student_id", student_id)
                .eq("subject_id", subject_id)
                .eq("phase_type", phase_type)
                .order("updated_at", desc=True)
                .eq("bookmark_updated_time", bookmark_updated_time)
                .limit(1)
                .execute()
            )

            if res.data:
                chat_row = res.data[0]
                chat_id = chat_row["id"]
                convo_log = chat_row.get("conversation_log", [])
            else:
                # New chat row if none exists
                insert_res = (
                    supabase.table("concept_review_bookmarks_chat")
                    .insert({
                        "student_id": student_id,
                        "subject_id": subject_id,
                        "phase_type": phase_type,
                        "phase_json": phase_json,
                        "bookmark_updated_time": bookmark_updated_time, # ✅ added here
                        "conversation_log": [],
                        "created_at": datetime.utcnow().isoformat() + "Z",
                    })
                    .execute()
                )
                chat_id = insert_res.data[0]["id"] if insert_res.data else None
        except Exception as e:
            print(f"⚠️ DB fetch/insert failed: {e}")
            return {"error": "DB fetch failed"}

        # ✅ If no message provided → just return existing conversation
        if not message:
            print("ℹ️ No message → returning existing conversation only")
            return {"existing_conversation": convo_log}

        # 2️⃣ Append student message
        convo_log.append({
            "role": "student",
            "content": message,
            "ts": datetime.utcnow().isoformat() + "Z",
        })

        # 3️⃣ Generate mentor reply via GPT
        prompt = """
You are a senior NEET-PG mentor with 30 years’ experience.
Guide the student concisely, in Markdown with Unicode symbols, ≤150 words.
Use headings, **bold**, _italic_, arrows (→, ↑, ↓), subscripts/superscripts (₁, ₂, ³, ⁺, ⁻),
and emojis (💡🧠⚕️📘) naturally. Do NOT output code blocks or JSON.
"""

        mentor_reply = "⚠️ Temporary glitch — please retry."
        gpt_status = "failed"
        try:
            mentor_reply = chat_with_gpt(prompt, convo_log)
            if isinstance(mentor_reply, str):
                gpt_status = "success"
        except Exception as e:
            print(f"❌ GPT call failed: {e}")

        convo_log.append({
            "role": "assistant",
            "content": mentor_reply,
            "ts": datetime.utcnow().isoformat() + "Z",
        })

        # 4️⃣ Update the conversation_log back into table
        try:
            supabase.table("concept_review_bookmarks_chat") \
                .update({
                    "conversation_log": convo_log,
                    "updated_at": datetime.utcnow().isoformat() + "Z",
                }) \
                .eq("student_id", student_id) \
                .eq("subject_id", subject_id) \
                .eq("phase_type", phase_type) \
                .eq("bookmark_updated_time", bookmark_updated_time)\
                .execute()
        except Exception as e:
            print(f"⚠️ DB update failed: {e}")

        # 5️⃣ Return GPT reply to frontend
        return {
            "mentor_reply": mentor_reply,
            "gpt_status": gpt_status,
        }

    # ───────────────────────────────
    # ❌ Unknown action
    # ───────────────────────────────
    else:
        return {"error": f"Unknown action '{action}'"}


# ───────────────────────────────────────────────
# 🟠 SUBMIT ANSWER — MCQ logging
# ───────────────────────────────────────────────
@app.post("/submit_answer")
async def submit_answer(request: Request):
    try:
        data = await request.json()
        student_id = data.get("student_id")
        subject_id = data.get("subject_id")
        react_order_final = data.get("react_order_final")
        student_answer = data.get("student_answer")
        correct_answer = data.get("correct_answer")
        is_correct = data.get("is_correct")
        is_completed = data.get("is_completed", True)

        if not student_id or not react_order_final:
            return {"error": "❌ Missing student_id or react_order_final"}

        payload = {
            "student_id": student_id,
            "subject_id": subject_id,
            "react_order_final": int(react_order_final),
            "student_answer": student_answer,
            "correct_answer": correct_answer,
            "is_correct": is_correct,
            "is_completed": is_completed,
            "submitted_at": datetime.utcnow().isoformat() + "Z",
        }

        supabase.table("student_mcq_submissions") \
            .upsert(payload, on_conflict=["student_id", "react_order_final"]) \
            .execute()

        print(f"✅ MCQ submission saved → student {student_id}, subject {subject_id}, react_order_final {react_order_final}")
        return {"status": "success", "data": payload}

    except Exception as e:
        print(f"❌ Error in /submit_answer: {e}")
        return {"error": "⚠️ Failed to submit answer", "details": str(e)}


# ───────────────────────────────────────────────
# HOME
# ───────────────────────────────────────────────
@app.get("/")
def home():
    return {"message": "🧠 Paragraph Orchestra API (bookmark review + chat intent) is live!"}



