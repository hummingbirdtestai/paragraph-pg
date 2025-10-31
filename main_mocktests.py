from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import timedelta, datetime
from supabase_client import call_rpc, supabase
from gpt_utils import chat_with_gpt
import traceback
import json

# ───────────────────────────────
# APP SETUP
# ───────────────────────────────
app = FastAPI(title="Mock Test Orchestra API", version="1.3.0")

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
    react_order_final = payload.get("react_order_final") or payload.get("react_order")
    student_answer = payload.get("student_answer")
    is_correct = payload.get("is_correct")
    mcq_id = payload.get("mcq_id")
    phase_json = payload.get("phase_json")
    message = payload.get("message")
    time_left_str = payload.get("time_left", "03:30:00")

    print("\n─────────────────────────────")
    print(f"🎬 Action: {action}")
    print(f"👤 Student: {student_id}")
    print(f"🧪 Exam Serial: {exam_serial}")
    print(f"🧩 React Order: {react_order_final}")
    print(f"🕒 Time Left: {time_left_str}")
    print("─────────────────────────────")

    # Safely parse time string → timedelta
    try:
        h, m, s = map(int, time_left_str.split(":"))
        time_left = timedelta(hours=h, minutes=m, seconds=s)
    except Exception as e:
        print(f"⚠️ Failed to parse time_left_str '{time_left_str}': {e}")
        time_left = timedelta(hours=3, minutes=30, seconds=0)

    try:
        result = None

        # ───────────────────────────────
        # 1️⃣ NORMAL MOCK TEST MODE
        # ───────────────────────────────
        if action == "start_mocktest":
            print("🟢 Calling RPC → start_orchestra_mocktest")
            result = call_rpc("start_orchestra_mocktest", {
                "p_student_id": student_id,
                "p_exam_serial": exam_serial
            })

        elif action == "next_mocktest_phase":
            print("🟢 Calling RPC → next_orchestra_mocktest")
            result = call_rpc("next_orchestra_mocktest", {
                "p_student_id": student_id,
                "p_exam_serial": exam_serial,
                "p_react_order_final": react_order_final,
                "p_student_answer": student_answer,
                "p_is_correct": is_correct,
                "p_time_left": str(time_left)
            })

        elif action == "skip_mocktest_phase":
            print("🟢 Calling RPC → skip_orchestra_mocktest")
            result = call_rpc("skip_orchestra_mocktest", {
                "p_student_id": student_id,
                "p_exam_serial": exam_serial,
                "p_react_order_final": react_order_final,
                "p_time_left": str(time_left)
            })

        # ───────────────────────────────
        # 2️⃣ REVIEW MODE (POST-COMPLETION)
        # ───────────────────────────────
        elif action == "start_review_mocktest":
            print("🟡 Calling RPC → start_review_mocktest")
            result = call_rpc("start_review_mocktest", {
                "p_student_id": student_id,
                "p_exam_serial": exam_serial
            })

        elif action == "next_review_mocktest":
            print("🟡 Calling RPC → next_review_mocktest")
            result = call_rpc("next_review_mocktest", {
                "p_student_id": student_id,
                "p_exam_serial": exam_serial,
                "p_react_order": react_order_final
            })

        elif action == "get_review_mocktest_content":
            print("🟡 Calling RPC → get_review_mocktest_content")
            result = call_rpc("get_review_mocktest_content", {
                "p_student_id": student_id,
                "p_exam_serial": exam_serial,
                "p_react_order": react_order_final
            })

        # ───────────────────────────────
        # 3️⃣ CHAT DURING REVIEW
        # ───────────────────────────────
        elif action == "chat_review_mocktest":
            print("💬 Review Chat Triggered")
            print(f"📦 Payload keys: {list(payload.keys())}")
            print(f"📋 mcq_id={mcq_id} | message={message}")

            if not student_id or not exam_serial or not mcq_id or not message:
                return {"error": "❌ Missing required fields"}

            # Step 1: Get existing conversation (if any)
            res = (
                supabase.table("mock_test_review_conversation")
                .select("id, conversation_log")
                .eq("student_id", student_id)
                .eq("exam_serial", exam_serial)
                .eq("mcq_id", mcq_id)
                .maybe_single()
                .execute()
            )
            existing = res.data if hasattr(res, "data") else None
            convo_log = existing.get("conversation_log", []) if existing else []

            # Step 2: Append student message
            convo_log.append({
                "role": "student",
                "content": message,
                "ts": datetime.utcnow().isoformat() + "Z",
            })

            # Step 3: Prepare mentor prompt
            stem_text = None
            try:
                if isinstance(phase_json, dict):
                    stem_text = phase_json.get("stem")
                elif isinstance(phase_json, str):
                    stem_text = json.loads(phase_json).get("stem", phase_json)
                else:
                    stem_text = str(phase_json)
            except Exception:
                stem_text = str(phase_json)

            prompt = f"""
You are a senior NEET-PG mentor with 30 years’ experience.
Guide the student concisely, in Markdown with Unicode symbols, ≤150 words.
Use headings, *bold*, italic, arrows (→, ↑, ↓), subscripts/superscripts (₁, ₂, ³, ⁺, ⁻),
and emojis (💡🧠⚕📘) naturally. Do NOT output code blocks or JSON.

MCQ Stem: {stem_text}
Student’s question: {message}
"""

            # Step 4: Get mentor reply
            mentor_reply = "⚠️ Please retry later."
            try:
                print("🤖 Calling GPT mentor...")
                mentor_reply = chat_with_gpt(prompt, convo_log)
                print("✅ GPT reply preview:", mentor_reply[:120])
            except Exception as e:
                print("❌ GPT call failed:", e)
                print(traceback.format_exc())

            convo_log.append({
                "role": "mentor",
                "content": mentor_reply,
                "ts": datetime.utcnow().isoformat() + "Z",
            })

            # Step 5: Insert or update Supabase
            try:
                if not existing:
                    insert_data = {
                        "student_id": student_id,
                        "exam_serial": exam_serial,
                        "mcq_id": mcq_id,
                        "phase_json": json.dumps({"stem": stem_text}),
                        "conversation_log": json.dumps(convo_log),
                        "created_at": datetime.utcnow().isoformat() + "Z",
                    }
                    supabase.table("mock_test_review_conversation").insert(insert_data).execute()
                    print("🟢 Inserted new review conversation row.")
                else:
                    supabase.table("mock_test_review_conversation").update({
                        "conversation_log": json.dumps(convo_log),
                        "updated_at": datetime.utcnow().isoformat() + "Z",
                    }).eq("id", existing["id"]).execute()
                    print("🟡 Updated existing review conversation row.")
            except Exception as e:
                print("❌ Supabase insert/update failed:", e)
                print(traceback.format_exc())

            return {
                "mentor_reply": mentor_reply,
                "conversation_log": convo_log
            }

        else:
            print(f"❌ Unknown intent: {action}")
            return {"error": f"❌ Unknown intent '{action}'"}

        # ───────────────────────────────
        # RESULT VALIDATION + DEBUG LOGS
        # ───────────────────────────────
        print("📦 Raw RPC Result:", result)

        if not result:
            print("⚠️ RPC returned no data or None.")
            return {"error": "RPC returned no data."}

        if isinstance(result, str):
            try:
                print("🔍 Attempting to parse string result as JSON...")
                result = json.loads(result)
            except Exception:
                print("⚠️ Could not parse string result. Returning raw string.")
                return {"message": result}

        if isinstance(result, dict):
            if "message" in result and "✅ Review complete" in result["message"]:
                print("🎉 Review cycle complete — returning success message.")
                return {"message": "✅ Review complete"}

        return result

    except Exception as e:
        print("💥 Exception during RPC call!")
        print(traceback.format_exc())
        return {"error": f"Internal server error: {e}"}


# ───────────────────────────────
# HEALTH CHECK
# ───────────────────────────────
@app.get("/")
def home():
    return {"message": "🧠 Mock Test Orchestra API v1.3.0 — with chat_review_mocktest enabled!"}
