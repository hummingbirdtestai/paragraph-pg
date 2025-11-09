from fastapi import APIRouter, Query
from analytics.langchain_engine import safe_run_chain

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get("/practice")
def generate_inspirational_comment(student_id: str = Query(...)):
    """
    Analyze student_phase_pointer table and generate mentor-style commentary
    for NEET-PG preparation progress.
    """
    query = f"""
    For student_id='{student_id}', query the student_phase_pointer table to determine:
    1. Number of concepts completed in the past 10 days 
       (phase_type='concept' AND is_completed=true).
    2. Number of MCQs completed in the past 10 days 
       (phase_type='mcq' AND is_completed=true).

    Then, based on these results, write a concise and motivating mentor-style commentary
    about the student's NEET-PG preparation — highlighting pace, focus, and improvement areas.
    Use an encouraging yet constructive tone, like a senior mentor guiding the student.

    Return the response strictly as JSON with:
    {{
      "student_id": "<id>",
      "concepts_completed": <integer>,
      "mcqs_completed": <integer>,
      "mentor_commentary": "<motivational paragraph>"
    }}
    """

    result = safe_run_chain(query)
    return {
        "student_id": student_id,
        "mentor_feedback": result
    }
