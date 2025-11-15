from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import datetime
import openai
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

# Validate environment variables
if not SUPABASE_URL:
    raise Exception("❌ Missing SUPABASE_URL environment variable")
if not SUPABASE_SERVICE_ROLE:
    raise Exception("❌ Missing SUPABASE_SERVICE_ROLE_KEY environment variable")
if not OPENAI_API_KEY:
    raise Exception("❌ Missing OPENAI_API_KEY environment variable")

# Create Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE)

# Configure OpenAI
openai.api_key = OPENAI_API_KEY


# -------------------------
# Request Model
# -------------------------
class ProgressRequest(BaseModel):
    student_id: str
    student_name: str


# -------------------------
# ChatGPT prompt builder
# -------------------------
def build_prompt(progress_json, student_name):
    return f"""
You are an AI mentor for a NEET-PG student.

The following JSON is the student's subject-wise progress, time spent, and mastery metrics:

STUDENT NAME: {student_name}

PROGRESS DATA:
{progress_json}

Write a short, high-quality mentor_feedback comment:
- Be motivational
- Identify 2–3 strengths
- Identify 2–3 weaknesses
- Suggest exact next steps
- Keep it within 5–6 lines

Return ONLY the mentor_comment text (no JSON, no labels).
"""


# -------------------------
# Generate mentor comment using GPT
# -------------------------
def generate_mentor_comment(progress_json, student_name):
    prompt = build_prompt(progress_json, student_name)

    completion = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )

    return completion.choices[0].message["content"].strip()


# -------------------------
# MAIN ENDPOINT
# -------------------------
@app.post("/progress/analysis")
def get_practice_progress_analysis(request: ProgressRequest):

    student_id = request.student_id
    student_name = request.student_name

    # -------------------------------------------------
    # STEP 1: Check if mentor comment exists < 24 hours
    # -------------------------------------------------
    print("Checking cached mentor comment...")
    cached = (
        supabase.table("analysis_comments")
        .select("*")
        .eq("student_id", student_id)
        .eq("comment_type", "practice_progress")
        .order("updated_at", desc=True)
        .execute()
    )

    if cached.data:
        last_entry = cached.data[0]
        last_time = datetime.datetime.fromisoformat(last_entry["updated_at"])
        now = datetime.datetime.now(datetime.timezone.utc)

        if (now - last_time) < datetime.timedelta(hours=24):
            return {
                "source": "cached",
                "mentor_comment": last_entry["mentor_comment"],
                "data": None
            }

    # -------------------------------------------------
    # STEP 2: Call RPC get_progress_mastery_with_time
    # -------------------------------------------------
    print("Calling Supabase RPC...")

    rpc_res = supabase.rpc(
        "get_progress_mastery_with_time",
        {"student_id": student_id}
    ).execute()

    if rpc_res.data is None:
        raise HTTPException(status_code=400, detail="RPC returned no data")

    progress_json = rpc_res.data

    # -------------------------------------------------
    # STEP 3: Generate ChatGPT mentor comment
    # -------------------------------------------------
    print("Generating ChatGPT feedback...")
    mentor_comment = generate_mentor_comment(progress_json, student_name)

    # -------------------------------------------------
    # STEP 4: Save in analysis_comments
    # -------------------------------------------------
    supabase.table("analysis_comments").insert({
        "student_id": student_id,
        "student_name": student_name,
        "mentor_comment": mentor_comment,
        "comment_type": "practice_progress"
    }).execute()

    # -------------------------------------------------
    # STEP 5: Return to frontend
    # -------------------------------------------------
    return {
        "source": "fresh",
        "mentor_comment": mentor_comment,
        "data": progress_json
    }


# -------------------------
# ROOT (Health Check)
# -------------------------
@app.get("/")
def health():
    return {"status": "Practice Progress API running 🚀"}
