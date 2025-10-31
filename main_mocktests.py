# /app/main_mocktest.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
from supabase_client import supabase, call_rpc
from gpt_client import chat_with_gpt  # assumes same helper used earlier

# ───────────────────────────────
# APP SETUP
# ───────────────────────────────
app = FastAPI(title="Mock Test Orchestra API", version="1.2.0")

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
    # 3️⃣ CHAT DURING REVIEW (NEW)
    # ───────────────────────────────
    elif action == "chat_review_mocktest":
        print("💬 Review Chat Triggered")

        if not student_id or not exam_serial or not mcq_id or not message:
            return {"error": "Missing required fields"}

        try:
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

            # append student message
            convo_log.append({
                "role": "student",
                "content": message,
                "ts": datetime.utcnow().isoformat() + "Z",
            })

            # build prompt
            if existing is None:
                # first time review chat → use MCQ stem + question
                stem = phase_json.get("stem") if phase_json else "Unknown question stem"
                prompt = f"""
You are a senior NEET-PG mentor with 30 years' experience.
Explain in ≤120 words, with Unicode markup and emojis naturally.

MCQ Stem: {stem}
Student's question: {message}
"""
            else:
                # existing chat → continue context
                prompt = """
You are continuing a NEET-PG review discussion.
Keep replies concise, <=120 words, friendly mentor tone.
"""
            
            mentor_reply = "⚠️ Please retry later."
            try:
                mentor_reply = chat_with_gpt(prompt, convo_log)
            except Exception as e:
                print(f"GPT call failed: {e}")

            convo_log.append({
                "role": "mentor",
                "content": mentor_reply,
                "ts": datetime.utcnow().isoformat() + "Z",
            })

            # insert or update DB
            if existing is None:
                supabase.table("mock_test_review_conversation").insert({
                    "student_id": student_id,
                    "exam_serial": exam_serial,
                    "mcq_id": mcq_id,
                    "phase_json": phase_json,
                    "react_order": react_order,
                    "conversation_log": convo_log
                }).execute()
            else:
                supabase.table("mock_test_review_conversation").update({
                    "conversation_log": convo_log,
                    "updated_at": datetime.utcnow().isoformat() + "Z"
                }).eq("id", existing["id"]).execute()

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


@app.get("/")
def home():
    return {"message": "🧠 Mock Test Orchestra API is live with Review Mode + Review Chat!"}
