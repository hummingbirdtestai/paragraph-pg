from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from supabase_client import call_rpc, supabase
from gpt_utils import chat_with_gpt  # ✅ GPT mentor replies for flashcard chat
import json

# ───────────────────────────────────────────────
# Initialize FastAPI app
# ───────────────────────────────────────────────
app = FastAPI(title="Flashcard Orchestra API", version="2.0.0")

# ✅ Allow frontend (Expo / Web / React) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────────────────────────────────────────────
# Master Endpoint — handles all flashcard actions
# ───────────────────────────────────────────────
@app.post("/flashcard_orchestrate")
async def flashcard_orchestrate(request: Request):
    payload = await request.json()
    action = payload.get("action")
    student_id = payload.get("student_id")
    message = payload.get("message")

    print(f"🎬 Flashcard Action = {action}, Student = {student_id}")

    # ───────────────────────────────
    # 🟢 1️⃣ START_FLASHCARD
    # ───────────────────────────────
    if action == "start_flashcard":
        rpc_data = call_rpc("start_flashcard_orchestra", {"p_student_id": student_id})
        if not rpc_data:
            return {"error": "❌ start_flashcard_orchestra RPC failed"}

        phase_type = rpc_data.get("phase_type")
        phase_json = rpc_data.get("phase_json")
        mentor_reply = rpc_data.get("mentor_reply")
        react_order_final = rpc_data.get("react_order_final")
        concept = rpc_data.get("concept")
        subject = rpc_data.get("subject")

        return {
            "student_id": student_id,
            "react_order_final": react_order_final,
            "phase_type": phase_type,
            "phase_json": phase_json,
            "mentor_reply": mentor_reply,
            "concept": concept,
            "subject": subject
        }

    # ───────────────────────────────
    # 🟡 2️⃣ CHAT_FLASHCARD — contextual mentor interaction
    # ───────────────────────────────
    elif action == "chat_flashcard":
        pointer_id = None
        convo_log = []

        try:
            res = (
                supabase.table("student_flashcard_pointer")
                .select("pointer_id, conversation_log")
                .eq("student_id", student_id)
                .order("updated_at", desc=True)
                .limit(1)
                .execute()
            )
            if not res.data:
                print(f"⚠️ No flashcard pointer found for student {student_id}")
                return {"error": "⚠️ No active flashcard pointer for this student"}

            pointer = res.data[0]
            pointer_id = pointer["pointer_id"]
            convo_log = pointer.get("conversation_log", [])
            convo_log.append({
                "role": "student",
                "content": message,
                "ts": datetime.utcnow().isoformat() + "Z"
            })
        except Exception as e:
            print(f"⚠️ Failed to fetch or append student flashcard message: {e}")
            return {"error": "❌ Failed to fetch pointer or append message"}

        # ✅ Prompt for GPT mentor reply (flashcard context)
        prompt = """
You are a senior NEET-PG mentor with 30 years’ experience. 
You are helping a student with flashcard-based rapid revision.

You are given the full flashcard conversation log — a list of chat objects in the format:
[{ "role": "mentor" | "student", "content": "..." }]

👉 Use earlier messages only for context, but reply **only to the latest student message**.

🧠 Your reply must be in **natural Markdown** using **Unicode symbols** (no JSON, no code block).  
It should be concise, focused on reinforcing key flashcard recall concepts, and formatted for a WhatsApp-like dark chat bubble.

### Formatting Rules
- Use Markdown headings:
  - `#`, `##`, `###` for title / subheading / subsection
- Use **bold** and _italic_ text for emphasis
- Use lists and numbering for structure
- Use Unicode arrows (→, ↑, ↓), subscripts/superscripts (₁, ₂, ³, ⁺, ⁻)
- Use emojis sparingly (💡 🧠 ⚕️ 📘)
- ≤100 words
- Avoid emotional tone — be clinical, clear, and high-yield.
"""

        mentor_reply = None
        gpt_status = "success"

        try:
            mentor_reply = chat_with_gpt(prompt, convo_log)
            if not isinstance(mentor_reply, str):
                mentor_reply = str(mentor_reply)
        except Exception as e:
            print(f"❌ GPT call failed for student {student_id}: {e}")
            mentor_reply = "⚠️ I'm having a small technical hiccup 🤖. Please try again soon!"
            gpt_status = "failed"

        convo_log.append({
            "role": "assistant",
            "content": mentor_reply,
            "ts": datetime.utcnow().isoformat() + "Z"
        })

        db_status = "success"
        try:
            supabase.table("student_flashcard_pointer") \
                .update({"conversation_log": convo_log}) \
                .eq("pointer_id", pointer_id) \
                .execute()
        except Exception as e:
            db_status = "failed"
            print(f"⚠️ DB update failed for flashcard conversation: {e}")

        return {
            "mentor_reply": mentor_reply,
            "context_used": True,
            "db_update_status": db_status,
            "gpt_status": gpt_status
        }

    # ───────────────────────────────
    # 🔵 3️⃣ NEXT_FLASHCARD — advance to next phase
    # ───────────────────────────────
    elif action == "next_flashcard":
        rpc_data = call_rpc("next_flashcard_orchestra", {"p_student_id": student_id})
        if not rpc_data:
            return {"error": "❌ next_flashcard_orchestra RPC failed"}

        phase_type = rpc_data.get("phase_type")
        phase_json = rpc_data.get("phase_json")
        mentor_reply = rpc_data.get("mentor_reply")
        react_order_final = rpc_data.get("react_order_final")
        concept = rpc_data.get("concept")
        subject = rpc_data.get("subject")

        return {
            "student_id": student_id,
            "react_order_final": react_order_final,
            "phase_type": phase_type,
            "phase_json": phase_json,
            "mentor_reply": mentor_reply,
            "concept": concept,
            "subject": subject
        }

    else:
        return {"error": f"Unknown flashcard action '{action}'"}


# ───────────────────────────────────────────────
# 🟠 SUBMIT_FLASHCARD_PROGRESS — track per-phase progress
# ───────────────────────────────────────────────
@app.post("/submit_flashcard_progress")
async def submit_flashcard_progress(request: Request):
    """Optionally record per-card progress or time spent per flashcard phase"""
    try:
        data = await request.json()
        student_id = data.get("student_id")
        react_order_final = data.get("react_order_final")
        progress = data.get("progress", {})
        completed = data.get("completed", False)

        supabase.table("student_flashcard_pointer") \
            .update({
                "last_progress": progress,
                "is_completed": completed,
                "updated_at": datetime.utcnow().isoformat() + "Z"
            }) \
            .eq("student_id", student_id) \
            .eq("react_order_final", react_order_final) \
            .execute()

        print(f"✅ Flashcard progress updated for {student_id}, react_order {react_order_final}")
        return {"status": "success"}

    except Exception as e:
        print(f"❌ Error updating flashcard progress: {e}")
        return {"error": str(e)}


# ───────────────────────────────────────────────
# Health Check
# ───────────────────────────────────────────────
@app.get("/")
def home():
    return {"message": "🧠 Flashcard Orchestra API is running successfully!"}
