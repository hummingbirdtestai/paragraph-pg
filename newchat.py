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
# 🔒 VERBATIM SYSTEM PROMPT (DO NOT MODIFY)
# ───────────────────────────────────────────────
SYSTEM_PROMPT = """
You are 30 Years Experienced NEETPG Teacher and AI  Mentor to tutor a NEETPG Aspirant the concepts needed to answer this MCQ . Everu MCQ will have 3 Concepts recursively lined that the Student should Master  in order to succesfully answer he MCQ . Make it purely conversational , where you explain one concept , like you do in a Class , and ask a MCQ and wait for Student to answer . If the student answer is WRONG , UNDERSTAND HIS lEARNING GAP AND EXPLAIN to fill the Gap and once more recursively ask a MCQ . Continue it until the Student answers correctly . Then come back to next concept , until the same way you finish . Finish all the 3 Copncepts the same style . Lastly give 5 Summary High Yield facts that the Student need to remeber for the NEETPG Exam . During the converstion , when student asks any Question , answer it and continue the flow of the 3 Concepts based Conversation . Dont move conersation without student answer your question and you check his answer and understanding and based that dialog by dialog of Teacher and Student you progress.When the student answers any of the questions asked by you wrong , then after explainning , when you ask once more , dont ask same question that he answered wront  but a different recursive question to check weather he understood the clarification you gave.

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

    # 1️⃣ Ask GPT for FIRST mentor response
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

    # 2️⃣ Persist initial dialog
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
        f"[ASK_PARAGRAPH][CHAT] student_id={student_id} mcq_id={mcq_id} "
        f"message_len={len(student_message or '')}"
    )

    # 1️⃣ Load FULL session
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

    logger.info(
        f"[ASK_PARAGRAPH][STATE] last_block={tutor_state.get('last_block')} "
        f"turns={tutor_state.get('turns')}"
    )

    # 🚨 ENFORCEMENT: prevent skipping mentor
    if tutor_state.get("last_block") == "[STUDENT_REPLY_REQUIRED]":
        if not student_message or not student_message.strip():
            logger.warning(
                f"[ASK_PARAGRAPH][BLOCKED] Empty student reply blocked"
            )
            raise HTTPException(
                status_code=409,
                detail="Student response required before proceeding"
            )

    # 2️⃣ Extract MCQ payload
    mcq_payload = None
    for d in dialogs:
        if d["role"] == "assistant" and isinstance(d.get("mcq_payload"), dict):
            mcq_payload = d["mcq_payload"]
            break

    if mcq_payload:
        logger.info("[ASK_PARAGRAPH][MCQ] MCQ context restored")
    else:
        logger.warning("[ASK_PARAGRAPH][MCQ] MCQ payload missing")

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

    # 3️⃣ Build GPT messages
    gpt_messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if mcq_context:
        gpt_messages.append({"role": "system", "content": mcq_context})

    for d in dialogs:
        gpt_messages.append({
            "role": "assistant" if d["role"] == "assistant" else "user",
            "content": d["content"]
        })

    gpt_messages.append({"role": "user", "content": student_message})

    logger.info(
        f"[ASK_PARAGRAPH][GPT] Replaying {len(gpt_messages)} messages"
    )

    # 4️⃣ STREAMING GENERATOR
    def event_generator():
        full_reply = ""

        try:
            from gpt_utils import stream_chat_with_gpt

            for token in stream_chat_with_gpt(gpt_messages):
                full_reply += token
                yield token

        finally:
            elapsed = round(time.time() - start_time, 2)

            # 🧠 Semantic block detection
            last_block = detect_last_block(full_reply)

            logger.info(
                f"[ASK_PARAGRAPH][GPT_DONE] chars={len(full_reply)} "
                f"last_block={last_block} time={elapsed}s"
            )

            tutor_state["last_block"] = last_block
            tutor_state["turns"] = (tutor_state.get("turns", 0) or 0) + 1

            # 💾 Persist dialogs + tutor_state
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

            logger.info(
                f"[ASK_PARAGRAPH][DB] Dialogs persisted. turns={tutor_state['turns']}"
            )

            # 🧠 Build state for suggestions
            session_for_state = {
                "dialogs": dialogs + [
                    {"role": "student", "content": student_message},
                    {"role": "assistant", "content": full_reply},
                ],
                "current_concept": tutor_state.get("concept"),
            }

            state = extract_state(session_for_state)
            suggestions = generate_suggestions(state)

            supabase.table("student_mcq_session").update(
                {"next_suggestions": suggestions}
            ).eq("student_id", student_id).eq("mcq_id", mcq_id).execute()

            logger.info(
                f"[ASK_PARAGRAPH][SUGGESTIONS] generated={len(suggestions)}"
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/plain"
    )
