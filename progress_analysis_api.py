from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import datetime
from openai import OpenAI
from supabase import create_client, Client


# -------------------------
# Setup
# -------------------------
app = FastAPI(title="Practice Progress Analysis API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not SUPABASE_URL:
    raise Exception("❌ Missing SUPABASE_URL")
if not SUPABASE_SERVICE_ROLE:
    raise Exception("❌ Missing SUPABASE_SERVICE_ROLE_KEY")
if not OPENAI_API_KEY:
    raise Exception("❌ Missing OPENAI_API_KEY")

# Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE)

# NEW OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)


# -------------------------
# Request Model
# -------------------------
class ProgressRequest(BaseModel):
    student_id: str
    student_name: str


# -------------------------
# Prompt builder  (UPDATED)
# -------------------------
def build_prompt(progress_json, student_name):
    return f"""
You are a legendary NEET-PG mentor with 30+ years of experience, known for hyper-personalised guidance, psychological insight, and ruthless accuracy in diagnosing learning gaps.

Your job: Analyse the student’s subject-wise progress JSON and produce EXACTLY 4 paragraphs of extremely high-quality mentor commentary that:
• explains what the student is truly good at,
• reveals deep patterns in their preparation mindset,
• highlights hidden learning gaps,
• gives strategic corrections that can create a U-turn in their NEETPG journey,
• gives timeless exam-oriented wisdom,
• uses motivating, emotionally intelligent teacher tone,
• mixes anecdotes, short inspiring stories, and practical strategy,
• includes some NEETPG high-yield examples (MCQs, facts),
• uses Unicode (e.g., α, β, γ, x², Na⁺/K⁺, pH < 7.35, etc.) formatting (super/subscripts, greek letters, emojis, math),
• includes ONE compact table with comparisons or patterns,
• keeps the message powerful, crisp, and life-changing.

Use these definitions to understand the JSON:
- total_items: Total learning units in a subject = MAX(total_count) × 2. (Every concept has 2 stages: Concept + MCQ).
- completed_items: Count of units where is_completed = TRUE.
- completion_percent: completed_items ÷ total_items × 100.
- minutes_spent: Total active learning minutes for completed phases.
- minutes_total_time_to_complete: Estimated total minutes needed to finish that entire subject.

### 🧾 OUTPUT FORMAT (MANDATORY)
Write exactly 4 paragraphs, each 6–8 lines:
1) Strengths & Mastery Identity  
2) Weaknesses & Learning Gaps — with examples or micro-cases  
3) Subject-wise Strategy Table + High-Yield Examples  
   – Include ONE compact table comparing 3–5 subjects  
   – Include 2–3 high-yield NEETPG examples (concept or MCQ stems)  
4) Powerful 30-year Mentor Action Plan

• Do NOT rewrite the JSON.  
• Do NOT produce bullet lists except the required table.  
• Keep the tone wise, inspiring, and strategic — not generic.  
• Speak directly to the student by name: {student_name}.  
• Treat the stats as if you’re watching their preparation trajectory from above.

STUDENT NAME: {student_name}

PROGRESS DATA:
{progress_json}
"""


# -------------------------
# GPT: Mentor Comment
# -------------------------
def generate_mentor_comment(progress_json, student_name):
    prompt = build_prompt(progress_json, student_name)

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )

    return completion.choices[0].message.content.strip()


# -------------------------
# MAIN ENDPOINT
# -------------------------
@app.post("/progress/analysis")
def get_practice_progress_analysis(request: ProgressRequest):

    student_id = request.student_id
    student_name = request.student_name

    # -------------------------
    # Check Cached Comment < 24 hours
    # -------------------------
    cached = (
        supabase.table("analysis_comments")
        .select("*")
        .eq("student_id", student_id)
        .eq("comment_type", "practice_progress")
        .order("updated_at", desc=True)
        .execute()
    )

    if cached.data:
        entry = cached.data[0]
        ts = entry["updated_at"].replace("Z", "+00:00")
        last_time = datetime.datetime.fromisoformat(ts)
        now = datetime.datetime.now(datetime.timezone.utc)

        if (now - last_time) < datetime.timedelta(hours=24):
            return {
                "source": "cached",
                "mentor_comment": entry["mentor_comment"],
                "data": None,
            }

    # -------------------------
    # Call RPC
    # -------------------------
    rpc_res = supabase.rpc(
        "get_progress_mastery_with_time",
        {"student_id": student_id}
    ).execute()

    if rpc_res.data is None:
        raise HTTPException(400, "RPC returned no data")

    progress_json = rpc_res.data

    # -------------------------
    # Generate GPT Comment
    # -------------------------
    mentor_comment = generate_mentor_comment(progress_json, student_name)

    # -------------------------
    # Save in DB
    # -------------------------
    supabase.table("analysis_comments").insert({
        "student_id": student_id,
        "student_name": student_name,
        "mentor_comment": mentor_comment,
        "comment_type": "practice_progress"
    }).execute()

    return {
        "source": "fresh",
        "mentor_comment": mentor_comment,
        "data": progress_json
    }


# -------------------------
# Health Check
# -------------------------
@app.get("/")
def health():
    return {"status": "Practice Progress API running 🚀"}
