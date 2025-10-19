from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from supabase_client import call_rpc, supabase
from gpt_utils import chat_with_gpt  # ✅ still needed for chat only
import json

# ───────────────────────────────────────────────
# Initialize FastAPI app
# ───────────────────────────────────────────────
app = FastAPI(title="Paragraph Orchestra API", version="2.0.0")

# ✅ Allow frontend (Expo / Web / React) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────────────────────────────────────────────
# Master Endpoint — handles all actions
# ───────────────────────────────────────────────
@app.post("/orchestrate")
async def orchestrate(request: Request):
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
        mentor_reply = rpc_data.get("mentor_reply")
        react_order_final = rpc_data.get("react_order_final")

        return {
            "student_id": student_id,
            "react_order_final": react_order_final,
            "phase_type": phase_type,
            "phase_json": phase_json,
            "mentor_reply": mentor_reply
        }

    # ───────────────────────────────
    # 🟡 2️⃣ CHAT — CONTEXTUAL
    # ───────────────────────────────
    elif action == "chat":
        pointer_id = None
        convo_log = []

        try:
            res = (
                supabase.table("student_phase_pointer")
                .select("pointer_id, conversation_log")
                .eq("student_id", student_id)
                .order("updated_at", desc=True)
                .limit(1)
                .execute()
            )
            if not res.data:
                print(f"⚠️ No pointer found for student {student_id}")
                return {"error": "⚠️ No active pointer for this student"}

            pointer = res.data[0]
            pointer_id = pointer["pointer_id"]
            convo_log = pointer.get("conversation_log", [])
            convo_log.append({
                "role": "student",
                "content": message,
                "ts": datetime.utcnow().isoformat() + "Z"
            })
        except Exception as e:
            print(f"⚠️ Failed to fetch or append student message: {e}")
            return {"error": "❌ Failed to fetch pointer or append message"}

        # ✅ Updated Prompt — Markdown Natural Mentor Reply
        prompt = """
You are a senior NEET-PG mentor with 30 years’ experience. 
You are guiding a medical student preparing for NEET-PG.

You are given the full conversation log — a list of chat objects in the format:
[{ "role": "mentor" | "student", "content": "..." }]

👉 Use earlier messages only for context, but reply **only to the latest student message**.

🧠 Your reply must be in **natural Markdown** using **Unicode symbols** (no JSON, no code block).  
It should be formatted for a WhatsApp-like dark chat bubble — clear, concise, and NEET-PG exam-oriented.

### Formatting Rules
- Use Markdown headings:
  - `#`, `##`, `###` for title / subheading / subsection
- Use bold (**text**) and italic (_text_)
- Use lists and numbering for structured points
- Use Unicode arrows (→, ↑, ↓), subscripts/superscripts (₁, ₂, ³, ⁺, ⁻)
- Use emojis where relevant (💡 🧠 🩸 ⚕️ 📘)
- Use line breaks for readability
- ≤150 words per answer
- Do **not** explain or describe your format — just reply naturally.

### Example
# Respiratory Failure  
## Stepwise Approach  
1. Check **ABG** → PaO₂ < 60 mm Hg?  
2. Assess **PaCO₂** → ↑ → Type II  
3. Determine cause → airway, lung, or pump failure  

💡 *Type I:* oxygenation defect  
💡 *Type II:* ventilation defect
"""

        mentor_reply = None
        gpt_status = "success"

        try:
            mentor_reply = chat_with_gpt(prompt, convo_log)

            # ✅ No parsing or stringification — keep raw Markdown string
            if not isinstance(mentor_reply, str):
                mentor_reply = str(mentor_reply)

        except Exception as e:
            print(f"❌ GPT call failed for student {student_id}: {e}")
            mentor_reply = "⚠️ I'm having a small technical hiccup 🤖. Please try your question again in a bit!"
            gpt_status = "failed"

        convo_log.append({
            "role": "assistant",
            "content": mentor_reply,
            "ts": datetime.utcnow().isoformat() + "Z"
        })

        db_status = "success"
        try:
            supabase.table("student_phase_pointer") \
                .update({"conversation_log": convo_log}) \
                .eq("pointer_id", pointer_id) \
                .execute()
        except Exception as e:
            db_status = "failed"
            print(f"⚠️ DB update failed for student {student_id}: {e}")

        return {
            "mentor_reply": mentor_reply,
            "context_used": True,
            "db_update_status": db_status,
            "gpt_status": gpt_status
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
        mentor_reply = rpc_data.get("mentor_reply")
        react_order_final = rpc_data.get("react_order_final")

        return {
            "student_id": student_id,
            "react_order_final": react_order_final,
            "phase_type": phase_type,
            "phase_json": phase_json,
            "mentor_reply": mentor_reply
        }

    else:
        return {"error": f"Unknown action '{action}'"}


# ───────────────────────────────────────────────
# 🟠 SUBMIT ANSWER — simplified
# ───────────────────────────────────────────────
@app.post("/submit_answer")
async def submit_answer(request: Request):
    try:
        data = await request.json()
        student_id = data.get("student_id")
        react_order_final = data.get("react_order_final")
        student_answer = data.get("student_answer")
        correct_answer = data.get("correct_answer")
        is_correct = data.get("is_correct")
        is_completed = data.get("is_completed", True)

        if not student_id or not react_order_final:
            return {"error": "❌ Missing student_id or react_order_final"}

        payload = {
            "student_id": student_id,
            "react_order_final": int(react_order_final),
            "student_answer": student_answer,
            "correct_answer": correct_answer,
            "is_correct": is_correct,
            "is_completed": is_completed,
            "submitted_at": datetime.utcnow().isoformat() + "Z",
        }

        supabase.table("student_mcq_submissions") \
            .upsert(payload, on_conflict=["student_id", "react_order_final"]) \
            .execute()

        print(f"✅ MCQ submission saved → student {student_id}, react_order_final {react_order_final}")
        return {"status": "success", "data": payload}

    except Exception as e:
        print(f"❌ Error in /submit_answer: {e}")
        return {"error": "⚠️ Failed to submit answer", "details": str(e)}


@app.get("/")
def home():
    return {"message": "🧠 Paragraph Orchestra API is running successfully!"}
