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
app = FastAPI(title="Practice Progress & Accuracy Analysis API")

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

# OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)


# -------------------------
# Request Model
# -------------------------
class ProgressRequest(BaseModel):
    student_id: str
    student_name: str


# -------------------------
# Prompt Builder
# -------------------------
def build_prompt(progress_json, student_name):
    return f"""
You are 30 Years experienced NEETPG Coaching Guru who trained a Million Doctors for NEETPG Exam and knows the trajectory of NEETPG Aspirants—from the start of preparation to the day they master all High Yield topics, PYQs, integrated concepts and exam-temperament. 

Advise the student based on progress metrics. 
Address the student directly by name: {student_name}.

Use these definitions:
• total_items = total learnable units (concept + MCQ)
• completed_items = units finished
• completion_percent = completed_items ÷ total_items × 100
• minutes_spent = real minutes invested
• minutes_total_time_to_complete = estimated minutes to finish the subject

Your output:
Write a **crisp, powerful, emotionally intelligent 500-word mentor message** that:
• analyses strengths, weaknesses and mindset  
• explains what stage the student is currently in  
• predicts trajectory  
• gives actionable strategy  
• includes anecdotes, exam wisdom, and motivational insights  
• uses Unicode (α, β, γ, x², Na⁺/K⁺, HbA₁c, pH < 7.35, etc.)  
• reflects experience of training 1 million doctors

Do NOT repeat JSON.  
Do NOT write headings.  
Write as a continuous mentor letter to {student_name}.

STUDENT DATA:
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

    # Check Cached Comment < 24 hours
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
            
            # Always fetch fresh progress data (only GPT Comment is cached)
            rpc_res = supabase.rpc(
                "get_progress_mastery_with_time",
                {"student_id": student_id}
            ).execute()

            progress_json = rpc_res.data
            
            return {
                "source": "cached",
                "mentor_comment": entry["mentor_comment"],
                "data": progress_json,
            }

    # Call RPC
    rpc_res = supabase.rpc(
        "get_progress_mastery_with_time",
        {"student_id": student_id}
    ).execute()

    if rpc_res.data is None:
        raise HTTPException(400, "RPC returned no data")

    progress_json = rpc_res.data

    # Generate GPT Comment
    mentor_comment = generate_mentor_comment(progress_json, student_name)

    # Save in DB
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


# =====================================================================
# 🎯 NEW ENDPOINT — PRACTICE ACCURACY ANALYSIS
# =====================================================================

# -------------------------
# Accuracy Prompt Builder
# -------------------------
def build_accuracy_prompt(accuracy_json, student_name):
    return f"""
You are a legendary NEET-PG mentor with 30+ years of experience, known for
hyper-personalised guidance, psychological insight, and ruthless accuracy in
diagnosing learning gaps.

Your job: Analyse the student’s subject-wise accuracy JSON and produce EXACTLY
4 paragraphs of extremely high-quality mentor commentary that:
• explains what the student is truly good at,
• reveals deep patterns in their preparation mindset,
• highlights hidden learning gaps,
• gives strategic corrections that can create a U-turn in their NEETPG journey,
• gives timeless exam-oriented wisdom,
• uses motivating, emotionally intelligent teacher tone,
• mixes anecdotes, short inspiring stories, and practical strategy,
• includes some NEETPG high-yield examples (MCQs, facts),
• uses Unicode (e.g., α, β, γ, x², Na⁺/K⁺, pH < 7.35, etc.) formatting,
• includes ONE compact table with comparisons or patterns,
• keeps the message powerful, crisp, and life-changing.

Use these definitions to understand the JSON:
- attempted_mcqs: Total MCQs attempted in that subject
- correct_mcqs: Correctly solved MCQs
- overall_accuracy_percent: Correct ÷ Attempted × 100
- accuracy_7d_percent, accuracy_30d_percent: Recent and 30-day trend
- improvement_delta_percent: 7-day – 30-day accuracy (shows trend)
- confidence_gap_items: Bookmarked but wrong questions
- confidence_gap_percent: % of wrongs among bookmarked MCQs

### 🧾 OUTPUT FORMAT (MANDATORY)
Write **exactly 4 paragraphs**, each 6–8 lines:
1) **Strengths & Mastery Identity**
2) **Weaknesses & Learning Gaps**
3) **Subject-wise Strategy Table + High-Yield Examples**
4) **Powerful 30-year Mentor Action Plan**

Speak directly to the student by name: {student_name}.
Treat the stats as if you’re watching their preparation trajectory from above.

Now here is the student's data:
{accuracy_json}
"""


# -------------------------
# GPT: Mentor Comment for Accuracy
# -------------------------
def generate_accuracy_comment(accuracy_json, student_name):
    prompt = build_accuracy_prompt(accuracy_json, student_name)

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )

    return completion.choices[0].message.content.strip()


# -------------------------
# MAIN ENDPOINT: Accuracy Analysis
# -------------------------
@app.post("/accuracy/analysis")
def get_practice_accuracy_analysis(request: ProgressRequest):

    student_id = request.student_id
    student_name = request.student_name

    # Check Cached Comment < 24 hours
    cached = (
        supabase.table("analysis_comments")
        .select("*")
        .eq("student_id", student_id)
        .eq("comment_type", "practice_accuracy")
        .order("updated_at", desc=True)
        .execute()
    )

    if cached.data:
        entry = cached.data[0]
        ts = entry["updated_at"].replace("Z", "+00:00")
        last_time = datetime.datetime.fromisoformat(ts)
        now = datetime.datetime.now(datetime.timezone.utc)

        if (now - last_time) < datetime.timedelta(hours=24):

            # Always fetch fresh accuracy data (only GPT Comment is cached)
            rpc_res = supabase.rpc(
                "get_accuracy_performance_fast",
                {"student_id": student_id}
            ).execute()

            accuracy_json = rpc_res.data

            return {
                "source": "cached",
                "mentor_comment": entry["mentor_comment"],
                "data": accuracy_json,
            }

    # Call RPC
    rpc_res = supabase.rpc(
        "get_accuracy_performance_fast",
        {"student_id": student_id}
    ).execute()

    if rpc_res.data is None:
        raise HTTPException(400, "RPC returned no data")

    accuracy_json = rpc_res.data

    # Generate GPT Comment
    mentor_comment = generate_accuracy_comment(accuracy_json, student_name)

    # Save in DB
    supabase.table("analysis_comments").insert({
        "student_id": student_id,
        "student_name": student_name,
        "mentor_comment": mentor_comment,
        "comment_type": "practice_accuracy"
    }).execute()

    return {
        "source": "fresh",
        "mentor_comment": mentor_comment,
        "data": accuracy_json
    }


# -------------------------
# Health Check
# -------------------------
@app.get("/")
def health():
    return {"status": "Practice Progress & Accuracy API running 🚀"}
