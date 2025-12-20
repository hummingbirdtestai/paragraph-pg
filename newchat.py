from fastapi import APIRouter, Request, HTTPException
from supabase_client import supabase
from gpt_utils import chat_with_gpt
from fastapi.responses import StreamingResponse

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

    # 1️⃣ Ask GPT for FIRST mentor question
    mentor_reply = chat_with_gpt(
        SYSTEM_PROMPT,
        [
            {
                "role": "user",
                "content": f"""
Here is the MCQ the student is asking about:

{mcq_payload}

Begin the discussion.
"""
            }
        ]
    )

    # 2️⃣ Persist via RPC (system + assistant)
    rpc = supabase.rpc(
        "upsert_mcq_session_v11",
        { 
            "p_student_id": student_id,
            "p_mcq_id": mcq_id,
            "p_mcq_payload": mcq_payload,
            "p_new_dialogs": [
                {
                    "role": "assistant",
                    "content": mentor_reply
                }
            ]
        }
    ).execute()

    if not rpc.data:
        raise HTTPException(status_code=500, detail="Failed to start MCQ session")

    return rpc.data[0]


# ───────────────────────────────────────────────
# 🔥 LOAD EXISTING SESSION
# ───────────────────────────────────────────────
@router.post("/session")
async def get_session(request: Request):
    data = await request.json()
    session_id = data["session_id"]

    row = (
        supabase.table("student_mcq_session")
        .select("id, dialogs")
        .eq("id", session_id)
        .limit(1)
        .execute()
    )

    if not row.data:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": row.data[0]["id"],
        "dialogs": row.data[0]["dialogs"],
    }

# ───────────────────────────────────────────────
# CONTINUE CHAT (STUDENT → MENTOR) — STREAMING
# ───────────────────────────────────────────────
@router.post("/chat")
async def continue_chat(request: Request):
    data = await request.json()

    student_id = data["student_id"]
    mcq_id = data["mcq_id"]
    student_message = data["message"]

    # 1️⃣ Load FULL session (single source of truth)
    row = (
        supabase.table("student_mcq_session")
        .select("dialogs")
        .eq("student_id", student_id)
        .eq("mcq_id", mcq_id)
        .single()
        .execute()
    )

    if not row.data:
        raise HTTPException(status_code=404, detail="Session not found")

    dialogs = row.data["dialogs"]

    # 2️⃣ Extract MCQ payload (optional safety)
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

    # 3️⃣ Rebuild GPT messages (ChatGPT-style)
    gpt_messages = []

    gpt_messages.append({
        "role": "system",
        "content": SYSTEM_PROMPT
    })

    if mcq_context:
        gpt_messages.append({
            "role": "system",
            "content": mcq_context
        })

    for d in dialogs:
        role = "assistant" if d["role"] == "assistant" else "user"
        gpt_messages.append({
            "role": role,
            "content": d["content"]
        })

    gpt_messages.append({
        "role": "user",
        "content": student_message
    })

    # 4️⃣ STREAMING GENERATOR
    def event_generator():
        full_reply = ""

        try:
            from gpt_utils import stream_chat_with_gpt

            for token in stream_chat_with_gpt(gpt_messages):
                full_reply += token
                yield token

        finally:
            # 5️⃣ Persist AFTER stream completes (critical)
            supabase.rpc(
                "upsert_mcq_session_v11",
                {
                    "p_student_id": student_id,
                    "p_mcq_id": mcq_id,
                    "p_mcq_payload": {},
                    "p_new_dialogs": [
                        {
                            "role": "student",
                            "content": student_message
                        },
                        {
                            "role": "assistant",
                            "content": full_reply
                        }
                    ]
                }
            ).execute()

    return StreamingResponse(
        event_generator(),
        media_type="text/plain"
    )
