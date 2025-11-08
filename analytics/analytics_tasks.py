from fastapi import APIRouter, Query
from analytics.langchain_engine import analytics_chain

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get("/practice")
def generate_inspirational_comment(student_id: str = Query(...)):
    """
    For a given student_id, analyze student_phase_pointer table and generate
    a mentor-style motivational commentary on the student’s NEET-PG progress.
    """
    query = f"""
    For student_id='{student_id}', query the student_phase_pointer table and determine:
    1. Number of concepts completed in the past 10 days 
       (phase_type='concept' AND is_completed=true).
    2. Number of MCQs completed in the past 10 days 
       (phase_type='mcq' AND is_completed=true).

    Based on these results, write a short mentor-style message assessing the student's
    NEET-PG preparation. 
    - Comment on their pace, consistency, and focus.  
    - Mention strengths and weak points.
    - Encourage them with an inspiring yet critical tone, like a senior mentor guiding them
      to sustain momentum.

    Return the response as JSON with:
      "student_id": "<id>",
      "concepts_completed": <number>,
      "mcqs_completed": <number>,
      "mentor_commentary": "<motivational feedback paragraph>"
    """

    result = analytics_chain.run(query)
    return {
        "student_id": student_id,
        "mentor_feedback": result
    }
