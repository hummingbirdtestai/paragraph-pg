from fastapi import APIRouter, Query
from analytics.langchain_engine import analytics_chain

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get("/practice")
def generate_completion_analytics(student_id: str = Query(...)):
    """
    For a given student_id, analyze student_phase_pointer table to find:
    - Number of concepts completed in the last 10 days
    - Number of MCQs completed in the last 10 days
    """
    query = f"""
    For student_id='{student_id}', query the student_phase_pointer table and calculate:
    1. The total count of rows where phase_type='concept' and is_completed=true 
       within the past 10 days based on end_time.
    2. The total count of rows where phase_type='mcq' and is_completed=true 
       within the past 10 days based on end_time.
    Return the results in JSON format with keys:
       'concepts_completed' and 'mcqs_completed'.
    """

    result = analytics_chain.run(query)
    return {
        "student_id": student_id,
        "completion_summary": result
    }
