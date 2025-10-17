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
        # ✅ Serialize mentor_msg safely (handles dicts/lists/None)
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
        mentor_reply = rpc_data.get("mentor_reply")  # ✅ now fetched directly from RPC

        # ✅ no GPT call — just log and return
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

        phase_json = rpc_data.get("phase_json")
        conversation_log = rpc_data.get("conversation_log")

        # 🧠 still use GPT for live mentor interaction
        prompt = """
You are a 30-year-experienced NEET-PG faculty mentor.

The input is a conversation log between a mentor and a student.
All messages before the last one are context from previous exchanges.
The last message is the student’s current question that you must now answer.

Answer naturally like a NEET-PG teacher — accurate, concise, empathetic, and exam-focused.

Choose one suitable delivery style from this list (only one):
text_explanation, summary_paragraph, step_by_step, example_block, storytelling, quote, dialogue_snippet, code_explanation,
hyf_list, pros_cons_list, key_points, checklist, timeline_list, mnemonic_list,
mcq_block, true_false, flashcard_set, reflection_prompt, confidence_poll,
image_explanation, media_suggestion, chart_data,
tabular_summary, ranking_list,
cognitive_load_meter, mastery_feedback, error_analysis, learning_gap_report,
conversation_reply, action_prompt, system_message, chapter_completion, mentor_reflection,
case_scenario, branching_decision, role_play,
poetic_explanation, motivational_quote, metaphorical_teaching, daily_tip,
concept_intro, exam_strategy, clinical_correlation, quick_revision, pitfall_warning,
ai_generated_hint, doubt_clarification, reinforcement_card, summary_box, teaching_point,
table_comparison, fact_grid, quote_highlight, mentor_reflection_emotive,
gap_fix_pair, mistake_correction, clinical_case_flow, study_tip, encouragement_burst,
concept_bridge, exam_alert, mentor_story, creative_summary.

Return your answer strictly in this JSON format:

{
  "type": "<one_of_the_styles_above>",
  "text": "your mentor reply here"
}

Do not include explanations, prefaces, or any extra text — only valid JSON.
"""
        mentor_reply = chat_with_gpt(prompt, conversation_log)
        append_mentor_message(student_id, mentor_reply)

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
        mentor_reply = rpc_data.get("mentor_reply")  # ✅ directly from RPC

        # ✅ no GPT call — just log and return
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
