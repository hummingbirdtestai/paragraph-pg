# ───────────────────────────────────────────────
# NEWCHAT.PY
# ───────────────────────────────────────────────

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
import logging


from supabase_client import supabase
from gpt_utils import chat_with_gpt



# ───────────────────────────────────────────────
# LOGGER SETUP
# ───────────────────────────────────────────────
logger = logging.getLogger("ask_paragraph")
logger.setLevel(logging.INFO)

router = APIRouter()

# ───────────────────────────────────────────────
# DIALOG NORMALIZER (GPT SAFETY GATE)
# ───────────────────────────────────────────────
def normalize_dialogs(dialogs):
    """
    Enforces GPT-safe dialog schema:
    - skips system messages
    - skips non-string content
    - maps roles to OpenAI-compatible roles
    """
    safe = []
    skipped = 0

    for d in dialogs:
        role = d.get("role")
        content = d.get("content")

        if role == "system":
            skipped += 1
            continue

        if not isinstance(content, str):
            skipped += 1
            continue

        safe.append({
            "role": "assistant" if role == "assistant" else "user",
            "content": content,
        })

    if skipped:
        logger.warning(
            "[ASK_PARAGRAPH][NORMALIZE] skipped=%d total=%d",
            skipped,
            len(dialogs),
        )

    return safe


# ───────────────────────────────────────────────
# 🔒 VERBATIM SYSTEM PROMPT (DO NOT MODIFY)
# ───────────────────────────────────────────────
SYSTEM_PROMPT = """
You are a 30 Years Experienced NEETPG Teacher and AI Mentor.

The MCQ is the SINGLE and ONLY anchor of the conversation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ABSOLUTE AUTHORITY RULE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• YOU do NOT decide correctness
• YOU do NOT decide progression
• YOU do NOT decide mastery
• The BACKEND controls all state

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MCQ ANCHOR RULE (MANDATORY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

At any time there is EXACTLY ONE active MCQ.

• Student may ask questions
• Questions NEVER advance the session
• ONLY a correct MCQ answer ends the loop

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHEN STUDENT ASKS A QUESTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Answer briefly and clearly
• Do NOT evaluate correctness
• Do NOT change the MCQ
• Re-ask the SAME MCQ VERBATIM
• End with [STUDENT_REPLY_REQUIRED]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHEN STUDENT ANSWERS INCORRECTLY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Identify the precise learning gap
• Explain ONLY that gap
• Generate a NEW MCQ targeting that gap
• Provide 4 options (A–D)
• Mark the correct option explicitly
• End with [STUDENT_REPLY_REQUIRED]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHEN STUDENT ANSWERS CORRECTLY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Respond ONLY with:
  [FEEDBACK_CORRECT]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MCQ FORMAT (STRICT)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Whenever you generate an MCQ, use EXACTLY this format:

[MCQ]
Question: <text>
A. <option>
B. <option>
C. <option>
D. <option>
Correct: <A|B|C|D>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT RULES (NON-NEGOTIABLE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Plain text only
• No explanations outside rules
• No extra commentary
• No deviation from format
"""

import re

def parse_mcq_from_text(text: str):
    """
    Extracts MCQ question, options, and correct answer from GPT output.
    Returns None if parsing fails.
    """
    try:
        q = re.search(r"Question:\s*(.*)", text).group(1).strip()
        options = re.findall(r"[A-D]\.\s*(.*)", text)
        correct = re.search(r"Correct:\s*([A-D])", text).group(1)

        if len(options) != 4:
            return None

        return {
            "question": q,
            "options": options,
            "correct_answer": correct
        }
    except Exception:
        return None

# ───────────────────────────────────────────────
# START / RESUME MCQ SESSION
# ───────────────────────────────────────────────
@router.post("/start")
async def start_session(request: Request):
    data = await request.json()

    student_id = data["student_id"]
    mcq_id = data["mcq_id"]
    mcq_payload = data["mcq_payload"]

    gpt_reply = chat_with_gpt([
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"""
Here is the MCQ the student wants to understand:

{mcq_payload}

Explain briefly, then generate ONE MCQ.
Use the exact MCQ format.
End with [STUDENT_REPLY_REQUIRED].
"""
        }
    ])

    parsed = parse_mcq_from_text(gpt_reply)

    if not parsed:
        raise HTTPException(status_code=500, detail="Failed to generate MCQ")

    tutor_state = {
        "status": "active",
        "awaiting_answer": True,
        "recursion_depth": 0,
        "max_depth": 10,
        "current_mcq": {
            "id": "root",
            "question": parsed["question"],
            "options": parsed["options"],
            "correct_answer": parsed["correct_answer"]
        },
        "turns": 0
    }

    rpc = supabase.rpc(
        "upsert_mcq_session_v11",
        {
            "p_student_id": student_id,
            "p_mcq_id": mcq_id,
            "p_mcq_payload": mcq_payload,
            "p_new_dialogs": [
                {"role": "assistant", "content": gpt_reply}
            ],
            "p_tutor_state": tutor_state
        }
    ).execute()
    
    if not rpc.data:
        logger.error("[ASK_PARAGRAPH][START] RPC returned no data")
        raise HTTPException(status_code=500, detail="Failed to start session")
    
    return rpc.data[0]



# ───────────────────────────────────────────────
# 🔥 LOAD EXISTING SESSION
# ───────────────────────────────────────────────
@router.post("/session")
async def get_session(request: Request):
    data = await request.json()
    session_id = data["session_id"]

    logger.info(
        f"[ASK_PARAGRAPH][SESSION] Fetch session_id={session_id}"
    )

    row = (
        supabase.table("student_mcq_session")
        .select("id, dialogs, tutor_state, next_suggestions")
        .eq("id", session_id)
        .limit(1)
        .execute()
    )

    if not row.data:
        logger.warning(
            f"[ASK_PARAGRAPH][SESSION][404] Session not found session_id={session_id}"
        )
        raise HTTPException(status_code=404, detail="Session not found")

    logger.info(
        f"[ASK_PARAGRAPH][SESSION] Loaded dialogs={len(row.data[0]['dialogs'])} "
        f"turns={row.data[0]['tutor_state'].get('turns')}"
    )

    return {
        "session_id": row.data[0]["id"],
        "dialogs": row.data[0]["dialogs"],
        "tutor_state": row.data[0]["tutor_state"],
        "next_suggestions": row.data[0]["next_suggestions"],
    }

def get_active_mcq_context(dialogs, max_turns=4):
    """
    Returns only the most recent MCQ interaction
    to prevent option & concept pollution.
    """
    filtered = []

    # Walk backwards
    for d in reversed(dialogs):
        if d.get("role") == "assistant" and "[MCQ" in d.get("content", ""):
            filtered.append(d)
            break
        filtered.append(d)

    # Restore order and cap size
    return normalize_dialogs(list(reversed(filtered))[-max_turns:])

def is_mcq_answer(text: str) -> bool:
    t = text.strip().lower()
    return (
        t in {"a", "b", "c", "d"}
        or t.startswith(("option", "ans", "answer"))
        or len(t.split()) <= 3
    )

def generate_reinforcement(current_mcq: dict) -> str:
    """
    Generates post-mastery reinforcement:
    - 10 high-yield exam facts
    - 1 comparison table
    Runs ONLY after FEEDBACK_CORRECT
    """

    question = current_mcq.get("question", "")
    options = current_mcq.get("options", [])

    return chat_with_gpt([
        {
            "role": "system",
            "content": """
You are a senior NEET-PG mentor.

The student has JUST answered an MCQ correctly.

Your task is FINAL EXAM REINFORCEMENT.

━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT (STRICT)
━━━━━━━━━━━━━━━━━━━━━━

[HIGH_YIELD_FACTS]
• EXACTLY 10 bullet points
• One line each
• Pure exam facts
• No explanations

[EXAM_COMPARISON_TABLE]
• ONE table only
• NEET-PG relevant
• Minimal rows
• Markdown table

━━━━━━━━━━━━━━━━━━━━━━
RULES
━━━━━━━━━━━━━━━━━━━━━━

• DO NOT ask questions
• DO NOT generate MCQs
• DO NOT repeat the MCQ
• DO NOT explain answers
• Plain text only
"""
        },
        {
            "role": "user",
            "content": f"""
MCQ QUESTION:
{question}

OPTIONS:
{options}

Generate reinforcement.
"""
        }
    ])


# ───────────────────────────────────────────────
# CONTINUE CHAT (STUDENT → MENTOR) — DIAGNOSTIC BUILD
# ───────────────────────────────────────────────
@router.post("/chat")
async def continue_chat(request: Request):

    logger.info("🚀 /chat ENTERED")

    # ─────────────────────────────────────────
    # PARSE REQUEST
    # ─────────────────────────────────────────
    try:
        data = await request.json()
    except Exception:
        logger.exception("❌ Invalid JSON")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    student_id = data.get("student_id")
    mcq_id = data.get("mcq_id")
    student_message = data.get("message", "")

    logger.info(
        "👤 student_id=%s mcq_id=%s msg_len=%d",
        student_id,
        mcq_id,
        len(student_message or "")
    )

    # ─────────────────────────────────────────
    # FETCH SESSION
    # ─────────────────────────────────────────
    row = (
        supabase.table("student_mcq_session")
        .select("dialogs, tutor_state")
        .eq("student_id", student_id)
        .eq("mcq_id", mcq_id)
        .single()
        .execute()
    )

    if not row.data:
        logger.error("❌ Session not found")
        raise HTTPException(status_code=404, detail="Session not found")

    dialogs = row.data.get("dialogs") or []
    tutor_state = row.data.get("tutor_state") or {}
    current_mcq = tutor_state.get("current_mcq", {})

    # 🔒 OPTIONAL HARD GUARD — prevent re-entry after mastery
    if tutor_state.get("status") == "mastered":
        return StreamingResponse(
            iter(["[SESSION_COMPLETED]"]),
            media_type="text/plain"
        )

    # ─────────────────────────────────────────
    # GPT CALL (MAIN TUTOR)
    # ─────────────────────────────────────────
    try:
        reply = chat_with_gpt([
            {"role": "system", "content": SYSTEM_PROMPT},
            *get_active_mcq_context(dialogs),
            {
                "role": "user",
                "content": student_message
            }
        ])
    except Exception:
        logger.exception("🔥 GPT failed")
        reply = "[MENTOR]\nTemporary issue. Please retry."

    logger.info("🤖 GPT reply_len=%d", len(reply))

    final_reply = reply

    # ─────────────────────────────────────────
    # ✅ POST-MASTERY ENRICHMENT
    # ─────────────────────────────────────────
    if "[FEEDBACK_CORRECT]" in reply:
        logger.info("🏁 MCQ MASTERED")

        tutor_state["status"] = "mastered"
        tutor_state["awaiting_answer"] = False

        try:
            reinforcement = generate_reinforcement(current_mcq)
        except Exception:
            logger.exception("❌ Reinforcement generation failed")
            reinforcement = ""

        final_reply = "[FEEDBACK_CORRECT]"
        if reinforcement:
            final_reply += "\n\n" + reinforcement

    # ─────────────────────────────────────────
    # UPDATE STATE + DIALOGS
    # ─────────────────────────────────────────
    tutor_state["turns"] = (tutor_state.get("turns") or 0) + 1

    supabase.rpc(
        "upsert_mcq_session_v11",
        {
            "p_student_id": student_id,
            "p_mcq_id": mcq_id,
            "p_mcq_payload": {},
            "p_new_dialogs": [
                {"role": "student", "content": student_message},
                {"role": "assistant", "content": final_reply},
            ],
            "p_tutor_state": tutor_state,
        }
    ).execute()

    # ─────────────────────────────────────────
    # STREAM RESPONSE (SINGLE YIELD — FE SAFE)
    # ─────────────────────────────────────────
    def event_generator():
        yield final_reply
        return

    return StreamingResponse(
        event_generator(),
        media_type="text/plain"
    )
