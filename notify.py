from fastapi import APIRouter, Request
from supabase_client import send_realtime_event

router = APIRouter()

@router.post("/notify")
async def notify(request: Request):
    """
    Called automatically by Supabase trigger.
    Forwards notification to Supabase Realtime channel.
    """
    payload = await request.json()
    record = payload.get("record", {})

    student_id = record.get("student_id")
    message = record.get("message")
    gif_url = record.get("gif_url")
    category = record.get("category")
    notification_id = record.get("id")
    created_at = record.get("created_at")

    # Validate minimal required data
    if not student_id or not message:
        return {"status": "ignored", "reason": "missing student_id/message"}

    # 🔥 Build payload EXACTLY as required by Supabase Realtime V2
    realtime_payload = {
        "student_id": student_id,
        "message": message,
        "gif_url": gif_url,
        "category": category,
        "id": notification_id,
        "created_at": created_at
    }

    # 🔥 Send broadcast event via REST (correct Realtime V2 format)
    send_realtime_event(
        "student_notifications",
        realtime_payload
    )

    return {"status": "ok", "forwarded": True}
