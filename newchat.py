# ───────────────────────────────────────────────
# NEWCHAT.PY
# ───────────────────────────────────────────────

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
import logging
import time

from supabase_client import supabase
from gpt_utils import chat_with_gpt

from chat.state_extractor import detect_last_block, extract_state
from chat.suggestion_engine import generate_suggestions

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
You are a 30 Years Experienced NEETPG Teacher and AI Mentor tutoring a NEETPG aspirant to MASTER the concepts required to solve the given MCQ.

Each MCQ has EXACTLY **3 core concepts** arranged in a dependency chain:
Concept 1 → Concept 2 → Concept 3

Your job is to ensure **true mastery** of each concept using a **depth-first recursive MCQ teaching strategy** before moving to the next concept.

────────────────────────────────
CORE TEACHING STRATEGY (MANDATORY)
────────────────────────────────

• Teaching must be **purely MCQ-driven**.
• NEVER switch to theory-only questioning.
• NEVER ask open-ended or descriptive questions.
• EVERY checkpoint must be an MCQ.

For EACH concept, follow this STRICT loop:

1️⃣ Explain ONE concept briefly, as in a real classroom.
2️⃣ Immediately ask an MCQ that tests ONLY that explained concept.
3️⃣ STOP and wait for the student’s response.

────────────────────────────────
RECURSIVE MASTERY RULE (CRITICAL)
────────────────────────────────

If the student answers the MCQ:

✅ CORRECT:
- Confirm correctness.
- Consider this concept MASTERED.
- Move to the NEXT concept in sequence.

❌ WRONG:
- Identify the **specific underlying sub-concept gap** responsible for the error.
- Explain ONLY that missing sub-concept.
- Ask a **NEW MCQ** that tests THIS clarification.
- Do NOT repeat the same MCQ.
- Continue recursively UNTIL the student answers correctly.
- ONLY THEN return to the parent concept and continue.

⚠️ You MUST drill DOWN until correctness is achieved.
⚠️ You MUST drill UP only after mastery is proven.

This creates a **recursive concept chain**, not a flat discussion.

────────────────────────────────
MCQ GENERATION RULES (VERY IMPORTANT)
────────────────────────────────

• Every MCQ must be freshly generated.
• NEVER reuse the original MCQ options.
• NEVER recycle option wording from earlier MCQs.
• NEVER keep the same 4 options across questions.

Each MCQ must:
- Test understanding of the **immediately preceding explanation**
- Reflect NEETPG exam style
- Have ONE unambiguous best answer

Options may test:
- Mechanisms
- Definitions
- Clinical application
- Logical contrasts
- Cause–effect reasoning

But they MUST be tied ONLY to the concept just taught.

────────────────────────────────
STUDENT QUESTION HANDLING
────────────────────────────────

When you ask an MCQ and wait, the student may:
(a) Answer the MCQ, OR
(b) Ask any question (related or unrelated).

If the student ASKS A QUESTION:
- Answer it clearly and concisely.
- Do NOT evaluate correctness.
- Do NOT mark MCQ right or wrong.
- RE-ASK the SAME MCQ afterward.
- End again with [STUDENT_REPLY_REQUIRED].

────────────────────────────────
MCQ EVALUATION RULES
────────────────────────────────

If the student ANSWERS an MCQ:
- Evaluate correctness strictly.

If correct:
→ Respond with [FEEDBACK_CORRECT]

If wrong:
→ Respond with [FEEDBACK_WRONG]
→ Then [CLARIFICATION]
→ Then ask a DIFFERENT MCQ to recheck understanding.

NEVER move forward without closing the MCQ loop.

────────────────────────────────
GLOBAL CONSTRAINTS (NON-NEGOTIABLE)
────────────────────────────────

• NEVER ignore a student message.
• NEVER respond with empty output.
• NEVER move to the next concept without MCQ-verified mastery.
• NEVER summarize early.
• NEVER skip recursive drilling.

────────────────────────────────
FINAL PHASE (ONLY AFTER ALL 3 CONCEPTS)
────────────────────────────────

After Concept 1, 2, and 3 are fully mastered:

1️⃣ Provide a concise [FINAL_ANSWER] to the original MCQ.
2️⃣ Provide a [CONCEPT_TABLE] as a ready-reckoner.
3️⃣ Provide [TAKEAWAYS]:
   - EXACTLY 5 high-yield facts
   - Exam-oriented
   - Memory-anchorable
   - Frequently tested in NEETPG

────────────────────────────────
OUTPUT FORMAT RULES (STRICT)
────────────────────────────────

• Output must be plain text.
• Use ONLY the approved semantic blocks.
• Approved blocks:
  [MENTOR]
  [CONCEPT title="..."]
  [MCQ id="..."]
  [STUDENT_REPLY_REQUIRED]
  [FEEDBACK_CORRECT]
  [FEEDBACK_WRONG]
  [CLARIFICATION]
  [RECHECK_MCQ id="..."]
  [CONCEPT_TABLE]
  [FINAL_ANSWER]
  [TAKEAWAYS]

• Do NOT invent new block types.
• Do NOT write text outside blocks.

────────────────────────────────
TABLE FORMATTING RULES (CRITICAL)
────────────────────────────────

• Use valid GitHub-flavored Markdown.
• Header row MUST be followed immediately by |---|.
• Do NOT add extra dashed lines or blank rows.
• Do NOT break tables across blocks.
"""

# ───────────────────────────────────────────────
# START / RESUME MCQ SESSION
# ───────────────────────────────────────────────
@router.post("/start")
async def start_session(request: Request):
    data = await request.json()

    student_id = data["student_id"]
    mcq_id = data["mcq_id"]
    mcq_payload = data["mcq_payload"]

    logger.info(
        f"[ASK_PARAGRAPH][START] student_id={student_id} mcq_id={mcq_id}"
    )

    mentor_reply = chat_with_gpt([
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"""
Here is the MCQ the student is asking about:

{mcq_payload}

Begin the discussion.
"""
        }
    ])

    # ⬇️ ADD HERE — initialize teaching state
    initial_tutor_state = {
        "phase": "mcq_teaching",
        "concept_index": 1,
        "recursion_depth": 0,
        "concept_mastered": False,
        "turns": 0,
        "last_block": "[STUDENT_REPLY_REQUIRED]"
    }

    logger.info(
        f"[ASK_PARAGRAPH][START] Initial mentor reply generated "
        f"(chars={len(mentor_reply)})"
    )

    rpc = supabase.rpc(
        "upsert_mcq_session_v11",
        {
            "p_student_id": student_id,
            "p_mcq_id": mcq_id,
            "p_mcq_payload": mcq_payload,
            "p_new_dialogs": [
                {
                    "role": "assistant",
                    "content": mentor_reply,
                    "mcq_payload": mcq_payload
                }
            ],
            "p_tutor_state": initial_tutor_state
        }
    ).execute()

    if not rpc.data:
        logger.error(
            f"[ASK_PARAGRAPH][START][ERROR] Failed to persist session"
        )
        raise HTTPException(status_code=500, detail="Failed to start MCQ session")

    logger.info(
        f"[ASK_PARAGRAPH][START] Session created successfully"
    )

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


# ───────────────────────────────────────────────
# CONTINUE CHAT (STUDENT → MENTOR)
# ───────────────────────────────────────────────
@router.post("/chat")
async def continue_chat(request: Request):
    start_time = time.time()

    data = await request.json()
    student_id = data["student_id"]
    mcq_id = data["mcq_id"]
    student_message = data["message"]

    logger.info(
        "[ASK_PARAGRAPH][STUDENT_INPUT] raw='%s'",
        student_message.strip(),
    )

    logger.info(
        f"[ASK_PARAGRAPH][CHAT] student_id={student_id} mcq_id={mcq_id} "
        f"message_len={len(student_message or '')}"
    )

    row = (
        supabase.table("student_mcq_session")
        .select("dialogs, tutor_state")
        .eq("student_id", student_id)
        .eq("mcq_id", mcq_id)
        .single()
        .execute()
    )

    if not row.data:
        logger.warning(
            f"[ASK_PARAGRAPH][CHAT][404] Session not found "
            f"student_id={student_id} mcq_id={mcq_id}"
        )
        raise HTTPException(status_code=404, detail="Session not found")

    dialogs = row.data["dialogs"]
    tutor_state = row.data["tutor_state"] or {}
    concept_index = tutor_state.get("concept_index", 1)
    recursion_depth = tutor_state.get("recursion_depth", 0)

    if tutor_state.get("last_block") == "[STUDENT_REPLY_REQUIRED]":
        if not student_message or not student_message.strip():
            raise HTTPException(
                status_code=409,
                detail="Student response required before proceeding"
            )

    mcq_payload = None
    for d in dialogs:
        if d["role"] == "assistant" and isinstance(d.get("mcq_payload"), dict):
            mcq_payload = d["mcq_payload"]
            break

    mcq_context = ""
    if mcq_payload:
        mcq_context = f"""
MCQ CONTEXT (DO NOT REPEAT VERBATIM):
Stem: {mcq_payload.get("stem")}
Options: {mcq_payload.get("options")}
Correct Answer: {mcq_payload.get("correct_answer")}
Feedback: {mcq_payload.get("feedback")}
Learning Gap: {mcq_payload.get("learning_gap")}
"""

    gpt_messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
    
    if mcq_context:
        gpt_messages.append({
            "role": "user",
            "content": mcq_context
        })
    
    gpt_messages.extend(get_active_mcq_context(dialogs))

    gpt_messages.append({
        "role": "user",
        "content": f"""
Student response:
\"\"\"{student_message}\"\"\"

Decide whether this is:
- an MCQ answer (letter or free text), OR
- a question.

Follow all conversation rules strictly.
"""
    })

    logger.info(
        "[ASK_PARAGRAPH][GPT_REPLAY] messages=%d chars≈%d",
        len(gpt_messages),
        sum(len(m["content"]) for m in gpt_messages),
    )

    def event_generator():
        full_reply = ""
    
        try:

            full_reply = chat_with_gpt(gpt_messages)
            yield full_reply

    
        finally:
            if not full_reply:
                full_reply = "[MENTOR]\nTemporary issue. Please retry."
    
            prev_block = tutor_state.get("last_block")
            last_block = detect_last_block(full_reply)
    
            if tutor_state.get("recursion_depth", 0) > 5:
                tutor_state["recursion_depth"] = 0
    
            if last_block == "[FEEDBACK_CORRECT]":
                tutor_state["concept_index"] = min(
                    tutor_state.get("concept_index", 1) + 1,
                    3
                )
                tutor_state["recursion_depth"] = 0
            
            elif last_block == "[FEEDBACK_WRONG]":
                tutor_state["recursion_depth"] += 1

    
            tutor_state["last_block"] = last_block
            tutor_state["turns"] = (tutor_state.get("turns", 0) or 0) + 1
    
            supabase.rpc(
                "upsert_mcq_session_v11",
                {
                    "p_student_id": student_id,
                    "p_mcq_id": mcq_id,
                    "p_mcq_payload": {},
                    "p_new_dialogs": [
                        {"role": "student", "content": student_message},
                        {"role": "assistant", "content": full_reply},
                    ],
                    "p_tutor_state": tutor_state,
                }
            ).execute()
    
            state = extract_state({
                "dialogs": dialogs + [
                    {"role": "student", "content": student_message},
                    {"role": "assistant", "content": full_reply},
                ],
                "current_concept": tutor_state.get("concept_index"),
            })
    
            suggestions = generate_suggestions(state)
    
            supabase.table("student_mcq_session").update(
                {"next_suggestions": suggestions}
            ).eq("student_id", student_id).eq("mcq_id", mcq_id).execute()



    # ────────────────
    # 🔧 SURGICAL NON-STREAMING EXECUTION
    # ────────────────
    return StreamingResponse(
        event_generator(),
        media_type="text/plain"
    )
