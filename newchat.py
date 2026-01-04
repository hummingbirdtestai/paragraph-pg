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
You are a senior NEET-PG mentor using DIAGNOSTIC PEDAGOGY.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CORE GOAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Your job is NOT to finish MCQs.
Your job is to IDENTIFY and FIX the deepest missing prerequisite.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COGNITIVE LADDER (TOP → BOTTOM)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Recall
2. Understanding
3. Application
4. Comparison
5. Integration

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RECURSIVE RULES (NON-NEGOTIABLE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• NEVER repeat or paraphrase an MCQ
• Each WRONG answer means a DEEPER prerequisite is missing
• Each recursive MCQ MUST be simpler and more fundamental
• Difficulty always goes DOWN, never sideways
• Ask exactly ONE MCQ at a time

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHEN STUDENT ASKS A QUESTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Answer briefly (2–3 lines)
• Do NOT judge correctness
• Do NOT advance concepts
• Re-ask the SAME MCQ verbatim
• End with [STUDENT_REPLY_REQUIRED]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHEN STUDENT ANSWERS WRONG
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Start with: "You are incorrect."
• Identify the learning gap
• Explain the missing prerequisite (max 3 lines)
• Mention ONE common NEET-PG confusion
• Give ONE simple memory hook
• Generate a NEW MCQ on ONLY that prerequisite
• End with [STUDENT_REPLY_REQUIRED]

Use tags EXACTLY:

[GAP]:
[EXPLANATION]:
[COMMON_CONFUSION]:
[MEMORY_HOOK]:
[SUB_CONCEPT]:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHEN STUDENT ANSWERS CORRECTLY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Respond ONLY with:
  [FEEDBACK_CORRECT]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MCQ FORMAT (STRICT)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[MCQ]
Question: <text>
A. <option>
B. <option>
C. <option>
D. <option>
Correct: <A|B|C|D>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Plain text only
• No emojis
• No extra commentary
• No deviation from format
"""



import re

def parse_mcq_from_text(text: str):
    try:
        q_match = re.search(r"Question:\s*(.*)", text)
        options = re.findall(r"[A-D]\.\s*(.*)", text)
        correct_match = re.search(r"Correct:\s*([A-D])", text)

        if not q_match or not correct_match or len(options) != 4:
            return None

        return {
            "question": q_match.group(1).strip(),
            "options": options,
            "correct_answer": correct_match.group(1).strip()
        }
    except Exception:
        return None
# 🔒 ADD THIS RIGHT HERE
def normalize_question(q: str) -> str:
    """
    Normalizes MCQ questions to detect paraphrased repeats.
    """
    return re.sub(r"\W+", "", q.lower())

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

    # ✅ FIXED tutor_state (MINIMAL additions only)
    tutor_state = {
        "status": "active",
        "awaiting_answer": True,
        "recursion_depth": 0,
        "max_depth": 10,
        "turns": 0,

        # ✅ REQUIRED for diagnostic recursion
        "active_gap": "root concept",
        "active_concept": "root concept",

        "current_mcq": {
            "id": "root",
            "question": parsed["question"],
            "options": parsed["options"],
            "correct_answer": parsed["correct_answer"]
        },

        # ✅ CRITICAL: seed history with root MCQ
        "mcq_history": [
            {
                "question": parsed["question"],
                "gap": "root",
                "concept": "root",
                "level": 0
            }
        ]
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
# ───────────────────────────────────────────────
# CONTINUE CHAT (STUDENT → MENTOR) — FIXED PEDAGOGY
# ───────────────────────────────────────────────
@router.post("/chat")
async def continue_chat(request: Request):
    data = await request.json()

    student_id = data["student_id"]
    mcq_id = data["mcq_id"]
    message = data.get("message", "").strip()

    # ─────────────────────────────────────────
    # LOAD SESSION
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
        raise HTTPException(404, "Session not found")

    dialogs = row.data["dialogs"] or []
    tutor_state = row.data["tutor_state"] or {}

    tutor_state.setdefault("recursion_depth", 0)
    tutor_state.setdefault("max_depth", 8)
    tutor_state.setdefault("mcq_history", [])
    tutor_state.setdefault("active_gap", "core concept")
    tutor_state.setdefault("active_concept", "base concept")
    tutor_state.setdefault("turns", 0)

    current_mcq = tutor_state.get("current_mcq")
    if not current_mcq:
        raise HTTPException(500, "Corrupt session: missing current MCQ")

    # 🛑 STOP AFTER MASTERY
    if tutor_state.get("status") == "mastered":
        return StreamingResponse(
            iter(["[SESSION_COMPLETED]"]),
            media_type="text/plain"
        )

    # 🛑 SAFETY: MAX DEPTH
    if tutor_state["recursion_depth"] >= tutor_state["max_depth"]:
        final = (
            "You are incorrect.\n"
            "[CORE_CONCEPT]: This topic requires revision from first principles.\n"
            "[GAP]: Foundational understanding missing.\n"
            "[COMMON_CONFUSION]: Pattern recognition without concept clarity.\n"
            "[MEMORY_HOOK]: Definition before application.\n"
            "[SUB_CONCEPT]: Fundamental principles"
        )
        return StreamingResponse(iter([final]), media_type="text/plain")

    # ─────────────────────────────────────────
    # DETERMINE MESSAGE TYPE
    # ─────────────────────────────────────────
    is_answer = is_mcq_answer(message)

    # 🟡 STUDENT ASKED A QUESTION
    if not is_answer:
        reply = chat_with_gpt([
            {"role": "system", "content": SYSTEM_PROMPT},
            *get_active_mcq_context(dialogs),
            {
                "role": "user",
                "content": f"""
The student is asking a clarification.

Question:
{message}

Answer briefly, then re-ask the SAME MCQ verbatim.
End with [STUDENT_REPLY_REQUIRED].
"""
            }
        ])

        final_reply = reply

    # 🔵 STUDENT ANSWERED
    else:
        student_ans = message.strip().upper()[:1]
        correct_ans = current_mcq["correct_answer"].upper()

        # ✅ CORRECT ANSWER (BACKEND DECIDES)
        if student_ans == correct_ans:
            tutor_state["status"] = "mastered"
            reinforcement = generate_reinforcement(current_mcq)
            final_reply = "[FEEDBACK_CORRECT]\n\n" + reinforcement

        # ❌ WRONG ANSWER — FIXED PEDAGOGY
        else:
            tutor_state["recursion_depth"] += 1

            # ✅ BACKEND-CONTROLLED INTRO (ONCE ONLY)
            intro = (
                "You are incorrect.\n"
                f"The correct answer is {correct_ans}.\n\n"
            )

            reply = chat_with_gpt([
                {
                    "role": "system",
                    "content": """
You are a senior NEET-PG mentor.

The student answered an MCQ incorrectly.

Your job is TEACHING FIRST, DIAGNOSIS SECOND.

━━━━━━━━━━━━━━━━━━━━━━
STRICT ORDER (MANDATORY)
━━━━━━━━━━━━━━━━━━━━━━

1. Explain the CORE CONCEPT in detail (5–8 lines, exam-oriented)
2. Explain WHY the student made this mistake
3. Identify the specific missing prerequisite
4. Give ONE memory hook
5. Generate ONE simpler MCQ on that missing prerequisite
6. End with [STUDENT_REPLY_REQUIRED]

━━━━━━━━━━━━━━━━━━━━━━
FORMAT (STRICT)
━━━━━━━━━━━━━━━━━━━━━━

[CORE_CONCEPT]:
<detailed explanation>

[GAP]:
<what exactly is missing>

[COMMON_CONFUSION]:
<why students mix this up>

[MEMORY_HOOK]:
<short hook>

[SUB_CONCEPT]:
<name>

[MCQ]
Question: <text>
A. <option>
B. <option>
C. <option>
D. <option>
Correct: <A|B|C|D>

━━━━━━━━━━━━━━━━━━━━━━
RULES
━━━━━━━━━━━━━━━━━━━━━━

• Do NOT repeat “You are incorrect”
• Do NOT reveal the correct answer
• Do NOT mention recursion or pedagogy
• Plain text only
"""
                },
                *get_active_mcq_context(dialogs),
                {
                    "role": "user",
                    "content": f"""
Student answer: {student_ans}
Correct answer: {correct_ans}

Teach properly, then diagnose, then ask next MCQ.
"""
                }
            ])

            parsed = parse_mcq_from_text(reply)

            if not parsed:
                final_reply = intro + (
                    "[CORE_CONCEPT]: Revise the fundamental concept carefully.\n"
                    "[GAP]: Conceptual misunderstanding.\n"
                    "[COMMON_CONFUSION]: Similar terms confused.\n"
                    "[MEMORY_HOOK]: One concept → one definition.\n"
                    "[SUB_CONCEPT]: Foundational concept"
                )
            else:
                # 🔒 HARD ANTI-REPEAT
                new_q = normalize_question(parsed["question"])
                for old in tutor_state["mcq_history"]:
                    if normalize_question(old["question"]) == new_q:
                        tutor_state["recursion_depth"] += 1
                        tutor_state["active_gap"] = f"deeper prerequisite of {tutor_state['active_gap']}"
                        tutor_state["active_concept"] = f"sub-concept of {tutor_state['active_concept']}"
                        return StreamingResponse(
                            iter(["[SYSTEM_RETRY]"]),
                            media_type="text/plain"
                        )

                tutor_state["mcq_history"].append({
                    "question": parsed["question"],
                    "gap": tutor_state["active_gap"],
                    "concept": tutor_state["active_concept"],
                    "level": tutor_state["recursion_depth"]
                })

                tutor_state["current_mcq"] = parsed
                final_reply = intro + reply

    # ─────────────────────────────────────────
    # UPDATE STATE + DIALOGS
    # ─────────────────────────────────────────
    tutor_state["turns"] += 1

    supabase.rpc(
        "upsert_mcq_session_v11",
        {
            "p_student_id": student_id,
            "p_mcq_id": mcq_id,
            "p_mcq_payload": {},
            "p_new_dialogs": [
                {"role": "student", "content": message},
                {"role": "assistant", "content": final_reply},
            ],
            "p_tutor_state": tutor_state,
        }
    ).execute()

    return StreamingResponse(
        iter([final_reply]),
        media_type="text/plain"
    )



