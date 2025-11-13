from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from supabase_client import call_rpc, supabase
from gpt_utils import chat_with_gpt
import json

# ───────────────────────────────────────────────
# Initialize FastAPI app
# ───────────────────────────────────────────────
app = FastAPI(title="Paragraph Orchestra API", version="2.5.0")

# Allow frontend calls
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────────────────────────────────────────────
# MASTER ORCHESTRATOR ENDPOINT
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
    # 1️⃣ START NORMAL CHAPTER FLOW
    # ───────────────────────────────
    if action == "start":
        rpc_data = call_rpc("start_orchestra", {
            "p_student_id": student_id,
            "p_subject_id": subject_id
        })
        if not rpc_data or "phase_type" not in rpc_data:
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
    # 2️⃣ GPT CHAT FLOW
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
            print(f"⚠️ Failed to fetch/append chat log: {e}")
            return {"error": "❌ Conversation log fetch failed"}

        # GPT
        prompt = """
You are a senior NEET-PG mentor with 30 years’ experience.
Guide the student concisely, in Markdown with Unicode symbols.
"""

        mentor_reply = "⚠️ Temporary glitch — please retry."
        gpt_status = "failed"
        try:
            mentor_reply = chat_with_gpt(prompt, convo_log)
            gpt_status = "success"
        except:
            pass

        convo_log.append({
            "role": "assistant",
            "content": mentor_reply,
            "ts": datetime.utcnow().isoformat() + "Z",
        })

        supabase.table("student_phase_pointer") \
            .update({"conversation_log": convo_log}) \
            .eq("pointer_id", pointer_id) \
            .execute()

        return {"mentor_reply": mentor_reply, "gpt_status": gpt_status}

    # ───────────────────────────────
    # 3️⃣ NEXT PHASE (normal learning)
    # ───────────────────────────────
    elif action == "next":
        rpc_data = call_rpc("next_orchestra", {
            "p_student_id": student_id,
            "p_subject_id": subject_id
        })

        if not rpc_data or "phase_type" not in rpc_data:
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
    # 4️⃣ BOOKMARK REVIEW
    # ───────────────────────────────
    elif action == "bookmark_review":
        rpc_data = call_rpc("get_first_bookmarked_phase", {
            "p_student_id": student_id,
            "p_subject_id": subject_id,
        })
        return {"bookmarked_concepts": [rpc_data] if rpc_data else []}

    elif action == "bookmark_review_next":
        last_time = payload.get("bookmark_updated_time")
        rpc_data = call_rpc("get_next_bookmarked_phase", {
            "p_student_id": student_id,
            "p_subject_id": subject_id,
            "p_last_bookmark_time": last_time,
        })
        return {"bookmarked_concepts": [rpc_data] if rpc_data else []}

    # ───────────────────────────────
    # 🆕 5️⃣ REVIEW COMPLETED FLOW — START
    # ───────────────────────────────
    elif action == "review_upto_start":
        print("📘 Fetching FIRST completed phase...")

        query = (
            supabase.table("student_phase_pointer")
            .select("*")
            .eq("student_id", student_id)
            .eq("subject_id", subject_id)
            .eq("is_completed", True)
            .order("react_order_final", desc=False)
            .limit(1)
            .execute()
        )
        return {"review_upto": query.data or []}

    # ───────────────────────────────
    # 🆕 6️⃣ REVIEW COMPLETED FLOW — NEXT
    # ───────────────────────────────
    elif action == "review_upto_next":
        current_order = payload.get("react_order_final")
        print(f"⏭ Reviewing next after {current_order}")

        query = (
            supabase.table("student_phase_pointer")
            .select("*")
            .eq("student_id", student_id)
            .eq("subject_id", subject_id)
            .eq("is_completed", True)
            .gt("react_order_final", current_order)
            .order("react_order_final", desc=False)
            .limit(1)
            .execute()
        )
        return {"review_upto": query.data or []}

    # ───────────────────────────────
    # 7️⃣ WRONG MCQS START
    # ───────────────────────────────
    elif action == "wrong_mcqs_start":
        query = (
            supabase.table("student_phase_pointer")
            .select("*")
            .eq("student_id", student_id)
            .eq("subject_id", subject_id)
            .eq("phase_type", "mcq")
            .eq("is_correct", False)
            .order("react_order_final", desc=False)
            .limit(1)
            .execute()
        )
        return {"wrong_mcqs": query.data or []}

    # ───────────────────────────────
    # 8️⃣ WRONG MCQS NEXT
    # ───────────────────────────────
    elif action == "wrong_mcqs_next":
        current_order = payload.get("react_order_final")

        query = (
            supabase.table("student_phase_pointer")
            .select("*")
            .eq("student_id", student_id)
            .eq("subject_id", subject_id)
            .eq("phase_type", "mcq")
            .eq("is_correct", False)
            .gt("react_order_final", current_order)
            .order("react_order_final", desc=False)
            .limit(1)
            .execute()
        )
        return {"wrong_mcqs": query.data or []}

    # ───────────────────────────────
    # ❌ UNKNOWN ACTION
    # ───────────────────────────────
    else:
        return {"error": f"Unknown action '{action}'"}


# ───────────────────────────────────────────────
# SUBMIT MCQ ANSWER
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

        if not student_id or not react_order_final:
            return {"error": "Missing required fields"}

        payload = {
            "student_id": student_id,
            "subject_id": subject_id,
            "react_order_final": int(react_order_final),
            "student_answer": student_answer,
            "correct_answer": correct_answer,
            "is_correct": is_correct,
            "is_completed": True,
            "submitted_at": datetime.utcnow().isoformat() + "Z",
        }

        supabase.table("student_mcq_submissions") \
            .upsert(payload, on_conflict=["student_id", "react_order_final"]) \
            .execute()

        return {"status": "success", "data": payload}

    except Exception as e:
        return {"error": str(e)}


# ───────────────────────────────────────────────
# HOME
# ───────────────────────────────────────────────
@app.get("/")
def home():
    return {"message": "🧠 Paragraph API with review_upto & wrong MCQs active!"}


