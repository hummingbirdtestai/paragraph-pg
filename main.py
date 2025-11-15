from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from supabase_client import call_rpc, supabase
from gpt_utils import chat_with_gpt
import json

# ───────────────────────────────────────────────
# Initialize FastAPI app
# ───────────────────────────────────────────────
app = FastAPI(title="Paragraph Orchestra API", version="3.1.0")

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

    # ───────────────────────────────────────────
    # 1️⃣ START NORMAL FLOW (active learning)
    # ───────────────────────────────────────────
    if action == "start":
        rpc_data = call_rpc("start_orchestra", {
            "p_student_id": student_id,
            "p_subject_id": subject_id
        })

        if not rpc_data or "phase_type" not in rpc_data:
            return {"error": "❌ start_orchestra RPC failed"}

        return rpc_data

    # ───────────────────────────────────────────
    # 2️⃣ ACTIVE LEARNING CHAT
    # ───────────────────────────────────────────
    elif action == "chat":
        try:
            row = (
                supabase.table("student_phase_pointer")
                .select("pointer_id, conversation_log")
                .eq("student_id", student_id)
                .eq("subject_id", subject_id)
                .order("updated_at", desc=True)
                .limit(1)
                .execute()
            )

            if not row.data:
                return {"error": "⚠️ No active pointer found"}

            pointer = row.data[0]
            pointer_id = pointer["pointer_id"]
            convo = pointer.get("conversation_log", [])

            # Append student message
            convo.append({
                "role": "student",
                "content": message,
                "ts": datetime.utcnow().isoformat() + "Z",
            })

            # GPT reply
            prompt = """
You are a senior NEET-PG mentor with 30 years’ experience.
Guide the student concisely in Markdown.
"""
            mentor_reply = chat_with_gpt(prompt, convo)

            convo.append({
                "role": "assistant",
                "content": mentor_reply,
                "ts": datetime.utcnow().isoformat() + "Z",
            })

            supabase.table("student_phase_pointer") \
                .update({"conversation_log": convo}) \
                .eq("pointer_id", pointer_id) \
                .execute()

            return {"mentor_reply": mentor_reply}

        except Exception as e:
            return {"error": str(e)}

    # ───────────────────────────────────────────
    # 3️⃣ NEXT PHASE
    # ───────────────────────────────────────────
    elif action == "next":
        rpc_data = call_rpc("next_orchestra", {
            "p_student_id": student_id,
            "p_subject_id": subject_id
        })
        return rpc_data

    # ───────────────────────────────────────────
    # 4️⃣ BOOKMARK REVIEW
    # ───────────────────────────────────────────
    elif action == "bookmark_review":
        row = call_rpc("get_first_bookmarked_phase", {
            "p_student_id": student_id,
            "p_subject_id": subject_id
        })
        return {"bookmarked_concepts": [row] if row else []}

    elif action == "bookmark_review_next":
        last_time = payload.get("bookmark_updated_time")
        row = call_rpc("get_next_bookmarked_phase", {
            "p_student_id": student_id,
            "p_subject_id": subject_id,
            "p_last_bookmark_time": last_time
        })
        return {"bookmarked_concepts": [row] if row else []}

    # ───────────────────────────────────────────
    # 5️⃣ REVIEW COMPLETED — START (✅ now with seq + total)
    # ───────────────────────────────────────────
    elif action == "review_upto_start":
        rows = (
            supabase.table("student_phase_pointer")
            .select("*")
            .eq("student_id", student_id)
            .eq("subject_id", subject_id)
            .eq("is_completed", True)
            .order("react_order_final", desc=False)
            .execute()
        ).data

        if not rows:
            return {"review_upto": []}

        total = len(rows)
        for i, row in enumerate(rows):
            row["seq_num"] = i + 1
            row["total_count"] = total

        # first one
        return {"review_upto": [rows[0]]}

    # ───────────────────────────────────────────
    # 6️⃣ REVIEW COMPLETED — NEXT (✅ now with seq + total)
    # ───────────────────────────────────────────
    elif action == "review_upto_next":
        current_order = payload.get("react_order_final")

        rows = (
            supabase.table("student_phase_pointer")
            .select("*")
            .eq("student_id", student_id)
            .eq("subject_id", subject_id)
            .eq("is_completed", True)
            .order("react_order_final", desc=False)
            .execute()
        ).data

        if not rows:
            return {"review_upto": []}

        total = len(rows)
        for i, row in enumerate(rows):
            row["seq_num"] = i + 1
            row["total_count"] = total

        next_row = next(
            (r for r in rows if r["react_order_final"] > current_order),
            None
        )

        return {"review_upto": [next_row] if next_row else []}

    # ───────────────────────────────────────────
    # 7️⃣ WRONG MCQs START
    # ───────────────────────────────────────────
    elif action == "wrong_mcqs_start":
        row = (
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
        return {"wrong_mcqs": row.data or []}

    # ───────────────────────────────────────────
    # 8️⃣ WRONG MCQs NEXT
    # ───────────────────────────────────────────
    elif action == "wrong_mcqs_next":
        current_order = payload.get("react_order_final")
        row = (
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
        return {"wrong_mcqs": row.data or []}

    # ───────────────────────────────────────────
    # 9️⃣ REVIEW CHAT (Unified)
    # ───────────────────────────────────────────
    elif action == "review_chat":
        react_order_final = payload.get("react_order_final")

        row = (
            supabase.table("student_phase_pointer")
            .select("pointer_id, conversation_log")
            .eq("student_id", student_id)
            .eq("subject_id", subject_id)
            .eq("react_order_final", react_order_final)
            .limit(1)
            .execute()
        )

        if not row.data:
            return {"error": "❌ No matching review pointer found"}

        pointer = row.data[0]
        pointer_id = pointer["pointer_id"]
        convo = pointer.get("conversation_log", [])

        # No message? just return previous convo
        if not message or not message.strip():
            return {"existing_conversation": convo}

        convo.append({
            "role": "student",
            "content": message.strip(),
            "ts": datetime.utcnow().isoformat() + "Z",
        })

        prompt = """
You are a senior NEET-PG mentor with 30 years’ experience.
Guide the student concisely in Markdown.
"""
        mentor_reply = chat_with_gpt(prompt, convo)

        convo.append({
            "role": "assistant",
            "content": mentor_reply,
            "ts": datetime.utcnow().isoformat() + "Z",
        })

        supabase.table("student_phase_pointer") \
            .update({"conversation_log": convo}) \
            .eq("pointer_id", pointer_id) \
            .execute()

        return {"mentor_reply": mentor_reply}

    # ───────────────────────────────────────────
    # ❿ UNKNOWN ACTION
    # ───────────────────────────────────────────
    else:
        return {"error": f"Unknown action '{action}'"}


# ───────────────────────────────────────────────
# SUBMIT MCQ ANSWER
# ───────────────────────────────────────────────
@app.post("/submit_answer")
async def submit_answer(request: Request):
    try:
        data = await request.json()

        payload = {
            "student_id": data["student_id"],
            "subject_id": data["subject_id"],
            "react_order_final": int(data["react_order_final"]),
            "student_answer": data["student_answer"],
            "correct_answer": data["correct_answer"],
            "is_correct": data["is_correct"],
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
# HEALTH CHECK
# ───────────────────────────────────────────────
@app.get("/")
def home():
    return {"message": "🧠 Review flow now includes seq_num & total_count ✅"}
