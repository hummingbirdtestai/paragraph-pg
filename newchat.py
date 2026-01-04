# NEWCHAT.PY

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
import logging, time, json

from supabase_client import supabase
from gpt_utils import chat_with_gpt

router = APIRouter()
logger = logging.getLogger("ask_paragraph")
logger.setLevel(logging.INFO)

def detect_block(text: str | None):
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

CONCEPT_EXTRACT_PROMPT = """
You are a senior NEET-PG academic expert.

Your task is to identify the MINIMUM prerequisite knowledge
required to solve the given MCQ.

INSTRUCTIONS (STRICT):

• Extract EXACTLY **3 core concepts**
• These must be:
  - Prerequisite concepts (not outcomes or answers)
  - Ordered in a dependency chain (Concept 1 → Concept 2 → Concept 3)
• Concepts must be:
  - Atomic
  - Exam-oriented
  - Conceptual (not procedural steps)
• Do NOT explain anything
• Do NOT ask questions
• Do NOT add commentary
• Do NOT use markdown
• Do NOT include numbering outside JSON

OUTPUT FORMAT (MANDATORY):

Return ONLY a valid JSON array of 3 strings.

Example:
[
  "Concept 1 name",
  "Concept 2 name",
  "Concept 3 name"
]

If unsure, still return the BEST possible 3 concepts
as per NEET-PG standards.

Now analyze the following MCQ:
"""

SYSTEM_PROMPT = """
You are a **30 Years Experienced NEET-PG Teacher and AI Mentor**
tutoring a NEET-PG aspirant to MASTER the concepts required to solve
the given MCQ.

Each MCQ has EXACTLY **3 core concepts** arranged in a dependency chain:
Concept 1 → Concept 2 → Concept 3

Your job is to ensure **true mastery** of each concept using a
**depth-first, recursive, MCQ-driven teaching strategy**
before moving to the next concept.

────────────────────────────────
CORE TEACHING STRATEGY (MANDATORY)
────────────────────────────────

• Teaching must be **purely MCQ-driven**
• NEVER switch to theory-only explanations
• NEVER ask open-ended or descriptive questions
• EVERY checkpoint must be an MCQ

For EACH concept, follow this STRICT loop:

1️⃣ Explain ONE concept briefly (as in a real classroom)
2️⃣ Immediately ask an MCQ that tests ONLY that explained concept
3️⃣ STOP and wait for the student’s response

────────────────────────────────
RECURSIVE MASTERY RULE (CRITICAL)
────────────────────────────────

If the student answers the MCQ:

✅ CORRECT:
• Confirm correctness
• Consider this concept MASTERED
• Move to the NEXT concept in sequence

❌ WRONG:
• Identify the SPECIFIC underlying sub-concept gap
• Explain ONLY that missing sub-concept
• Ask a NEW MCQ testing THIS clarification
• Do NOT repeat the same MCQ
• Continue recursively UNTIL the student answers correctly
• ONLY THEN return to the parent concept and continue

⚠️ Drill DOWN until correctness is achieved  
⚠️ Drill UP only after mastery is proven  

────────────────────────────────
MCQ GENERATION RULES (VERY IMPORTANT)
────────────────────────────────

• Every MCQ must be freshly generated
• NEVER reuse original MCQ options
• NEVER recycle wording from earlier MCQs
• NEVER keep the same 4 options across questions

Each MCQ must:
• Test understanding of the IMMEDIATELY preceding explanation
• Reflect NEET-PG exam style
• Have ONE unambiguous best answer

────────────────────────────────
STUDENT QUESTION HANDLING
────────────────────────────────

If the student ASKS a question:
• Answer it clearly and concisely
• Do NOT evaluate correctness
• Do NOT mark MCQ right or wrong
• RE-ASK the SAME MCQ
• End with [STUDENT_REPLY_REQUIRED]

────────────────────────────────
MCQ EVALUATION RULES
────────────────────────────────

Correct answer →
→ [FEEDBACK_CORRECT]

Wrong answer →
→ [FEEDBACK_WRONG]
→ [CLARIFICATION]
→ Ask a DIFFERENT MCQ

NEVER move forward without closing the MCQ loop.

────────────────────────────────
GLOBAL CONSTRAINTS (NON-NEGOTIABLE)
────────────────────────────────

• NEVER ignore a student message
• NEVER respond with empty output
• NEVER skip MCQ verification
• NEVER summarize early
• NEVER bypass recursion

────────────────────────────────
FINAL PHASE (ONLY AFTER ALL 3 CONCEPTS)
────────────────────────────────

After all 3 concepts are mastered:

1️⃣ [FINAL_ANSWER]
2️⃣ [CONCEPT_TABLE]
3️⃣ [TAKEAWAYS]
   • EXACTLY 5 points
   • Exam-oriented
   • High-yield
   • Memory-anchorable

────────────────────────────────
OUTPUT FORMAT RULES (STRICT)
────────────────────────────────

Use ONLY these blocks:
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

Do NOT invent new blocks.
Do NOT write outside blocks.

────────────────────────────────
TABLE RULES (CRITICAL)
────────────────────────────────

• Valid GitHub Markdown only
• Header row must be followed by |---|
• No blank rows
• No broken tables
"""

@router.post("/start")
async def start_session(request: Request):
    data = await request.json()
    student_id = data["student_id"]
    mcq_id = data["mcq_id"]
    mcq_payload = data["mcq_payload"]

    # 1️⃣ Extract concepts ONCE
    raw = chat_with_gpt([
        {"role": "system", "content": CONCEPT_EXTRACT_PROMPT},
        {"role": "user", "content": str(mcq_payload)}
    ])

    try:
        concepts = json.loads(raw)
        assert isinstance(concepts, list) and len(concepts) == 3
    except Exception:
        raise HTTPException(500, "Concept extraction failed")

    tutor_state = {
        "concepts": [{"title": c, "status": "pending"} for c in concepts],
        "concept_index": 0,
        "recursion_depth": 0,
        "turns": 0,
        "last_block": "[STUDENT_REPLY_REQUIRED]"
    }

    # 2️⃣ Start teaching Concept 1
    mentor_reply = chat_with_gpt([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"""
Here is the MCQ:

{mcq_payload}

Start with Concept 1: {concepts[0]}
Explain briefly and ask an MCQ.
"""}
    ])

    supabase.rpc("upsert_mcq_session_v11", {
        "p_student_id": student_id,
        "p_mcq_id": mcq_id,
        "p_mcq_payload": mcq_payload,
        "p_new_dialogs": [{"role": "assistant", "content": mentor_reply}],
        "p_tutor_state": tutor_state
    }).execute()

    return {"status": "started"}

@router.post("/chat")
async def continue_chat(request: Request):
    data = await request.json()
    student_id = data["student_id"]
    mcq_id = data["mcq_id"]
    student_message = data["message"]

    row = supabase.table("student_mcq_session") \
        .select("dialogs, tutor_state") \
        .eq("student_id", student_id) \
        .eq("mcq_id", mcq_id) \
        .single().execute()

    dialogs = row.data["dialogs"]
    tutor_state = row.data["tutor_state"]

    concept_idx = tutor_state["concept_index"]
    concept = tutor_state["concepts"][concept_idx]["title"]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *dialogs[-4:],
        {"role": "user", "content": f"""
Current concept: {concept}

Student response:
\"\"\"{student_message}\"\"\"
"""}
    ]

    def event_generator():
        reply = chat_with_gpt(messages)
        yield reply  # ✅ SINGLE YIELD ONLY

        block = detect_block(reply)

        if block == "[FEEDBACK_CORRECT]":
            tutor_state["concepts"][concept_idx]["status"] = "mastered"
            tutor_state["concept_index"] += 1
            tutor_state["recursion_depth"] = 0
        elif block == "[FEEDBACK_WRONG]":
            tutor_state["recursion_depth"] += 1

        tutor_state["turns"] += 1
        tutor_state["last_block"] = block

        supabase.rpc("upsert_mcq_session_v11", {
            "p_student_id": student_id,
            "p_mcq_id": mcq_id,
            "p_mcq_payload": {},
            "p_new_dialogs": [
                {"role": "student", "content": student_message},
                {"role": "assistant", "content": reply}
            ],
            "p_tutor_state": tutor_state
        }).execute()

    return StreamingResponse(event_generator(), media_type="text/plain")

@router.post("/final")
async def final_summary(request: Request):
    data = await request.json()
    session_id = data["session_id"]

    row = supabase.table("student_mcq_session") \
        .select("dialogs") \
        .eq("id", session_id) \
        .single().execute()

    final = chat_with_gpt([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": """
All 3 concepts are mastered.
Now provide:
[FINAL_ANSWER]
[CONCEPT_TABLE]
[TAKEAWAYS] (EXACTLY 5)
"""}
    ])

    return final
