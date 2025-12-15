from fastapi import APIRouter, Request
from datetime import datetime
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
# START / RESUME ASK PARAGRAPH SESSION
# ───────────────────────────────────────────────
@router.post("/start")
async def start_session(request: Request):
    data = await request.json()

    student_id = data["student_id"]
    mcq_id = data["mcq_id"]
    subject = data["subject_name"]
    react_order = data["react_order"]
    phase_json = data["phase_json"]

    # 1️⃣ Check existing session
    row = (
        supabase.table("student_mcq_session")
        .select("*")
        .eq("student_id", student_id)
        .eq("mcq_id", mcq_id)
        .eq("subject", subject)
        .limit(1)
        .execute()
    )

    if row.data:
        session = row.data[0]
        return {
            "session_id": session["id"],
            "dialogs": session["dialogs"],
            "phase_json": phase_json,
        }

    # 2️⃣ Ask GPT for first mentor message
    mentor_reply = chat_with_gpt(
        SYSTEM_PROMPT,
        [{
            "role": "user",
            "content": "Start discussion for this MCQ.",
        }],
        extra_context={"mcq": phase_json}
    )

    dialogs = [{
        "role": "assistant",
        "content": mentor_reply,
        "ts": datetime.utcnow().isoformat() + "Z"
    }]

    # 3️⃣ Insert session
    inserted = (
        supabase.table("student_mcq_session")
        .insert({
            "student_id": student_id,
            "mcq_id": mcq_id,
            "subject": subject,
            "react_order": react_order,
            "status": "in_progress",
            "tutor_state": {},
            "dialogs": dialogs,
        })
        .execute()
    )

    session_id = inserted.data[0]["id"]

    return {
        "session_id": session_id,
        "dialogs": dialogs,
        "phase_json": phase_json,
    }


# ───────────────────────────────────────────────
# CONTINUE CHAT
# ───────────────────────────────────────────────
@router.post("/chat")
async def continue_chat(request: Request):
    data = await request.json()

    session_id = data["session_id"]
    student_message = data["message"]

    # 1️⃣ Fetch session
    row = (
        supabase.table("student_mcq_session")
        .select("dialogs")
        .eq("id", session_id)
        .limit(1)
        .execute()
    )

    if not row.data:
        return {"error": "Session not found"}

    dialogs = row.data[0]["dialogs"]

    # 2️⃣ Append student message
    dialogs.append({
        "role": "student",
        "content": student_message,
        "ts": datetime.utcnow().isoformat() + "Z",
    })

    # 3️⃣ Ask GPT (ONLY last student turn)
    mentor_reply = chat_with_gpt(
        SYSTEM_PROMPT,
        [{
            "role": "user",
            "content": student_message,
        }]
    )

    dialogs.append({
        "role": "assistant",
        "content": mentor_reply,
        "ts": datetime.utcnow().isoformat() + "Z",
    })

    # 4️⃣ Persist
    supabase.table("student_mcq_session") \
        .update({
            "dialogs": dialogs,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }) \
        .eq("id", session_id) \
        .execute()

    return {"mentor_reply": mentor_reply}
