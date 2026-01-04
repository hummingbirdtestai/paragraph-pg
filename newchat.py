# ───────────────────────────────────────────────
# PART 1 — Imports & Logger
# ───────────────────────────────────────────────

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
import logging, time, json

from supabase_client import supabase
from gpt_utils import chat_with_gpt

router = APIRouter()

logger = logging.getLogger("ask_paragraph")
logger.setLevel(logging.INFO)


def log_time(tag, start):
    logger.info("[ASK_PARAGRAPH][TIME][%s] %.2fs", tag, time.time() - start)


def safe_block_detect(text: str | None):
    if not text:
        return None
    for b in [
        "[FEEDBACK_CORRECT]",
        "[FEEDBACK_WRONG]",
        "[STUDENT_REPLY_REQUIRED]",
        "[FINAL_ANSWER]"
    ]:
        if b in text:
            return b
    return None

BEFORE STARTING ANY TEACHING:

You MUST FIRST extract EXACTLY **3 core concepts** required to solve the given MCQ.

• These must be prerequisite concepts necessary to solve the MCQ  
• They must be ordered in a dependency chain  
• Do NOT explain them yet  
• Do NOT ask any MCQ yet  

Output them ONCE in the following block ONLY:

[CONCEPT_LIST]
1. <Concept 1>
2. <Concept 2>
3. <Concept 3>

After outputting [CONCEPT_LIST]:
• Say: "I will start with Concept 1."
• Then proceed with the teaching rules EXACTLY as defined below.
• From this point onward, NEVER re-list the concepts again.

────────────────────────────────────────────────────────

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

# ───────────────────────────────────────────────
# PART 3 — START SESSION
# ───────────────────────────────────────────────

@router.post("/start")
async def start_session(request: Request):
    t0 = time.time()
    data = await request.json()

    student_id = data["student_id"]
    mcq_id = data["mcq_id"]
    mcq_payload = data["mcq_payload"]

    logger.info("[START] student=%s mcq=%s", student_id, mcq_id)

    # STEP 1: Ask GPT ONLY to extract 3 concepts
    concept_prompt = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"""
From the following MCQ, list EXACTLY 3 core concepts
required to answer it. Return as JSON list only.

MCQ:
{mcq_payload}
"""}
    ]

    raw = chat_with_gpt(concept_prompt)
    concepts = json.loads(raw)

    tutor_state = {
        "phase": "concept_teaching",
        "concept_pointer": 0,
        "recursion_depth": 0,
        "awaiting_mcq": True,
        "last_block": None,
        "turns": 0,
        "concepts": [
            {"title": c, "status": "pending"} for c in concepts
        ]
    }

    # STEP 2: Start first concept teaching
    mentor_reply = chat_with_gpt([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"""
Teach this concept:
{concepts[0]}

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

    log_time("START", t0)
    return {"status": "started"}

# ───────────────────────────────────────────────
# PART 4 — CHAT LOOP (NO HALLUCINATION)
# ───────────────────────────────────────────────

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

    concept_idx = tutor_state["concept_pointer"]
    concept = tutor_state["concepts"][concept_idx]["title"]

    gpt_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *dialogs[-4:],
        {"role": "user", "content": f"""
Current concept: {concept}

Student said:
\"\"\"{student_msg}\"\"\"
"""}
    ]

    def stream():
        full = chat_with_gpt(gpt_messages)
        yield full

        block = safe_block_detect(full)

        if block == "[FEEDBACK_CORRECT]":
            tutor_state["concepts"][concept_idx]["status"] = "mastered"
            tutor_state["concept_pointer"] += 1
            tutor_state["recursion_depth"] = 0

            if tutor_state["concept_pointer"] == 3:
                tutor_state["phase"] = "final"
        elif block == "[FEEDBACK_WRONG]":
            tutor_state["recursion_depth"] += 1

        tutor_state["last_block"] = block
        tutor_state["turns"] += 1

        supabase.rpc("upsert_mcq_session_v11", {
            "p_student_id": student_id,
            "p_mcq_id": mcq_id,
            "p_mcq_payload": {},
            "p_new_dialogs": [
                {"role": "student", "content": student_msg},
                {"role": "assistant", "content": full}
            ],
            "p_tutor_state": tutor_state
        }).execute()

        log_time("CHAT", t0)

    return StreamingResponse(stream(), media_type="text/plain")

# ───────────────────────────────────────────────
# PART 5 — FINAL SUMMARY
# ───────────────────────────────────────────────

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
