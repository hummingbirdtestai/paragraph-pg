# battle_api.py
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from supabase import create_client, Client
import os, asyncio
from dotenv import load_dotenv

# ✅ Load environment variables
load_dotenv()

app = FastAPI(title="Battle API")

# ✅ Supabase client (service role key)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# -----------------------------------------------------
# 🔹 REST ENDPOINTS
# -----------------------------------------------------
@app.post("/battle/get_stats")
async def get_battle_stats(mcq_id: str):
    """Returns the count of A/B/C/D answers for a given MCQ."""
    try:
        response = supabase.rpc("get_battle_stats", {"mcq_id_input": mcq_id}).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="No stats found")
        return {"success": True, "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/battle/leaderboard")
async def get_leaderboard(battle_id: str):
    """Returns leaderboard for a given battle."""
    try:
        response = supabase.rpc("get_leader_board", {"battle_id_input": battle_id}).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="No leaderboard found")
        return {"success": True, "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    return {"status": "Battle API running ✅"}


# -----------------------------------------------------
# 🔹 REALTIME WEBSOCKET BATTLE ROOM
# -----------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except Exception:
                pass


manager = ConnectionManager()


@app.websocket("/ws/battle/{battle_id}")
async def battle_room(websocket: WebSocket, battle_id: str):
    """Main battle room WebSocket for real-time coordination."""
    await manager.connect(websocket)
    print(f"🎮 Player joined battle {battle_id}")

    try:
        while True:
            data = await websocket.receive_json()

            # 🕒 Timer ended → fetch stats
            if data.get("type") == "end_question":
                mcq_id = data.get("mcq_id")

                # 1️⃣ Fetch bar graph data
                stats = supabase.rpc("get_battle_stats", {"mcq_id_input": mcq_id}).execute().data or []
                await manager.broadcast({"type": "show_stats", "data": stats})

                # 2️⃣ Wait 5 seconds → fetch leaderboard
                await asyncio.sleep(5)
                leaderboard = supabase.rpc("get_leader_board", {"battle_id_input": battle_id}).execute().data or []
                await manager.broadcast({"type": "update_leaderboard", "data": leaderboard})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print(f"❌ Player left battle {battle_id}")
