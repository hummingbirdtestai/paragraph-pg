# /app/main_mocktest.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import timedelta
from supabase_client import call_rpc

# ───────────────────────────────
# APP SETUP
# ───────────────────────────────
app = FastAPI(title="Mock Test Orchestra API", version="1.1.0")

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
    time_left_str = payload.get("time_left", "03:30:00")

    # Safely parse time string → timedelta
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
        # loads first question (react_order = 1)
        return call_rpc("start_review_mocktest", {
            "p_student_id": student_id,
            "p_exam_serial": exam_serial
        })

    elif action == "next_review_mocktest":
        # loads next question react_order > current
        return call_rpc("next_review_mocktest", {
            "p_student_id": student_id,
            "p_exam_serial": exam_serial,
            "p_react_order": react_order_final
        })

    elif action == "get_review_mocktest_content":
        # fetch specific question by react_order
        return call_rpc("get_review_mocktest_content", {
            "p_student_id": student_id,
            "p_exam_serial": exam_serial,
            "p_react_order": react_order_final
        })

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
    return {"message": "🧠 Mock Test Orchestra API is live with Review Mode!"}
