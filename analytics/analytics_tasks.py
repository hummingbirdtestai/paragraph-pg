from fastapi import APIRouter, Query
from analytics.langchain_engine import analytics_chain

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get("/practice")
def generate_practice_analytics(student_id: str = Query(...)):
    query = f"""
    For student_id='{student_id}', analyze the last 7 days from student_phase_pointer table:
    1. Total concepts completed, total MCQs attempted, accuracy trends.
    2. Subject-wise time spent.
    3. Common mistakes.
    4. 3 actionable revision suggestions.
    Generate concise mentor-style commentary.
    """
    result = analytics_chain.run(query)
    return {"student_id": student_id, "mentor_commentary": result}
