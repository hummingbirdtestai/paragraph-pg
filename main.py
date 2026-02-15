# MAIN.PY
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from supabase_client import call_rpc, supabase
from gpt_utils import chat_with_gpt
from newchat import router as newchat_router
from payments import router as payments_router
import json
from notify import router as notify_router
from stream_token import router as stream_router

# MAIN.PY
import logging
from fastapi import FastAPI

# ───────────────────────────────────────────────
# 🔥 GLOBAL LOGGING CONFIG — MUST BE HERE
# ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logging.getLogger("ask_paragraph").setLevel(logging.DEBUG)
logging.getLogger("ask_paragraph.state").setLevel(logging.DEBUG)
logging.getLogger("ask_paragraph.suggestions").setLevel(logging.DEBUG)

# ───────────────────────────────────────────────
# Initialize FastAPI app
# ───────────────────────────────────────────────
app = FastAPI(title="Paragraph Orchestra API", version="3.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.neetpg.app",
        "https://neetpg.app",
        "http://localhost:3000",

        # 🔥 THIS IS MANDATORY FOR YOUR CURRENT ERROR
        "https://zp1v56uxy8rdx5ypatb0ockcb9tr6a-oci3--8081--365214aa.local-credentialless.webcontainer-api.io",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# THEN routers
app.include_router(notify_router)
app.include_router(newchat_router, prefix="/ask-paragraph")
app.include_router(payments_router)
app.include_router(stream_router)

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

    # 1️⃣ START NORMAL FLOW
    if action == "start":
        rpc_data = call_rpc("start_orchestra", {
            "p_student_id": student_id,
            "p_subject_id": subject_id
        })

        if not rpc_data or "phase_type" not in rpc_data:
            return {"error": "❌ start_orchestra RPC failed"}

        return rpc_data

    # 2️⃣ ACTIVE LEARNING CHAT
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

            convo.append({
                "role": "student",
                "content": message,
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

        except Exception as e:
            return {"error": str(e)}

    # 3️⃣ NEXT PHASE
    elif action == "next":
        rpc_data = call_rpc("next_orchestra", {
            "p_student_id": student_id,
            "p_subject_id": subject_id
        })
        return rpc_data

    # 4️⃣ BOOKMARK REVIEW
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

    # 5️⃣ REVIEW COMPLETED — START
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

        return {"review_upto": [rows[0]]}

    # 6️⃣ REVIEW COMPLETED — NEXT
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

    # 7️⃣ WRONG MCQs START
    elif action == "wrong_mcqs_start":
        rows = (
            supabase.table("student_phase_pointer")
            .select("*")
            .eq("student_id", student_id)
            .eq("subject_id", subject_id)
            .eq("phase_type", "mcq")
            .eq("is_correct", False)
            .order("react_order_final", desc=False)
            .execute()
        ).data

        if not rows:
            return {"wrong_mcqs": []}

        total = len(rows)
        for i, r in enumerate(rows):
            r["seq_num"] = i + 1
            r["total_count"] = total

        return {"wrong_mcqs": [rows[0]]}

    # 8️⃣ WRONG MCQs NEXT
    elif action == "wrong_mcqs_next":
        current_order = payload.get("react_order_final")

        rows = (
            supabase.table("student_phase_pointer")
            .select("*")
            .eq("student_id", student_id)
            .eq("subject_id", subject_id)
            .eq("phase_type", "mcq")
            .eq("is_correct", False)
            .order("react_order_final", desc=False)
            .execute()
        ).data

        if not rows:
            return {"wrong_mcqs": []}

        total = len(rows)
        for i, r in enumerate(rows):
            r["seq_num"] = i + 1
            r["total_count"] = total

        next_row = next(
            (r for r in rows if r["react_order_final"] > current_order),
            None
        )

        return {"wrong_mcqs": [next_row] if next_row else []}

    # 9️⃣ REVIEW CHAT
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

    # ❿ UNKNOWN ACTION
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
            "submitted_at": datetime.utcnow().isoformat() + "Z",
            "is_completed": True,
        }

        supabase.table("student_mcq_submissions") \
            .upsert(payload, on_conflict=["student_id", "react_order_final"]) \
            .execute()

        return {"status": "success", "data": payload}

    except Exception as e:
        return {"error": str(e)}



# ───────────────────────────────────────────────
# NEW ENDPOINT: Resolve MCQ → Find Previous Concept → Call RPC
# ───────────────────────────────────────────────
@app.post("/intent/resolve_mcq")
async def resolve_mcq(request: Request):
    data = await request.json()

    p_student_id = data.get("p_student_id")
    p_mcq_id = data.get("p_mcq_id")
    p_student_answer = data.get("p_student_answer")
    p_correct_answer = data.get("p_correct_answer")

    if not p_student_id or not p_mcq_id:
        return {"error": "p_student_id and p_mcq_id are required"}

    # 1️⃣ Fetch the MCQ row
    mcq_row = (
        supabase.table("concept_phase_final")
        .select("id, phase_type, subject_id, react_order_final")
        .eq("id", p_mcq_id)
        .eq("phase_type", "mcq")
        .execute()
    )

    if not mcq_row.data:
        return {"error": "MCQ row not found"}

    mcq = mcq_row.data[0]
    mcq_order = mcq["react_order_final"]
    subject_id = mcq["subject_id"]

    # 2️⃣ Fetch the concept just before this MCQ
    concept_row = (
        supabase.table("concept_phase_final")
        .select("id, react_order_final, phase_json")
        .eq("subject_id", subject_id)
        .eq("phase_type", "concept")
        .eq("react_order_final", mcq_order - 1)
        .limit(1)
        .execute()
    )

    if not concept_row.data:
        return {"error": "Previous concept not found"}

    concept = concept_row.data[0]
    concept_id = concept["id"]

    # 3️⃣ Call the existing RPC
    rpc_result = call_rpc("mark_mcq_submission_v6", {
        "p_student_id": p_student_id,
        "p_concept_id": concept_id,
        "p_mcq_id": p_mcq_id,
        "p_student_answer": p_student_answer,
        "p_correct_answer": p_correct_answer,
    })

    # 4️⃣ Return combined response
    return {
        "concept_before": {
            "concept_id": concept_id,
            "react_order_final": concept["react_order_final"],
            "phase_json": concept["phase_json"],
        },
        "rpc_result": rpc_result
    }


# ───────────────────────────────────────────────
# HEALTH CHECK
# ───────────────────────────────────────────────
@app.get("/")
def home():
    return {"message": "🧠 Review flow now includes seq_num & total_count + Resolve MCQ Intent Added ✅"}


