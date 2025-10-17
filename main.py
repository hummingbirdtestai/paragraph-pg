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
# Helper: Log conversation turn (student + mentor)
# ───────────────────────────────────────────────
def log_conversation(student_id: str, phase_type: str, phase_json: dict,
                     student_msg: str, mentor_msg):
    try:
        if isinstance(mentor_msg, (dict, list)):
            mentor_serialized = json.dumps(mentor_msg)
        elif mentor_msg is None:
            mentor_serialized = "null"
        else:
            mentor_serialized = str(mentor_msg)

        data = {
            "student_id": student_id,
            "phase_type": phase_type,
            "phase_json": phase_json,
            "conversation_log": [{"student": student_msg, "mentor": mentor_serialized}],
            "updated_at": datetime.utcnow().isoformat() + "Z"
        }
        res = supabase.table("student_conversation").insert(data).execute()
        if res.error:
            print("❌ Error inserting into student_conversation:", res.error)
    except Exception as e:
        print("⚠️ Exception during log_conversation:", e)


# ───────────────────────────────────────────────
# Helper: Append ChatGPT reply directly (no RPC)
# ───────────────────────────────────────────────
def append_mentor_message(student_id: str, mentor_reply: str):
    try:
        res = supabase.table("student_conversation")\
            .select("conversation_id, conversation_log")\
            .eq("student_id", student_id)\
            .order("updated_at", desc=True)\
            .limit(1)\
            .execute()

        if not res.data:
            print(f"⚠️ No active conversation found for student {student_id}")
            return

        convo = res.data[0]
        convo_id = convo["conversation_id"]
        convo_log = convo["conversation_log"] or []

        convo_log.append({
            "role": "assistant",
            "content": mentor_reply,
            "ts": datetime.utcnow().isoformat() + "Z"
        })

        supabase.table("student_conversation")\
            .update({"conversation_log": convo_log})\
            .eq("conversation_id", convo_id)\
            .execute()

    except Exception as e:
        print("⚠️ Exception in append_mentor_message:", e)


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
        rpc_data = call_rpc("append_student_message", {
            "p_student_id": student_id,
            "p_message": message
        })

        if not rpc_data:
            return {"error": "❌ append_student_message RPC failed"}

        conversation_log = rpc_data.get("conversation_log")

        # 🧠 GPT prompt — only uses conversation_log, with consistent style_type mapping
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
        mentor_reply = chat_with_gpt(prompt, conversation_log)
        append_mentor_message(student_id, mentor_reply)

        return {
            "mentor_reply": mentor_reply,
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
        mentor_reply = rpc_data.get("mentor_reply")

        log_conversation(student_id, phase_type, phase_json, "SYSTEM: next", mentor_reply)

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
