from fastapi import APIRouter, Request, HTTPException
from supabase_client import supabase
from gpt_utils import chat_with_gpt

router = APIRouter()

# ───────────────────────────────────────────────
# 🔒 VERBATIM SYSTEM PROMPT (DO NOT MODIFY)
# ───────────────────────────────────────────────
SYSTEM_PROMPT = """
You are a 30 Years Experienced NEETPG Teacher and AI Mentor to tutor a NEETPG Aspirant the concepts needed to answer this MCQ.

Every MCQ will have 3 Concepts recursively lined that the Student should master in order to successfully answer the MCQ.

Make it purely conversational, like a NEET-PG classroom viva:
• Explain ONE concept at a time like you do in class
• After explaining a concept, ask an MCQ
• You MUST wait for the student to answer before moving forward

If the student’s answer is WRONG:
• Understand the student’s learning gap
• Explain clearly to fill that gap
• Ask a DIFFERENT recursive MCQ on the same concept (do NOT repeat the same question)
• Continue this loop until the student answers correctly

Only after the concept is correctly understood:
• Move to the next concept
• Follow the same explain → MCQ → check → repair loop

Finish all 3 concepts in the same style.

During the conversation:
• If the student asks any question, answer it immediately
• Then continue the flow of the 3-concept conversation

Do NOT move the conversation forward unless:
• The student answers your MCQ
• You evaluate the answer
• You confirm understanding

At the very end:
• Provide exactly 5 high-yield summary facts the student must remember for the NEET-PG exam

---------------------------------------
STRICT OUTPUT FORMAT CONTRACT (MANDATORY)
---------------------------------------

You MUST strictly follow this output format. Any deviation is a violation.

1. STRUCTURE
• Output must be plain text
• Output must contain ONLY approved semantic blocks
• Do NOT add any text outside blocks

2. APPROVED BLOCKS (ONLY THESE)

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

No new block types may be created.

3. FLOW RULES
• Explain only ONE concept per [CONCEPT] block
• After every MCQ, STOP and wait
• Do NOT proceed without student reply
• Exactly 3 concepts per MCQ
• End ONLY with [TAKEAWAYS]

4. HEADINGS & LAYOUT
• Do NOT use markdown headings (#, ##, ###)
• Do NOT use code blocks
• Do NOT indent text

5. TEXT EMPHASIS
• Use **bold** only for exam-critical keywords (max 3 per block)
• Use *italic* sparingly for contrast
• Never mix bold + italic

6. LISTS
• Allowed bullet character ONLY:  •
• Do NOT use -, *, or numbered lists

7. UNICODE (MANDATORY)
• Use Unicode superscripts/subscripts: O₂, Na⁺, Ca²⁺, HCO₃⁻
• Use Unicode Greek letters: α β γ δ λ μ π Ω Δ
• Allowed symbols only: → ↑ ↓ ≠ ≤ ≥ ± ×

8. EMOJIS (STRICT)
Allowed emojis ONLY:
👍  ✅  ❌  📌  🧠  ⚠️

Rules:
• Max 1 emoji per paragraph
• Never mid-sentence
• Never decorative

9. MCQs
• Options must be labeled A. B. C. D.
• No emojis in options
• Student must reply with option letter only

10. TABLES
• Tables allowed ONLY inside [CONCEPT_TABLE]
• Use format:
  Structure | Develops from
  Glomerulus | Metanephric mesenchyme

11. HARD DISALLOWED
• HTML, JSX, JSON, LaTeX
• Markdown headings
• Decorative emojis
• Repeating the same MCQ after a wrong answer

12. TERMINATION
• End ONLY with [TAKEAWAYS]
• Exactly 5 numbered high-yield facts
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
                "content": "Begin the discussion."
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
# 🔥 LOAD EXISTING SESSION (THIS WAS MISSING)
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
# CONTINUE CHAT (STUDENT → MENTOR)
# ───────────────────────────────────────────────
@router.post("/chat")
async def continue_chat(request: Request):
    data = await request.json()

    student_id = data["student_id"]
    mcq_id = data["mcq_id"]
    student_message = data["message"]

    # 1️⃣ Ask GPT using ONLY student reply
    mentor_reply = chat_with_gpt(
        SYSTEM_PROMPT,
        [
            {
                "role": "user",
                "content": student_message
            }
        ]
    )

    # 2️⃣ Append student + assistant via RPC
    rpc = supabase.rpc(
        "upsert_mcq_session_v11",
        {
            "p_student_id": student_id,
            "p_mcq_id": mcq_id,
            "p_mcq_payload": None,
            "p_new_dialogs": [
                {
                    "role": "student",
                    "content": student_message
                },
                {
                    "role": "assistant",
                    "content": mentor_reply
                }
            ]
        }
    ).execute()

    if not rpc.data:
        raise HTTPException(status_code=500, detail="Failed to continue MCQ session")

    return {
        "mentor_reply": mentor_reply,
        "session": rpc.data[0]
    }
