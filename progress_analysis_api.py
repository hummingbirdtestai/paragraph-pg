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
    CORSMiddleware(
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
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
# Prompt builder (UPDATED)
# -------------------------
def build_prompt(progress_json, student_name):
    return f"""
You are a 30-year veteran NEETPG Coaching Guru who has trained over one million doctors. 
You understand every stage of a student's NEETPG preparation journey — from their first chapter to 
the day they master PYQs, high-yield facts, integrated concepts, and exam temperament.

Your task: Based on the JSON data below, write a **crisp, inspiring, highly personalised 500-word mentor guidance** addressed directly 
to the student by name: {student_name}.  
You must sound like a legendary teacher who knows preparation psychology, patterns of toppers, and pitfalls of average candidates.

Use these metric definitions:
- total_items = total learnable units (concept + MCQ).
- completed_items = units finished.
- completion_percent = completed_items ÷ total_items × 100.
- minutes_spent = real minutes invested.
- minutes_total_time_to_complete = estimated minutes to finish the subject.

Your output must:
• Analyse strengths, mindset patterns, pace, discipline  
• Reveal hidden weaknesses (with examples if needed)  
• Tell the student what stage of preparation they are currently in  
• Predict what their trajectory looks like  
• Give very actionable corrections  
• Use NEETPG exam wisdom, anecdotes, motivation  
• Be emotionally intelligent and confidence-building  
• Include references to high-yield NEETPG facts, formulas, or micro-MCQs  
• Use Unicode formatting (e.g., α, β, γ, x², Na⁺/K⁺, HbA₁c, pH < 7.35)

Tone:  
Wise, caring, deeply experienced, strategic, life-changing — NOT generic.

Length:  
**Exactly ~500 words.**

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

    # Check cached comment < 24 hours
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


# -------------------------
# Health Check
# -------------------------
@app.get("/")
def health():
    return {"status": "Practice Progress API running 🚀"}
