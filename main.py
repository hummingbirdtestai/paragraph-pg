# main.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from supabase_client import call_rpc, supabase
from gpt_utils import chat_with_gpt

# ───────────────────────────────────────────────
# Initialize FastAPI app
# ───────────────────────────────────────────────
app = FastAPI(title="Paragraph Orchestra API", version="1.0.0")

# ✅ Allow your frontend (Expo/Web/React) to call this API from any origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # You can replace "*" with your frontend domain later for security
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ───────────────────────────────────────────────
# Helper: Log conversation turns in Supabase
# ───────────────────────────────────────────────
def log_conversation(student_id: str, phase_type: str, phase_json: dict, student_msg: str, mentor_msg: str):
    """
    Stores one conversation turn (student + mentor messages) into student_conversation.
    """
    try:
        data = {
            "student_id": student_id,
            "phase_type": phase_type,
            "phase_json": phase_json,
            "conversation_log": [{"student": student_msg, "mentor": mentor_msg}],
            "updated_at": datetime.utcnow().isoformat()
        }
        res = supabase.table("student_conversation").insert(data).execute()
        if res.error:
            print("❌ Error inserting into student_conversation:", res.error)
    except Exception as e:
        print("⚠️ Exception during log_conversation:", e)


# ───────────────────────────────────────────────
# Master Endpoint — handles all actions
# ───────────────────────────────────────────────
@app.post("/orchestrate")
async def orchestrate(request: Request):
    """
    Handles all frontend actions: start, chat, next.
    Communicates with Supabase (RPCs) + GPT for mentor responses.
    """
    payload = await request.json()
    action = payload.get("action")
    student_id = payload.get("student_id")
    message = payload.get("message")

    print(f"🎬 Action = {action}, Student = {student_id}")

    # ───────────────────────────────
    # 🟢 1️⃣ START
    # ───────────────────────────────
    if action == "start":
        rpc_data = call_rpc("start_orchestra", {"p_student_id": student_id})
        if not rpc_data:
            return {"error": "❌ start_orchestra RPC failed"}

        phase_type = rpc_data.get("phase_type")
        phase_json = rpc_data.get("phase_json")

        prompt = "You are the mentor. Explain this paragraph conversationally to the student."

        mentor_reply = chat_with_gpt(prompt, phase_json)
        log_conversation(student_id, phase_type, phase_json, "SYSTEM: start", mentor_reply)

        return {
            "phase_type": phase_type,
            "phase_json": phase_json,
            "mentor_reply": mentor_reply
        }

    # ───────────────────────────────
    # 🟡 2️⃣ CHAT
    # ───────────────────────────────
    elif action == "chat":
        rows = supabase.table("student_conversation") \
            .select("phase_type, phase_json") \
            .eq("student_id", student_id) \
            .order("updated_at", desc=True) \
            .limit(1) \
            .execute()

        if not rows.data:
            return {"error": "⚠️ No active phase found for this student"}

        phase_type = rows.data[0]["phase_type"]
        phase_json = rows.data[0]["phase_json"]

        if phase_type == "concept":
            prompt = "Continue explaining and clarify the student's question about this concept."
        else:
            prompt = "Clarify the reasoning or concept behind this MCQ question."

        mentor_reply = chat_with_gpt(prompt, phase_json, message)
        log_conversation(student_id, phase_type, phase_json, message, mentor_reply)

        return {"mentor_reply": mentor_reply}

    # ───────────────────────────────
    # 🔵 3️⃣ NEXT
    # ───────────────────────────────
    elif action == "next":
        rpc_data = call_rpc("next_orchestra", {"p_student_id": student_id})
        if not rpc_data:
            return {"error": "❌ next_orchestra RPC failed"}

        phase_type = rpc_data.get("phase_type")
        phase_json = rpc_data.get("phase_json")

        if phase_type == "concept":
            prompt = "Introduce and explain this next paragraph to the student."
        else:
            prompt = "Present this question interactively and motivate the student to answer."

        mentor_reply = chat_with_gpt(prompt, phase_json)
        log_conversation(student_id, phase_type, phase_json, "SYSTEM: next", mentor_reply)

        return {
            "phase_type": phase_type,
            "phase_json": phase_json,
            "mentor_reply": mentor_reply
        }

    # ───────────────────────────────
    # ❌ Fallback
    # ───────────────────────────────
    else:
        return {"error": f"Unknown action '{action}'"}


# ───────────────────────────────────────────────
# Health check route
# ───────────────────────────────────────────────
@app.get("/")
def home():
    """
    Simple root route to verify API health.
    """
    return {"message": "🧠 Paragraph Orchestra API is running successfully!"}
