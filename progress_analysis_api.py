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

# ✅ CORRECT CORS MIDDLEWARE (do NOT overwrite app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------
# Environment Variables
# -------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not SUPABASE_URL:
    raise Exception("❌ Missing SUPABASE_URL")
if not SUPABASE_SERVICE_ROLE:
    raise Exception("❌ Missing SUPABASE_SERVICE_ROLE_KEY")
if not OPENAI_API_KEY:
    raise Exception("❌ Missing OPENAI_API_KEY")

# Clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE)
client = OpenAI(api_key=OPENAI_API_KEY)


# -------------------------
# Request Model
# -------------------------
class ProgressRequest(BaseModel):
    student_id: str
    student_name: str


# -------------------------
# PROMPTS — PROGRESS
# -------------------------
def build_prompt(progress_json, student_name):
    return f"""
You are 30 Years experienced NEETPG Coaching Guru who trained a Million Doctors...

STUDENT DATA:
{progress_json}
"""


# -------------------------
# PROMPTS — ACCURACY
# -------------------------
def build_accuracy_prompt(progress_json, student_name):
    return f"""
You are 30 Years experienced NEETPG Coaching Guru...

STUDENT DATA:
{progress_json}
"""


# -------------------------
# GENERATORS
# -------------------------
def generate_mentor_comment(progress_json, student_name):
    prompt = build_prompt(progress_json, student_name)
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return completion.choices[0].message.content.strip()


def generate_accuracy_comment(progress_json, student_name):
    prompt = build_accuracy_prompt(progress_json, student_name)
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return completion.choices[0].message.content.strip()


# -------------------------
# ENDPOINT — PROGRESS
# -------------------------
@app.post("/progress/analysis")
def get_practice_progress_analysis(request: ProgressRequest):

    student_id = request.student_id
    student_name = request.student_name

    cached = (
        supabase.table("analysis_comments")
        .select("*")
        .eq("student_id", student_id)
        .eq("comment_type", "practice_progress")
        .order("updated_at", desc=True)
        .execute()
    )

    # Return cached if < 24 hours old
    if cached.data:
        entry = cached.data[0]
        ts = entry["updated_at"].replace("Z", "+00:00")
        last = datetime.datetime.fromisoformat(ts)
        now = datetime.datetime.now(datetime.timezone.utc)

        if (now - last) < datetime.timedelta(hours=24):

            rpc_res = supabase.rpc(
                "get_progress_mastery_with_time",
                {"student_id": student_id}
            ).execute()

            return {
                "source": "cached",
                "mentor_comment": entry["mentor_comment"],
                "data": rpc_res.data,
            }

    # Fresh call
    rpc_res = supabase.rpc(
        "get_progress_mastery_with_time",
        {"student_id": student_id}
    ).execute()

    progress_json = rpc_res.data
    if progress_json is None:
        raise HTTPException(400, "RPC returned no data")

    mentor_comment = generate_mentor_comment(progress_json, student_name)

    # Save
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
# ENDPOINT — ACCURACY
# -------------------------
@app.post("/accuracy/analysis")
def get_accuracy_analysis(request: ProgressRequest):

    student_id = request.student_id
    student_name = request.student_name

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
        last = datetime.datetime.fromisoformat(ts)
        now = datetime.datetime.now(datetime.timezone.utc)

        if (now - last) < datetime.timedelta(hours=24):

            rpc_res = supabase.rpc(
                "get_accuracy_performance_fast",
                {"student_id": student_id}
            ).execute()

            return {
                "source": "cached",
                "mentor_comment": entry["mentor_comment"],
                "data": rpc_res.data,
            }

    rpc_res = supabase.rpc(
        "get_accuracy_performance_fast",
        {"student_id": student_id}
    ).execute()

    progress_json = rpc_res.data
    if progress_json is None:
        raise HTTPException(400, "RPC returned no data")

    mentor_comment = generate_accuracy_comment(progress_json, student_name)

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
# HEALTH CHECK
# -------------------------
@app.get("/")
def health():
    return {"status": "Practice Progress API running 🚀"}


# ============================================================
# LEARNING-GAP
# ============================================================
def build_learning_gap_prompt(gap_json, student_name):
    return f"""
You are 30 Years experienced NEETPG Coaching Guru...

STUDENT DATA:
{gap_json}
"""


def generate_learning_gap_comment(gap_json, student_name):
    prompt = build_learning_gap_prompt(gap_json, student_name)
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return completion.choices[0].message.content.strip()


@app.post("/learning-gap/analysis")
def get_learning_gap_analysis(request: ProgressRequest):

    student_id = request.student_id
    student_name = request.student_name

    cached = (
        supabase.table("analysis_comments")
        .select("*")
        .eq("student_id", student_id)
        .eq("comment_type", "flashcard_learning_gap")
        .order("updated_at", desc=True)
        .execute()
    )

    # cached logic
    if cached.data:
        entry = cached.data[0]
        ts = entry["updated_at"].replace("Z", "+00:00")
        last = datetime.datetime.fromisoformat(ts)
        now = datetime.datetime.now(datetime.timezone.utc)

        if (now - last) < datetime.timedelta(hours=24):

            rpc_res = supabase.rpc(
                "get_deep_learning_gap",
                {"student_id": student_id}
            ).execute()

            return {
                "source": "cached",
                "mentor_comment": entry["mentor_comment"],
                "data": rpc_res.data,
            }

    rpc_res = supabase.rpc(
        "get_deep_learning_gap",
        {"student_id": student_id}
    ).execute()

    gap_json = rpc_res.data
    if gap_json is None:
        raise HTTPException(400, "RPC returned no data")

    mentor_comment = generate_learning_gap_comment(gap_json, student_name)

    supabase.table("analysis_comments").insert({
        "student_id": student_id,
        "student_name": student_name,
        "mentor_comment": mentor_comment,
        "comment_type": "flashcard_learning_gap"
    }).execute()

    return {
        "source": "fresh",
        "mentor_comment": mentor_comment,
        "data": gap_json
    }


# ============================================================
# FLASHCARD MASTERY PROGRESS
# ============================================================
def build_flashcard_mastery_prompt(flash_json, student_name):
    return f"""
You are 30 Years experienced NEETPG Coaching Guru...

STUDENT DATA:
{flash_json}
"""


def generate_flashcard_mastery_comment(flash_json, student_name):
    prompt = build_flashcard_mastery_prompt(flash_json, student_name)
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return completion.choices[0].message.content.strip()


@app.post("/flashcards/mastery")
def get_flashcard_mastery_analysis(request: ProgressRequest):

    student_id = request.student_id
    student_name = request.student_name

    cached = (
        supabase.table("analysis_comments")
        .select("*")
        .eq("student_id", student_id)
        .eq("comment_type", "flashcard_mastery")
        .order("updated_at", desc=True)
        .execute()
    )

    if cached.data:
        entry = cached.data[0]
        ts = entry["updated_at"].replace("Z", "+00:00")
        last = datetime.datetime.fromisoformat(ts)
        now = datetime.datetime.now(datetime.timezone.utc)

        if (now - last) < datetime.timedelta(hours=24):

            rpc_res = supabase.rpc(
                "get_flashcard_mastery_progress",
                {"student_id": student_id}
            ).execute()

            return {
                "source": "cached",
                "mentor_comment": entry["mentor_comment"],
                "data": rpc_res.data,
            }

    rpc_res = supabase.rpc(
        "get_flashcard_mastery_progress",
        {"student_id": student_id}
    ).execute()

    flash_json = rpc_res.data
    if flash_json is None:
        raise HTTPException(400, "RPC returned no data")

    mentor_comment = generate_flashcard_mastery_comment(flash_json, student_name)

    supabase.table("analysis_comments").insert({
        "student_id": student_id,
        "student_name": student_name,
        "mentor_comment": mentor_comment,
        "comment_type": "flashcard_mastery"
    }).execute()

    return {
        "source": "fresh",
        "mentor_comment": mentor_comment,
        "data": flash_json
    }


# ============================================================
# MOCKTEST PERFORMANCE — NEW
# ============================================================

def build_mocktest_prompt(mocktest_json, student_name):
    return f"""
You are a 30-year experienced NEETPG Coaching Guru who has trained over one million doctors for NEETPG.

These are the student's full-scale mock-test performance metrics, broken down by subject and exam.

Address the student directly by name: {student_name}.

Use these definitions:
• total_questions = MCQs asked  
• answered = attempted  
• skipped = left unattempted  
• correct_answers = correct  
• wrong_answers = incorrect  
• score = (correct × 4) − wrong  
• accuracy_percent = (correct ÷ answered × 100)  
• attempt_rate_percent = (answered ÷ total_questions × 100)  
• avg_time_per_mcq = avg minutes per MCQ  
• time_spent_min = total minutes spent  
• time_eff_percent = (1 ÷ avg_time_per_mcq × 100)  
• effort_eff_percent = percent of max possible score obtained  

Write a powerful, 500-word continuous mentor letter using emotional intelligence and exam-strategy depth.  
No JSON repetition. No headings.

STUDENT DATA:
{mocktest_json}
"""


def generate_mocktest_comment(mocktest_json, student_name):
    prompt = build_mocktest_prompt(mocktest_json, student_name)
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return completion.choices[0].message.content.strip()


@app.post("/mocktest/test-results")
def get_mocktest_results(request: ProgressRequest):

    student_id = request.student_id
    student_name = request.student_name

    # Check cache
    cached = (
        supabase.table("analysis_comments")
        .select("*")
        .eq("student_id", student_id)
        .eq("comment_type", "mocktest_results")
        .order("updated_at", desc=True)
        .execute()
    )

    if cached.data:
        entry = cached.data[0]
        ts = entry["updated_at"].replace("Z", "+00:00")
        last = datetime.datetime.fromisoformat(ts)
        now = datetime.datetime.now(datetime.timezone.utc)

        if (now - last) < datetime.timedelta(hours=24):
            rpc_res = supabase.rpc(
                "get_mock_test_subject_performance",
                {"p_student_id": student_id}
            ).execute()

            return {
                "source": "cached",
                "mentor_comment": entry["mentor_comment"],
                "data": rpc_res.data,
            }

    # Fresh RPC
    rpc_res = supabase.rpc(
        "get_mock_test_subject_performance",
        {"p_student_id": student_id}
    ).execute()

    mocktest_json = rpc_res.data
    if mocktest_json is None:
        raise HTTPException(400, "RPC returned no data")

    mentor_comment = generate_mocktest_comment(mocktest_json, student_name)

    supabase.table("analysis_comments").insert({
        "student_id": student_id,
        "student_name": student_name,
        "mentor_comment": mentor_comment,
        "comment_type": "mocktest_results"
    }).execute()

    return {
        "source": "fresh",
        "mentor_comment": mentor_comment,
        "data": mocktest_json
    }
# ============================================================
# MOCKTEST PERFORMANCE — NEW
# ============================================================

def build_mocktest_prompt(mocktest_json, student_name):
    return f"""
You are a 30 Years experienced NEETPG Coaching Guru who trained a Million Doctors at all stages of their NEETPG journey.
These are the student's full-scale mock-test performance metrics.

Address the student directly by Name: {student_name}.

Use these definitions:
• total_questions = MCQs asked  
• answered = attempted  
• skipped = left unattempted  
• correct_answers = correct  
• wrong_answers = incorrect  
• total_score = (correct × 4) − wrong  
• accuracy_percent = (correct ÷ answered × 100)  
• attempt_rate_percent = (answered ÷ total_questions × 100)  
• avg_time_per_mcq = average minutes per MCQ  
• time_spent_min = total minutes spent  
• time_eff_percent = (1 ÷ avg_time_per_mcq × 100)  
• effort_eff_percent = percent of max possible score obtained  

Write a powerful, emotionally intelligent, 500-word continuous mentor letter.
Do NOT repeat the JSON.
Do NOT use headings.

STUDENT DATA:
{mocktest_json}
"""


def generate_mocktest_comment(mocktest_json, student_name):
    prompt = build_mocktest_prompt(mocktest_json, student_name)
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return completion.choices[0].message.content.strip()


@app.post("/mocktest/performance")
def get_mocktest_performance(request: ProgressRequest):

    student_id = request.student_id
    student_name = request.student_name

    # ---- CACHE CHECK ----
    cached = (
        supabase.table("analysis_comments")
        .select("*")
        .eq("student_id", student_id)
        .eq("comment_type", "mocktest_performance")
        .order("updated_at", desc=True)
        .execute()
    )

    if cached.data:
        entry = cached.data[0]

        ts = entry["updated_at"].replace("Z", "+00:00")
        last = datetime.datetime.fromisoformat(ts)
        now = datetime.datetime.now(datetime.timezone.utc)

        # < 24 hours → use cache
        if (now - last) < datetime.timedelta(hours=24):

            rpc_res = supabase.rpc(
                "get_mock_test_performance_summary",
                {"student_id": student_id}
            ).execute()

            return {
                "source": "cached",
                "mentor_comment": entry["mentor_comment"],
                "data": rpc_res.data,
            }

    # ---- FRESH RPC ----
    rpc_res = supabase.rpc(
        "get_mock_test_performance_summary",
        {"student_id": student_id}
    ).execute()

    mock_json = rpc_res.data
    if mock_json is None:
        raise HTTPException(400, "RPC returned no data")

    mentor_comment = generate_mocktest_comment(mock_json, student_name)

    # ---- SAVE ----
    supabase.table("analysis_comments").insert({
        "student_id": student_id,
        "student_name": student_name,
        "mentor_comment": mentor_comment,
        "comment_type": "mocktest_performance"
    }).execute()

    return {
        "source": "fresh",
        "mentor_comment": mentor_comment,
        "data": mock_json
    }

# ============================================================
# BATTLE PERFORMANCE — NEW
# ============================================================

def build_battle_prompt(battle_json, student_name):
    return f"""
You are a 30 Years experienced NEETPG Coaching Guru who has trained a Million Doctors for NEETPG Exam and understand how students evolve inside high-pressure competitive Battle Rooms. These are the student's Battle performance metrics across subjects.

Address the student directly by Name: {student_name}.

Use these definitions derived from battle analytics:
• total_questions = MCQs asked  
• answered = attempted  
• correct_answers = correct  
• wrong_answers = incorrect  
• score = (correct × 4) − wrong  
• accuracy_percent = (correct ÷ answered × 100)  
• attempt_rate_percent = (answered ÷ total_questions × 100)  
• avg_time_per_mcq_sec = average time per MCQ in seconds  
• time_spent_min = total minutes spent  
• time_eff_percent = (20 sec ÷ avg_time_per_mcq_sec × 100)  
• effort_eff_percent = score efficiency as % of max possible marks  

Make the message emotionally intelligent, powerful and exactly 500 words.  
Use Unicode symbols (α, β, γ, Δ, Na⁺/K⁺, μ, λ).  
Do NOT repeat the JSON.  
Do NOT use headings.  
Write as one continuous mentor letter addressed personally to {student_name}.

STUDENT DATA:
{battle_json}
"""


def generate_battle_comment(battle_json, student_name):
    prompt = build_battle_prompt(battle_json, student_name)
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return completion.choices[0].message.content.strip()


@app.post("/battle/battle_stats")
def get_battle_stats(request: ProgressRequest):

    student_id = request.student_id
    student_name = request.student_name

    # ---- CACHE CHECK ----
    cached = (
        supabase.table("analysis_comments")
        .select("*")
        .eq("student_id", student_id)
        .eq("comment_type", "battle_stats")
        .order("updated_at", desc=True)
        .execute()
    )

    if cached.data:
        entry = cached.data[0]

        ts = entry["updated_at"].replace("Z", "+00:00")
        last = datetime.datetime.fromisoformat(ts)
        now = datetime.datetime.now(datetime.timezone.utc)

        # Cache valid for 24 hours
        if (now - last) < datetime.timedelta(hours=24):

            rpc_res = supabase.rpc(
                "get_battle_subject_performance",
                {"p_student_id": student_id}
            ).execute()

            return {
                "source": "cached",
                "mentor_comment": entry["mentor_comment"],
                "data": rpc_res.data,
            }

    # ---- FRESH RPC ----
    rpc_res = supabase.rpc(
        "get_battle_subject_performance",
        {"p_student_id": student_id}
    ).execute()

    battle_json = rpc_res.data
    if battle_json is None:
        raise HTTPException(400, "RPC returned no data")

    mentor_comment = generate_battle_comment(battle_json, student_name)

    # ---- SAVE ----
    supabase.table("analysis_comments").insert({
        "student_id": student_id,
        "student_name": student_name,
        "mentor_comment": mentor_comment,
        "comment_type": "battle_stats"
    }).execute()

    return {
        "source": "fresh",
        "mentor_comment": mentor_comment,
        "data": battle_json
    }
# ============================================================
# BATTLE PERFORMANCE SUMMARY (NEW ENDPOINT)
# ============================================================

def build_battle_performance_prompt(battle_json, student_name):
    return f"""
You are a 30-year experienced NEETPG Coaching Guru who has trained over one million doctors. 
You deeply understand how students behave under competitive stress inside Battle Rooms, 
and how accuracy, speed, and decision-making evolve over time.

These are the student's overall Battle performance summaries across completed battles.

Address the student directly by Name: {student_name}.

Use these definitions exactly:
• total_questions = MCQs asked  
• answered = attempted  
• correct_answers = correct  
• wrong_answers = incorrect  
• score = (correct × 4) − wrong  
• accuracy_percent = (correct ÷ answered × 100)  
• attempt_rate_percent = (answered ÷ total_questions × 100)  
• avg_time_per_mcq_sec = average seconds taken per MCQ  
• time_spent_min = total minutes spent  
• time_eff_percent = (20 ÷ avg_time_per_mcq_sec × 100)  
• effort_eff_percent = percent of max possible score obtained  

Write a powerful, emotionally intelligent, EXACT 500-word continuous mentor letter.  
Use Unicode symbols (α, β, γ, Δ, Na⁺/K⁺, μ, λ, etc.).  
Do NOT repeat the JSON.  
Do NOT use headings.  
Write as one flowing letter addressed personally to {student_name}.

STUDENT DATA:
{battle_json}
"""


def generate_battle_performance_comment(battle_json, student_name):
    prompt = build_battle_performance_prompt(battle_json, student_name)
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return completion.choices[0].message.content.strip()


@app.post("/battle/battle-performance")
def get_battle_performance(request: ProgressRequest):

    student_id = request.student_id
    student_name = request.student_name

    # ---- CHECK CACHE ----
    cached = (
        supabase.table("analysis_comments")
        .select("*")
        .eq("student_id", student_id)
        .eq("comment_type", "battle_performance")
        .order("updated_at", desc=True)
        .execute()
    )

    if cached.data:
        entry = cached.data[0]

        ts = entry["updated_at"].replace("Z", "+00:00")
        last = datetime.datetime.fromisoformat(ts)
        now = datetime.datetime.now(datetime.timezone.utc)

        # Use cached comment if < 24 hours old
        if (now - last) < datetime.timedelta(hours=24):

            rpc_res = supabase.rpc(
                "get_battle_performance_summary",
                {"p_student_id": student_id}
            ).execute()

            return {
                "source": "cached",
                "mentor_comment": entry["mentor_comment"],
                "data": rpc_res.data,
            }

    # ---- FRESH RPC CALL ----
    rpc_res = supabase.rpc(
        "get_battle_performance_summary",
        {"p_student_id": student_id}
    ).execute()

    battle_json = rpc_res.data
    if battle_json is None:
        raise HTTPException(400, "RPC returned no data")

    # ---- GENERATE COMMENT ----
    mentor_comment = generate_battle_performance_comment(battle_json, student_name)

    # ---- SAVE COMMENT ----
    supabase.table("analysis_comments").insert({
        "student_id": student_id,
        "student_name": student_name,
        "mentor_comment": mentor_comment,
        "comment_type": "battle_performance"
    }).execute()

    return {
        "source": "fresh",
        "mentor_comment": mentor_comment,
        "data": battle_json
    }


