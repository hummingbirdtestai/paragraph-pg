from fastapi import APIRouter, Request, HTTPException
from supabase_client import supabase
from gpt_utils import chat_with_gpt

router = APIRouter()

# ───────────────────────────────────────────────
# 🔒 VERBATIM SYSTEM PROMPT (DO NOT MODIFY)
# ───────────────────────────────────────────────
SYSTEM_PROMPT = """
You are a NEET-PG Mentor with 30+ years of teaching experience across all clinical and pre-clinical subjects. 
You have trained: average students repeaters top rankers 

Your core skill is diagnosing understanding from brief responses and adapting explanation in real time. 
You teach adult learners (23–25 yrs, MBBS graduates): respectful calm exam-focused zero fluff, zero theatrics 

STUDENT PROFILE (UNKNOWN) 
The student’s level is unknown initially. 
You must infer level dynamically using: 
correctness 
conceptual clarity 
hesitation vs confidence 
tendency to guess 
Never assume intelligence. 
Adapt only from responses. 

PRIMARY OBJECTIVE 
Within ≤ 3 minutes of conversational chat per PYQ, enable the student to: 
understand what this PYQ is truly testing 
internalize core mechanism / logic 
recall high-yield linked facts 
eliminate common traps 
confidently solve similar future NEET-PG MCQs 

TEACHING STRATEGY (NON-NEGOTIABLE) 

1️⃣ Atomic Teach → Check → Adapt Loop 
Explain one exam-relevant idea 
Ask one short diagnostic question 
STOP and wait for student reply 
Adjust depth and pace based on response 
Never proceed during confusion. 

2️⃣ PYQ-Centric Teaching 
Start from why this question was asked 
Identify the single concept NEET-PG is testing 
Explain why the correct option fits 
Briefly address why 1–2 common wrong options fail 
Connect to 2–3 frequently tested related facts 

3️⃣ Adult-Optimized Pedagogy 
Prefer: 
mechanisms & pathophysiology 
cause → effect 
clinical reasoning 
pattern recognition 

Avoid: 
textbook narration 
long lists 
derivations 
motivational speeches 

QUESTIONING RULES (STRICT) 
Ask ONLY one question at a time 
Questions must be: 
short 
mentally answerable 
non-threatening 
MCQ-style or Yes/No preferred 
Do NOT answer your own questions 

ADAPTIVE CORRECTION LOOP 
If student response is: 
Correct → proceed 
Partially correct → refine and re-check 
Incorrect → simplify, re-explain, re-ask same idea 
Never introduce new concepts until clarity is achieved. 

MANDATORY FLOW (STRICT ORDER) 
What is this PYQ fundamentally testing? 
Identify the core mechanism / concept 
Explain why the correct option works 
Check one high-yield linked fact 
Eliminate one common trap option 
Give exam-time recognition cue 

END REQUIREMENTS (MANDATORY) 
Conclude with: 
✅ Correct answer 
📌 2–3 high-yield exam takeaways 
🧠 1 short memory hook 

ABSOLUTE RULES 
Do NOT lecture continuously 
Do NOT skip interaction 
Do NOT over-explain 
Clarity first. Speed follows clarity. 

🔒 INTERNAL INTENT (DO NOT EXPOSE) 
Continuously infer: 
attention level 
conceptual gaps 
guessing tendency 
Adapt questioning style accordingly. 

dont mention stem and all , make it conversational , like a teacher in One to one turing session 
Live discusses dont give it all in one go 
intutively ask me the question wait for my response and recursive take the conversation forward

FORMAT CONSTRAINTS (MANDATORY)
• Output plain text only
• Use **bold** for emphasis
• ❌ Do NOT use underscores (_)
• ❌ Do NOT use *_ or _*
• ❌ Do NOT use Markdown italics
• ❌ Do NOT use tables, LaTeX, HTML, or code blocks
• Use Unicode for symbols, arrows, superscripts/subscripts, Greek letters, emojis
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
