from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
from supabase_client import supabase, call_rpc
from gpt_utils import chat_with_gpt  # ✅ same helper used in /app/orchestrate
import json

# ───────────────────────────────
# APP SETUP
# ───────────────────────────────
app = FastAPI(title="Mock Test Orchestra API", version="1.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ───────────────────────────────
# MAIN ORCHESTRATOR ENDPOINT
# ───────────────────────────────
@app.post("/mocktest_orchestrate")
async def mocktest_orchestrate(request: Request):
    payload = await request.json()
    action = payload.get("intent")
    student_id = payload.get("student_id")
    exam_serial = payload.get("exam_serial")
    react_order_final = payload.get("react_order_final")
    student_answer = payload.get("student_answer")
    is_correct = payload.get("is_correct")
    mcq_id = payload.get("mcq_id")
    phase_json = payload.get("phase_json")
    message = payload.get("message")
    react_order = payload.get("react_order")
    time_left_str = payload.get("time_left", "03:30:00")

    # Safely parse time string
    try:
        h, m, s = map(int, time_left_str.split(":"))
        time_left = timedelta(hours=h, minutes=m, seconds=s)
    except Exception:
        time_left = timedelta(hours=3, minutes=30, seconds=0)

    print(f"🎬 Action={action} | Student={student_id} | Exam={exam_serial}")

    # ───────────────────────────────
    # 1️⃣ NORMAL MOCK TEST MODE
    # ───────────────────────────────
    if action == "start_mocktest":
        return call_rpc("start_orchestra_mocktest", {
            "p_student_id": student_id,
            "p_exam_serial": exam_serial
        })

    elif action == "next_mocktest_phase":
        return call_rpc("next_orchestra_mocktest", {
            "p_student_id": student_id,
            "p_exam_serial": exam_serial,
            "p_react_order_final": react_order_final,
            "p_student_answer": student_answer,
            "p_is_correct": is_correct,
            "p_time_left": str(time_left)
        })

    elif action == "skip_mocktest_phase":
        return call_rpc("skip_orchestra_mocktest", {
            "p_student_id": student_id,
            "p_exam_serial": exam_serial,
            "p_react_order_final": react_order_final,
            "p_time_left": str(time_left)
        })


    # ───────────────────────────────
    # 2️⃣ REVIEW MODE (POST-COMPLETION)
    # ───────────────────────────────
    elif action == "start_review_mocktest":
        return call_rpc("start_review_mocktest", {
            "p_student_id": student_id,
            "p_exam_serial": exam_serial
        })

    elif action == "next_review_mocktest":
        return call_rpc("next_review_mocktest", {
            "p_student_id": student_id,
            "p_exam_serial": exam_serial,
            "p_react_order": react_order_final
        })

    elif action == "get_review_mocktest_content":
        return call_rpc("get_review_mocktest_content", {
            "p_student_id": student_id,
            "p_exam_serial": exam_serial,
            "p_react_order": react_order_final
        })


    # ───────────────────────────────
    # 3️⃣ CHAT DURING REVIEW (AI MENTOR Q&A)
    # ───────────────────────────────
    elif action == "chat_review_mocktest":
        print("💬 Review Chat Triggered")

        if not student_id or not exam_serial or not mcq_id or not message:
            return {"error": "❌ Missing required fields"}

        try:
            # 🔍 Check if existing conversation for same student × test × mcq
            res = (
                supabase.table("mock_test_review_conversation")
                .select("id, conversation_log, phase_json")
                .eq("student_id", student_id)
                .eq("exam_serial", exam_serial)
                .eq("mcq_id", mcq_id)
                .maybe_single()
                .execute()
            )

            existing = res.data
            convo_log = existing.get("conversation_log", []) if existing else []

            # 🧩 Append student message
            convo_log.append({
                "role": "student",
                "content": message,
                "ts": datetime.utcnow().isoformat() + "Z",
            })

            # ─────────────────────────────────────
            # 🧠 Extract only the stem from phase_json
            # ─────────────────────────────────────
            stem_text = None
            if isinstance(phase_json, dict):
                stem_text = phase_json.get("stem")
            elif isinstance(phase_json, str):
                try:
                    parsed = json.loads(phase_json)
                    stem_text = parsed.get("stem")
                except Exception:
                    stem_text = phase_json

            phase_stub = {"stem": stem_text}

            # ─────────────────────────────────────
            # 🧠 Build GPT prompt
            # ─────────────────────────────────────
            if existing is None:
                prompt = f"""
You are a senior NEET-PG mentor with 30 years' experience.
Explain the concept behind the answer in ≤120 words, using Unicode markup and emojis naturally.

MCQ Stem: {stem_text}
Student's question: {message}
"""
            else:
                prompt = """
You are continuing a NEET-PG review discussion.
Reply concisely (≤120 words) with a friendly mentor tone and Unicode formatting.
"""

            mentor_reply = "⚠️ Please retry later."
            try:
                mentor_reply = chat_with_gpt(prompt, convo_log)
            except Exception as e:
                print(f"❌ GPT call failed: {e}")

            # 🗨️ Append mentor reply
            convo_log.append({
                "role": "mentor",
                "content": mentor_reply,
                "ts": datetime.utcnow().isoformat() + "Z",
            })

            # ─────────────────────────────────────
            # 💾 Save to Supabase (insert/update)
            # ─────────────────────────────────────
            if existing is None:
                supabase.table("mock_test_review_conversation").insert({
                    "student_id": student_id,
                    "exam_serial": exam_serial,
                    "mcq_id": mcq_id,
                    "phase_json": json.dumps(phase_stub),      # ✅ only stem
                    "react_order": react_order,
                    "conversation_log": json.dumps(convo_log), # ✅ serialize JSON
                    "created_at": datetime.utcnow().isoformat() + "Z",
                }).execute()
            else:
                supabase.table("mock_test_review_conversation").update({
                    "conversation_log": json.dumps(convo_log),
                    "updated_at": datetime.utcnow().isoformat() + "Z"
                }).eq("id", existing["id"]).execute()

            print(f"🧾 Stored review chat for MCQ {mcq_id}: {stem_text}")

            # ✅ Return mentor reply & conversation history
            return {
                "mentor_reply": mentor_reply,
                "conversation_log": convo_log
            }

        except Exception as e:
            print(f"❌ Review chat error: {e}")
            return {"error": str(e)}


    # ───────────────────────────────
    # FALLBACK
    # ───────────────────────────────
    else:
        return {"error": f"❌ Unknown intent '{action}'"}


# ───────────────────────────────
# HEALTH CHECK ROUTE
# ───────────────────────────────
@app.get("/")
def home():
    return {
        "message": "🧠 Mock Test Orchestra API is live with Review Mode + AI Mentor Chat (Stem-Only Optimized)!",
        "version": "1.4.0",
    }
