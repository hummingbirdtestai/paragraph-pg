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

# OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)


# -------------------------
# Request Model
# -------------------------
class ProgressRequest(BaseModel):
    student_id: str
    student_name: str


# -------------------------
# Prompt Builder — PROGRESS
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
# Prompt Builder — ACCURACY
# -------------------------
def build_accuracy_prompt(progress_json, student_name):
    return f"""
You are 30 Years experienced NEETPG Coaching Guru who trained a Million Doctors for NEETPG Exam and know the trajectory of NEETPG Aspirants at various levels of preparation—from the start of their journey to the day of exam when they have mastered all the High Yield topics, PYQs, integrated concepts, and perfected the high-yield facts. 

Advise this Student based on the performance metrics.  
Address the student directly by Name: {student_name}.

Use these definitions for interpretation:
• attempted_mcqs = total MCQs the student has attempted  
• correct_mcqs = MCQs answered correctly  
• overall_accuracy_percent = (correct_mcqs ÷ attempted_mcqs) × 100  
• accuracy_7d_percent = accuracy in last 7 days  
• accuracy_30d_percent = accuracy in last 30 days  
• improvement_delta_percent = (accuracy_7d − accuracy_30d), indicating trend  
• confidence_gap_items = bookmarked-but-wrong MCQs  
• confidence_gap_percent = % of bookmarked MCQs that are wrong  
• This data reflects: performance quality, conceptual strength, error-clusters, trend, retention curve, and exam-readiness.

Your output:
Write a **crisp, powerful, emotionally intelligent 500-word mentor message** that:
• analyses accuracy, errors, strengths, weak zones, and conceptual stability  
• interprets trends (7-day vs 30-day) like a seasoned exam coach  
• decodes confidence gaps and learning behavior  
• explains what stage of exam preparedness the student is currently in  
• predicts future trajectory based on accuracy patterns  
• gives actionable strategy for improving accuracy, retention and exam-temperament  
• includes anecdotes, exam wisdom, and motivational insights  
• uses Unicode symbols (α, β, γ, Na⁺/K⁺, Δ change, x², pH < 7.35, etc.)  
• reflects the experience of training 1 million doctors

Do NOT repeat JSON.  
Do NOT write headings.  
Write as a continuous mentor letter to {student_name}.

STUDENT DATA:
{progress_json}
"""


# -------------------------
# GPT Generator — PROGRESS
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
# GPT Generator — ACCURACY
# -------------------------
def generate_accuracy_comment(progress_json, student_name):
    prompt = build_accuracy_prompt(progress_json, student_name)

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )

    return completion.choices[0].message.content.strip()


# -------------------------
# MAIN ENDPOINT — PROGRESS
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

    # Get new data
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


# -------------------------
# NEW ENDPOINT — ACCURACY ANALYSIS
# -------------------------
@app.post("/accuracy/analysis")
def get_accuracy_analysis(request: ProgressRequest):

    student_id = request.student_id
    student_name = request.student_name

    # Cached Accuracy Comment < 24h
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

            rpc_res = supabase.rpc(
                "get_accuracy_performance_fast",
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
        "get_accuracy_performance_fast",
        {"student_id": student_id}
    ).execute()

    if rpc_res.data is None:
        raise HTTPException(400, "RPC returned no data")

    progress_json = rpc_res.data

    # Generate GPT Comment
    mentor_comment = generate_accuracy_comment(progress_json, student_name)

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
        "data": progress_json
    }


# -------------------------
# Health Check
# -------------------------
@app.get("/")
def health():
    return {"status": "Practice Progress API running 🚀"}
