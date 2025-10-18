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

        return {
            "phase_type": phase_type,
            "phase_json": phase_json,
            "mentor_reply": mentor_reply
        }

    # ───────────────────────────────
    # 🟡 2️⃣ CHAT — CONTEXTUAL (concept or MCQ)
    # ───────────────────────────────
    elif action == "chat":
        pointer_id = None
        convo_log = []

        # 1️⃣ Fetch the latest pointer and append student's message
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

        # 2️⃣ Build GPT prompt
        prompt = """
You are a senior NEET-PG mentor with 30 yrs experience.

Input = array of chat objects [{mentor?, student?}].  
Use earlier messages as context; answer only the **last student's question**.

Reply in ONE of 5 mentor styles, matching the app’s rendering types:
1️⃣ "summary" → Crisp Clinical Summary (bullet points)
2️⃣ "differential" → Differential Table (comparison)
3️⃣ "highyield" → High-Yield Fact Sheet (emoji bullets)
4️⃣ "algorithm" → Algorithm / Flow Summary (→ steps)
5️⃣ "reflection" → Mentor Reflection Block (closing summary)

Rules:
• ≤120 words, NEET-PG tone (friendly + exam-focused)
• Use Unicode markup (**bold**, *italic*, subscripts/superscripts, arrows, emojis) — no LaTeX  
• Output **strict JSON**:

{
  "style_type": "<summary | differential | highyield | algorithm | reflection>",
  "mentor_reply": "<formatted mentor message>"
}

Now generate the mentor's reply.
"""

        # 3️⃣ Call GPT safely (catch all failures)
        mentor_reply = None
        gpt_status = "success"
        try:
            mentor_reply = chat_with_gpt(prompt, convo_log)
            # If GPT returned invalid JSON, fall back
            if not isinstance(mentor_reply, (dict, str)):
                raise ValueError("Malformed GPT reply")
        except Exception as e:
            print(f"❌ GPT call failed for student {student_id}: {e}")
            mentor_reply = {
                "style_type": "reflection",
                "mentor_reply": "⚠️ I'm having a small technical hiccup 🤖. Please try your question again in a bit!"
            }
            gpt_status = "failed"

        # 4️⃣ Append mentor reply to convo log
        convo_log.append({
            "role": "assistant",
            "content": mentor_reply,
            "ts": datetime.utcnow().isoformat() + "Z"
        })

        # 5️⃣ Try updating DB — but never block frontend if it fails
        db_status = "success"
        try:
            supabase.table("student_phase_pointer") \
                .update({"conversation_log": convo_log}) \
                .eq("pointer_id", pointer_id) \
                .execute()
        except Exception as e:
            db_status = "failed"
            print(f"⚠️ DB update failed for student {student_id}: {e}")

        # 6️⃣ Always respond to frontend
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

        return {
            "phase_type": phase_type,
            "phase_json": phase_json,
            "mentor_reply": mentor_reply
        }

    else:
        return {"error": f"Unknown action '{action}'"}


@app.get("/")
def home():
    return {"message": "🧠 Paragraph Orchestra API is running successfully!"}
