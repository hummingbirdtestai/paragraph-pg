from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import timedelta
from supabase_client import call_rpc
import traceback
import json

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
    react_order_final = payload.get("react_order_final") or payload.get("react_order")
    student_answer = payload.get("student_answer")
    is_correct = payload.get("is_correct")
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

        else:
            print(f"❌ Unknown intent: {action}")
            return {"error": f"❌ Unknown intent '{action}'"}

        # ───────────────────────────────
        # RESULT VALIDATION + DEBUG LOGS
        # ───────────────────────────────
        print("📦 Raw RPC Result:", result)

        # Handle None or malformed result
        if not result:
            print("⚠️ RPC returned no data or None.")
            return {"error": "RPC returned no data."}

        # Normalize stringified JSON (common in Supabase exceptions)
        if isinstance(result, str):
            try:
                print("🔍 Attempting to parse string result as JSON...")
                result = json.loads(result)
            except Exception:
                print("⚠️ Could not parse string result. Returning raw string.")
                return {"message": result}

        # Handle “✅ Review complete.” safely
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
# HEALTH CHECK ROUTE
# ───────────────────────────────
@app.get("/")
def home():
    return {"message": "🧠 Mock Test Orchestra API is live with detailed logging!"}
