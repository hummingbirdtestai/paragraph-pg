# main.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from supabase_client import call_rpc, supabase
from gpt_utils import chat_with_gpt

# ───────────────────────────────────────────────
# Initialize FastAPI app
# ───────────────────────────────────────────────
app = FastAPI(title="Paragraph Orchestra API", version="2.0.0")

# ✅ Allow frontend (Expo / Web / React) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # replace "*" with your frontend domain later for security
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ───────────────────────────────────────────────
# Helper: Log conversation turn (student + mentor)
# ───────────────────────────────────────────────
def log_conversation(student_id: str, phase_type: str, phase_json: dict,
                     student_msg: str, mentor_msg: str):
    """
    Inserts a conversation turn into student_conversation table.
    Each row represents one turn (user + mentor).
    """
    try:
        data = {
            "student_id": student_id,
            "phase_type": phase_type,
            "phase_json": phase_json,
            "conversation_log": [{"student": student_msg, "mentor": mentor_msg}],
            "updated_at": datetime.utcnow().isoformat() + "Z"
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
    # 🟡 2️⃣ CHAT — CONTEXTUAL (concept or MCQ)
    # ───────────────────────────────
    elif action == "chat":
        # 1️⃣ Append the student's message in the DB & get latest conversation
        rpc_data = call_rpc("append_student_message", {
            "p_student_id": student_id,
            "p_message": message
        })

        if not rpc_data:
            return {"error": "❌ append_student_message RPC failed"}

        phase_json = rpc_data.get("phase_json")
        conversation_log = rpc_data.get("conversation_log")

        # 2️⃣ Find the most recent mentor reply for context
        previous_mentor_reply = None
        if conversation_log and isinstance(conversation_log, list):
            for item in reversed(conversation_log):
                if isinstance(item, dict):
                    # works with both new structure ('role':'assistant') and old ('mentor')
                    if item.get("role") == "assistant" or "mentor" in item:
                        previous_mentor_reply = item.get("content") or item.get("mentor")
                        break

        # 3️⃣ Build the contextual prompt
        if previous_mentor_reply:
            prompt = (
                "You are the student's mentor continuing an ongoing learning conversation.\n"
                f"Previous mentor reply:\n{previous_mentor_reply}\n\n"
                f"Student just asked:\n{message}\n\n"
                "Please respond naturally, referring to the concept or MCQ context below:\n"
            )
        else:
            prompt = (
                "Continue explaining based on the student's question below:\n"
                f"{message}\n\nHere is the context:\n"
            )

        # 4️⃣ Send context to GPT
        mentor_reply = chat_with_gpt(prompt, phase_json)

        # 5️⃣ Log mentor response (for visibility / analytics)
        log_conversation(student_id, "contextual_chat", phase_json, message, mentor_reply)

        # 6️⃣ Return mentor response to frontend
        return {
            "mentor_reply": mentor_reply,
            "phase_json": phase_json,
            "context_used": True
        }

    # ───────────────────────────────
    # 🔵 3️⃣ NEXT — advance to next phase
    # ───────────────────────────────
    elif action == "next":
        rpc_data = call_rpc("next_orchestra", {"p_student_id": student_id})
        if not rpc_data:
            return {"error": "❌ next_orchestra RPC failed"}

        phase_type = rpc_data.get("phase_type")
        phase_json = rpc_data.get("phase_json")

        # Choose prompt dynamically
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
    # ❌ Unknown Action
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
