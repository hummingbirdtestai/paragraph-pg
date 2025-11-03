from fastapi import FastAPI, HTTPException
from supabase import create_client, Client
import os
from dotenv import load_dotenv

# ✅ Load environment variables
load_dotenv()

app = FastAPI(title="Battle API")

# ✅ Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# -----------------------------------------------------
# 🔹 1. Get battle stats (Bar graph A/B/C/D)
# -----------------------------------------------------
@app.post("/battle/get_stats")
async def get_battle_stats(mcq_id: str):
    """
    Returns the count of A/B/C/D answers for a given MCQ (room calls this).
    """
    try:
        response = supabase.rpc("get_battle_stats", {"mcq_id_input": mcq_id}).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="No stats found")
        return {"success": True, "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------
# 🔹 2. Get leaderboard for a given battle
# -----------------------------------------------------
@app.post("/battle/leaderboard")
async def get_leaderboard(battle_id: str):
    """
    Returns leaderboard: rank, student_id, total_score, etc.
    """
    try:
        response = supabase.rpc("get_leader_board", {"battle_id_input": battle_id}).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="No leaderboard found")
        return {"success": True, "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------
# 🔹 Health check
# -----------------------------------------------------
@app.get("/")
async def root():
    return {"status": "Battle API running ✅"}
