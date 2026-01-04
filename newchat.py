from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
import logging, time, json

from supabase_client import supabase
from gpt_utils import chat_with_gpt

router = APIRouter()

logger = logging.getLogger("ask_paragraph")
logger.setLevel(logging.INFO)


def log_time(tag: str, start: float):
    logger.info("[ASK_PARAGRAPH][TIME][%s] %.2fs", tag, time.time() - start)


def safe_block_detect(text: str | None):
    if not text:
        return None
    for b in (
        "[FEEDBACK_CORRECT]",
        "[FEEDBACK_WRONG]",
        "[STUDENT_REPLY_REQUIRED]",
        "[FINAL_ANSWER]",
    ):
        if b in text:
            return b
    return None

SYSTEM_PROMPT = """
BEFORE STARTING ANY TEACHING:

You MUST FIRST extract EXACTLY **3 core concepts** required to solve the given MCQ.

• These must be prerequisite concepts necessary to solve the MCQ
• They must be ordered in a dependency chain
• Do NOT explain them yet
• Do NOT ask any MCQ yet

────────────────────────────────────────────────

You are a 30 Years Experienced NEETPG Teacher and AI Mentor tutoring a NEETPG aspirant to MASTER the concepts required to solve the given MCQ.

Each MCQ has EXACTLY **3 core concepts** arranged in a dependency chain:
Concept 1 → Concept 2 → Concept 3

Your job is to ensure **true mastery** of each concept using a **depth-first recursive MCQ teaching strategy** before moving to the next concept.

────────────────────────────────
CORE TEACHING STRATEGY (MANDATORY)
────────────────────────────────

• Teaching must be **purely MCQ-driven**
• NEVER switch to theory-only questioning
• NEVER ask open-ended questions
• EVERY checkpoint must be an MCQ

For EACH concept:

1️⃣ Explain briefly  
2️⃣ Ask an MCQ testing ONLY that concept  
3️⃣ STOP and wait

────────────────────────────────
RECURSIVE MASTERY RULE
────────────────────────────────

CORRECT → move forward  
WRONG → identify gap → explain → NEW MCQ → repeat until correct  

────────────────────────────────
STUDENT QUESTION HANDLING
────────────────────────────────

If student asks a question:
• Answer briefly
• Do NOT evaluate
• Re-ask SAME MCQ
• End with [STUDENT_REPLY_REQUIRED]

────────────────────────────────
FINAL PHASE
────────────────────────────────

After all 3 concepts:
1️⃣ [FINAL_ANSWER]
2️⃣ [CONCEPT_TABLE]
3️⃣ [TAKEAWAYS] (EXACTLY 5)

────────────────────────────────
OUTPUT FORMAT (STRICT)
────────────────────────────────

Allowed blocks only:
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
"""

@router.post("/start")
async def start_session(request: Request):
    t0 = time.time()
    data = await request.json()

    student_id = data["student_id"]
    mcq_id = data["mcq_id"]
    mcq_payload = data["mcq_payload"]

    logger.info("[START] student=%s mcq=%s", student_id, mcq_id)

    # STEP 1: Extract EXACTLY 3 concepts (backend-authoritative)
    raw = chat_with_gpt([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"""
Extract EXACTLY 3 prerequisite concepts as a JSON array.
No text. No markdown.

MCQ:
{mcq_payload}
"""}
    ])

    try:
        concepts = json.loads(raw)
        if not isinstance(concepts, list) or len(concepts) != 3:
            raise ValueError("Invalid concept list")
    except Exception:
        logger.error("[CONCEPT_EXTRACT_FAIL] raw=%s", raw)
        raise HTTPException(500, "Concept extraction failed")

    tutor_state = {
        "phase": "teaching",
        "concept_pointer": 0,
        "recursion_depth": 0,
        "turns": 0,
        "last_block": None,
        "concepts": [
            {"title": c, "status": "pending"} for c in concepts
        ],
    }

    # STEP 2: Start Concept 1
    mentor_reply = chat_with_gpt([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"""
Start teaching Concept 1:

{concepts[0]}

Explain briefly and ask an MCQ.
"""}
    ])

    supabase.rpc("upsert_mcq_session_v11", {
        "p_student_id": student_id,
        "p_mcq_id": mcq_id,
        "p_mcq_payload": mcq_payload,
        "p_new_dialogs": [{"role": "assistant", "content": mentor_reply}],
        "p_tutor_state": tutor_state,
    }).execute()

    log_time("START", t0)
    return {"status": "started"}

@router.post("/chat")
async def continue_chat(request: Request):
    t0 = time.time()
    data = await request.json()

    student_id = data["student_id"]
    mcq_id = data["mcq_id"]
    student_msg = data["message"]

    row = supabase.table("student_mcq_session") \
        .select("dialogs, tutor_state") \
        .eq("student_id", student_id) \
        .eq("mcq_id", mcq_id) \
        .single().execute()

    dialogs = row.data["dialogs"]
    tutor_state = row.data["tutor_state"]

    idx = tutor_state["concept_pointer"]
    concept = tutor_state["concepts"][idx]["title"]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *dialogs[-4:],
        {"role": "user", "content": f"""
Current concept: {concept}

Student response:
\"\"\"{student_msg}\"\"\"
"""}
    ]

    def stream():
        full = chat_with_gpt(messages)
        yield full

        block = safe_block_detect(full)

        # Student asked a question
        if block is None:
            tutor_state["last_block"] = "[STUDENT_REPLY_REQUIRED]"

        elif block == "[FEEDBACK_CORRECT]":
            tutor_state["concepts"][idx]["status"] = "mastered"
            tutor_state["concept_pointer"] += 1
            tutor_state["recursion_depth"] = 0

        elif block == "[FEEDBACK_WRONG]":
            tutor_state["recursion_depth"] += 1

        if tutor_state["recursion_depth"] > 6:
            tutor_state["recursion_depth"] = 0

        tutor_state["turns"] += 1
        tutor_state["last_block"] = block

        supabase.rpc("upsert_mcq_session_v11", {
            "p_student_id": student_id,
            "p_mcq_id": mcq_id,
            "p_mcq_payload": {},
            "p_new_dialogs": [
                {"role": "student", "content": student_msg},
                {"role": "assistant", "content": full},
            ],
            "p_tutor_state": tutor_state,
        }).execute()

        # Trigger final phase
        if tutor_state["concept_pointer"] == 3:
            final = trigger_final_summary(dialogs)
            yield final

        log_time("CHAT", t0)

    return StreamingResponse(stream(), media_type="text/plain")

def trigger_final_summary(dialogs):
    return chat_with_gpt([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": """
All 3 concepts are mastered.

Now provide:
1. [FINAL_ANSWER]
2. [CONCEPT_TABLE]
3. [TAKEAWAYS] (EXACTLY 5)
"""}
    ])
