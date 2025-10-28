# /app/main_mocktest.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
from supabase_client import call_rpc

app = FastAPI(title="Mock Test Orchestra API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────────────────────────────
# MAIN ENDPOINT
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

    time_left = timedelta(
        hours=int(time_left_str.split(":")[0]),
        minutes=int(time_left_str.split(":")[1]),
        seconds=int(time_left_str.split(":")[2])
    )

    print(f"🎬 Action={action} Student={student_id} Exam={exam_serial}")

    # 🟢 1️⃣ START TEST
    if action == "start_mocktest":
        rpc_data = call_rpc("start_orchestra_mocktest", {
            "p_student_id": student_id,
            "p_exam_serial": exam_serial
        })
        return rpc_data

    # 🔵 2️⃣ NEXT QUESTION
    elif action == "next_mocktest_phase":
        rpc_data = call_rpc("next_orchestra_mocktest", {
            "p_student_id": student_id,
            "p_exam_serial": exam_serial,
            "p_react_order_final": react_order_final,
            "p_student_answer": student_answer,
            "p_is_correct": is_correct,
            "p_time_left": str(time_left)
        })
        return rpc_data

    # 🟠 3️⃣ SKIP QUESTION
    elif action == "skip_mocktest_phase":
        rpc_data = call_rpc("skip_orchestra_mocktest", {
            "p_student_id": student_id,
            "p_exam_serial": exam_serial,
            "p_react_order_final": react_order_final,
            "p_time_left": str(time_left)
        })
        return rpc_data

    else:
        return {"error": f"Unknown intent '{action}'"}


@app.get("/")
def home():
    return {"message": "🧠 Mock Test Orchestra API is live!"}
