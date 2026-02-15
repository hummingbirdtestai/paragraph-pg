# stream_token.py

import os
from fastapi import APIRouter
from stream_video import StreamVideo

router = APIRouter()

api_key = os.getenv("STREAM_API_KEY")
api_secret = os.getenv("STREAM_API_SECRET")

video_client = StreamVideo(api_key=api_key, api_secret=api_secret)

@router.post("/stream/token")
def create_stream_token(user_id: str):
    token = video_client.create_token(user_id)
    return {"token": token}
