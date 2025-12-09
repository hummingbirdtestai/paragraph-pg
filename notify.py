from fastapi import APIRouter, Request
from supabase_client import supabase

router = APIRouter()

@router.post("/notify")
async def notify(request: Request):
    """
    This endpoint is automatically called by Supabase trigger.
    It forwards notification to realtime channel.
    """
    payload = await request.json()
    record = payload.get("record", {})

    student_id = record.get("student_id")
    message = record.get("message")
    gif_url = record.get("gif_url")
    category = record.get("category")

    if not student_id or not message:
        return {"status": "ignored", "reason": "missing data"}

    # 🔥 Broadcast to realtime
    supabase.realtime.send(
        "student_notifications",
        {
            "event": "new_notification",
            "student_id": student_id,
            "message": message,
            "gif_url": gif_url,
            "category": category,
        }
    )

    return {"status": "ok", "forwarded": True}
