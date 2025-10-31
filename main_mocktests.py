from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
from supabase_client import supabase, call_rpc
from gpt_utils import chat_with_gpt
import json
import traceback

# ───────────────────────────────
# APP SETUP
# ───────────────────────────────
app = FastAPI(title="Mock Test Orchestra API", version="1.5.0")

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
        print("🟢 start_review_mocktest triggered")
        return call_rpc("start_review_mocktest", {
            "p_student_id": student_id,
            "p_exam_serial": exam_serial
        })

    elif action == "next_review_mocktest":
        print("🟠 next_review_mocktest triggered")
        return call_rpc("next_review_mocktest", {
            "p_student_id": student_id,
            "p_exam_serial": exam_serial,
            "p_react_order": react_order_final
        })

    elif action == "get_review_mocktest_content":
        print("🔵 get_review_mocktest_content triggered")
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
        print(f"📦 Payload keys: {list(payload.keys())}")
        print(f"📋 mcq_id={mcq_id} | phase_json={phase_json} | message={message}")

        if not student_id or not exam_serial or not mcq_id or not message:
            return {"error": "❌ Missing required fields"}

        try:
            # 🔍 Step 1: Check if existing chat exists
            res = (
                supabase.table("mock_test_review_conversation")
                .select("id, conversation_log, phase_json")
                .eq("student_id", student_id)
                .eq("exam_serial", exam_serial)
                .eq("mcq_id", mcq_id)
                .maybe_single()
                .execute()
            )

            print("🔍 Existing row query result:", res)

            existing = res.data
            convo_log = existing.get("conversation_log", []) if existing else []

            # 🧩 Step 2: Append student message
            convo_log.append({
                "role": "student",
                "content": message,
                "ts": datetime.utcnow().isoformat() + "Z",
            })

            # 🧠 Step 3: Extract stem only
            stem_text = None
            try:
                if isinstance(phase_json, dict):
                    stem_text = phase_json.get("stem")
                elif isinstance(phase_json, str):
                    parsed = json.loads(phase_json)
                    stem_text = parsed.get("stem", phase_json)
                else:
                    stem_text = str(phase_json)
            except Exception as e:
                print("⚠️ Stem parse error:", e)
                stem_text = str(phase_json)
            phase_stub = {"stem": stem_text}

            # 🧠 Step 4: Build GPT prompt
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

            # 🧠 Step 5: Call GPT safely
            mentor_reply = "⚠️ Please retry later."
            try:
                print("🤖 Calling GPT ...")
                mentor_reply = chat_with_gpt(prompt, convo_log)
                print("✅ GPT reply:", mentor_reply[:100])
            except Exception as e:
                print("❌ GPT call failed:", e)
                print(traceback.format_exc())

            # Append mentor message
            convo_log.append({
                "role": "mentor",
                "content": mentor_reply,
                "ts": datetime.utcnow().isoformat() + "Z",
            })

            # 🧾 Step 6: Insert or Update Supabase
            print("🪶 Preparing to insert/update in Supabase...")
            if existing is None:
                try:
                    insert_data = {
                        "student_id": student_id,
                        "exam_serial": exam_serial,
                        "mcq_id": mcq_id,
                        "phase_json": json.dumps(phase_stub),
                        "react_order": react_order,
                        "conversation_log": json.dumps(convo_log),
                        "created_at": datetime.utcnow().isoformat() + "Z",
                    }
                    print("📦 Insert data:", insert_data)
                    res = supabase.table("mock_test_review_conversation").insert(insert_data).execute()
                    print("✅ Insert result:", res)
                except Exception as e:
                    print("❌ Supabase insert error:", e)
                    print(traceback.format_exc())
            else:
                try:
                    update_data = {
                        "conversation_log": json.dumps(convo_log),
                        "updated_at": datetime.utcnow().isoformat() + "Z",
                    }
                    print("📦 Update data:", update_data)
                    res = (
                        supabase.table("mock_test_review_conversation")
                        .update(update_data)
                        .eq("id", existing["id"])
                        .execute()
                    )
                    print("✅ Update result:", res)
                except Exception as e:
                    print("❌ Supabase update error:", e)
                    print(traceback.format_exc())

            print(f"🧾 Stored review chat for MCQ={mcq_id}, stem='{stem_text}'")

            return {
                "mentor_reply": mentor_reply,
                "conversation_log": convo_log
            }

        except Exception as e:
            print("❌ Review chat block crashed:", e)
            print(traceback.format_exc())
            return {"error": str(e)}

    # ───────────────────────────────
    # FALLBACK
    # ───────────────────────────────
    else:
        return {"error": f"❌ Unknown intent '{action}'"}


# ───────────────────────────────
# HEALTH CHECK
# ───────────────────────────────
@app.get("/")
def home():
    return {
        "message": "🧠 Mock Test Orchestra API v1.5.0 (debug mode, review chat tracing active)",
        "status": "ok"
    }
