from fastapi import APIRouter, Query
from analytics.langchain_engine import safe_run_chain

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get("/practice")
def generate_inspirational_comment(student_id: str = Query(...)):
    """
    Analyze the student_phase_pointer table and generate a mentor-style commentary
    for NEET-PG preparation progress.
    The LLM is expected to run SQL, interpret the results, and write JSON feedback.
    """

    query = f"""
    You have access to a PostgreSQL table named student_phase_pointer
    with the following relevant columns:
    (student_id, phase_type, is_completed, start_time, end_time).

    Step 1️⃣ — Run the following SQL query:
    SELECT
      SUM(CASE WHEN phase_type = 'concept' AND is_completed = true
               AND end_time > NOW() - INTERVAL '10 days' THEN 1 ELSE 0 END) AS concepts_completed,
      SUM(CASE WHEN phase_type = 'mcq' AND is_completed = true
               AND end_time > NOW() - INTERVAL '10 days' THEN 1 ELSE 0 END) AS mcqs_completed
    FROM student_phase_pointer
    WHERE student_id = '{student_id}';

    Step 2️⃣ — Interpret the result to understand the student's recent progress
    in NEET-PG preparation (concepts learned, MCQs practiced).

    Step 3️⃣ — Write a short, mentor-style feedback paragraph that:
      - Highlights their pace, focus, and consistency.
      - Points out one area of improvement.
      - Sounds encouraging yet critically constructive, like an experienced NEET-PG mentor.

    Step 4️⃣ — Return the output strictly as **valid JSON** in the format below:
    {{
      "student_id": "{student_id}",
      "concepts_completed": <integer>,
      "mcqs_completed": <integer>,
      "mentor_commentary": "<short motivational feedback paragraph>"
    }}
    """

    result = safe_run_chain(query)
    return {
        "student_id": student_id,
        "mentor_feedback": result
    }
