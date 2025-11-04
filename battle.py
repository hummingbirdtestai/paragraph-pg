from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from supabase import create_client, Client
import os, asyncio
from dotenv import load_dotenv

# -----------------------------------------------------
# 🔹 SETUP
# -----------------------------------------------------
load_dotenv()
app = FastAPI(title="Battle API")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# -----------------------------------------------------
# 🔹 CONNECTION MANAGER (WebSocket)
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
        """Send JSON to all connected clients; remove dead sockets gracefully."""
        for conn in list(self.active_connections):
            try:
                await conn.send_json(message)
            except Exception:
                self.disconnect(conn)


manager = ConnectionManager()


# -----------------------------------------------------
# 🔹 REST ENDPOINTS
# -----------------------------------------------------
@app.get("/")
async def root():
    return {"status": "Battle API running ✅"}


@app.post("/battle/get_stats")
async def get_battle_stats(mcq_id: str):
    """Returns bar-graph stats for a given MCQ."""
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


# -----------------------------------------------------
# 🔹 BATTLE ORCHESTRATION (AUTO SEQUENCE)
# -----------------------------------------------------
active_battles = set()


@app.post("/battle/start/{battle_id}")
async def start_battle_till_end(battle_id: str, background_tasks: BackgroundTasks):
    """
    Starts the entire battle sequence in background:
      get_first_mcq → get_battle_stats → get_leader_board → get_next_mcq → …
    With synchronized timers:
      MCQ = 20 s (broadcasts every second)
      Stats = 10 s
      Leaderboard = 10 s
    """
    if battle_id in active_battles:
        return {"success": False, "message": "Battle already running."}

    active_battles.add(battle_id)
    print(f"🚀 Scheduling battle orchestrator for {battle_id}")

    # Run orchestration in background (non-blocking)
    background_tasks.add_task(run_battle_sequence, battle_id)

    return {"success": True, "message": f"Battle {battle_id} started in background."}


async def run_battle_sequence(battle_id: str):
    """Background coroutine that runs MCQ → stats → leaderboard loop."""
    try:
        print(f"🏁 Running orchestrator for {battle_id}")

        current = supabase.rpc("get_first_mcq", {"battle_id_input": battle_id}).execute()
        if not current.data:
            print("⚠️ No questions found for this battle.")
            return

        while current.data:
            mcq = current.data[0]

            # 🟢 Broadcast new question
            await manager.broadcast({
                "type": "new_question",
                "data": mcq,
                "message": f"Question {mcq.get('react_order', '?')} started"
            })
            print(f"🧩 Broadcasting question {mcq.get('react_order')}")

            # 🕒 Answering phase: broadcast timer countdown
            for remaining in range(20, 0, -1):
                await manager.broadcast({
                    "type": "timer_sync",
                    "seconds_left": remaining,
                    "message": f"Time remaining: {remaining}s"
                })
                await asyncio.sleep(1)

            # 📊 Battle stats
            stats = supabase.rpc("get_battle_stats", {"mcq_id_input": mcq["mcq_id"]}).execute().data or []
            await manager.broadcast({
                "type": "show_stats",
                "data": stats,
                "message": "Battle stats phase (10 s)"
            })
            print(f"📈 Stats broadcasted for {mcq['mcq_id']}")
            await asyncio.sleep(10)

            # 🏆 Leaderboard
            leaderboard = supabase.rpc("get_leader_board", {"battle_id_input": battle_id}).execute().data or []
            await manager.broadcast({
                "type": "update_leaderboard",
                "data": leaderboard,
                "message": "Leaderboard phase (10 s)"
            })
            print(f"🏅 Leaderboard broadcasted for battle {battle_id}")
            await asyncio.sleep(10)

            # ➡️ Next question
            current = supabase.rpc("get_next_mcq", {
                "battle_id_input": battle_id,
                "react_order_input": mcq.get("react_order", 0)
            }).execute()

        # ✅ End of battle
        await manager.broadcast({
            "type": "battle_end",
            "message": "Battle completed! 🏁"
        })
        print(f"✅ Battle {battle_id} completed.")

    except Exception as e:
        print(f"💥 Orchestrator error for {battle_id}: {e}")
    finally:
        active_battles.remove(battle_id)


# -----------------------------------------------------
# 🔹 REALTIME WEBSOCKET (LIVE ROOM)
# -----------------------------------------------------
@app.websocket("/ws/battle/{battle_id}")
async def battle_room(websocket: WebSocket, battle_id: str):
    """Main battle WebSocket for live events."""
    await manager.connect(websocket)
    print(f"🎮 Player joined battle {battle_id}")

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "end_question":
                mcq_id = data.get("mcq_id")
                stats = supabase.rpc("get_battle_stats", {"mcq_id_input": mcq_id}).execute().data or []
                await manager.broadcast({"type": "show_stats", "data": stats})
                print(f"📊 Manual stats broadcast for {mcq_id}")

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print(f"❌ Player left battle {battle_id}")
