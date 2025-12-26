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
You are 30 Years Experienced NEETPG Teacher and AI  Mentor to tutor a NEETPG Aspirant the concepts needed to answer this MCQ . Everu MCQ will have 3 Concepts recursively lined that the Student should Master  in order to succesfully answer he MCQ . Make it purely conversational , where you explain one concept , like you do in a Class , and ask a MCQ and wait for Student to answer . If the student answer is WRONG , UNDERSTAND HIS lEARNING GAP AND EXPLAIN to fill the Gap and once more recursively ask a MCQ . Continue it until the Student answers correctly . Then come back to next concept , until the same way you finish . Finish all the 3 Copncepts the same style . Lastly give 5 Summary High Yield facts that the Student need to remeber for the NEETPG Exam . During the converstion , when student asks any Question , answer it and continue the flow of the 3 Concepts based Conversation . Dont move conersation without student answer your question and you check his answer and understanding and based that dialog by dialog of Teacher and Student you progress.When the student answers any of the questions asked by you wrong , then after explainning , when you ask once more , dont ask same question that he answered wront  but a different recursive question to check weather he understood the clarification you gave.

CRITICAL CONVERSATION RULES:

• When you ask an MCQ and wait for a response, the student may:
  (a) answer the MCQ, OR
  (b) ask a related or unrelated question instead of answering.

• If the student ASKS A QUESTION (instead of answering):
  - Answer the student's question clearly and concisely.
  - Do NOT evaluate correctness.
  - Do NOT mark the MCQ as correct or wrong.
  - After answering the question, RE-ASK the SAME MCQ.
  - End again with [STUDENT_REPLY_REQUIRED].

• If the student ANSWERS the MCQ:
  - Evaluate correctness strictly.
  - If correct → respond with [FEEDBACK_CORRECT].
  - If wrong → respond with [FEEDBACK_WRONG] followed by [CLARIFICATION].
  - After clarification, ask a DIFFERENT MCQ to recheck understanding.

• NEVER ignore a student message.
• NEVER respond with empty output.
• NEVER move forward without explicitly closing the loop on the pending MCQ.

OUTPUT FORMAT RULES:
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
            ]
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


# ───────────────────────────────────────────────
# CONTINUE CHAT (STUDENT → MENTOR) — STREAMING
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

    gpt_messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if mcq_context:
        gpt_messages.append({"role": "system", "content": mcq_context})

    gpt_messages.extend(normalize_dialogs(dialogs))

    # 🔧 SURGICAL CHANGE — ONLY CHANGE IN ENTIRE FILE
    gpt_messages.append({
        "role": "system",
        "content": f"""
The student has responded with the following message:

\"\"\"{student_message}\"\"\"

IMPORTANT:
• This message may be an MCQ answer (letter OR free text) OR a question.
• YOU must decide which it is.
• If it is a QUESTION:
    - Answer it clearly.
    - Re-ask the SAME MCQ.
    - End with [STUDENT_REPLY_REQUIRED].
• If it is an ANSWER:
    - Evaluate correctness strictly.
    - Follow all MCQ rules.
• NEVER return empty output.
• NEVER skip semantic blocks.
• NEVER break the MCQ loop.
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
            from gpt_utils import stream_chat_with_gpt
            for token in stream_chat_with_gpt(gpt_messages):
                full_reply += token
                yield token
        finally:
            elapsed = round(time.time() - start_time, 2)

            prev_block = tutor_state.get("last_block")
            last_block = detect_last_block(full_reply)

            if not full_reply.strip():
                logger.error(
                    "[ASK_PARAGRAPH][GPT_EMPTY_REPLY] last_block=%s student_msg='%s'",
                    prev_block,
                    student_message,
                )

            if last_block != "[STUDENT_REPLY_REQUIRED]":
                logger.warning(
                    "[ASK_PARAGRAPH][MCQ_LOOP_BREAK] Expected STUDENT_REPLY_REQUIRED, got=%s",
                    last_block,
                )

            logger.info(
                "[ASK_PARAGRAPH][BLOCK_TRANSITION] %s → %s",
                prev_block,
                last_block,
            )

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
                "current_concept": tutor_state.get("concept"),
            })

            suggestions = generate_suggestions(state)

            logger.info(
                "[ASK_PARAGRAPH][SUGGESTIONS] ids=%s",
                [s["id"] for s in suggestions],
            )

            supabase.table("student_mcq_session").update(
                {"next_suggestions": suggestions}
            ).eq("student_id", student_id).eq("mcq_id", mcq_id).execute()

    return StreamingResponse(
        event_generator(),
        media_type="text/plain"
    )
