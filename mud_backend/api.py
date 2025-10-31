# mud_backend/api.py
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import List

# Import the core logic from your existing command executor
from mud_backend.core.command_executor import execute_command
from mud_backend.core.game_objects import Player

# --- FastAPI Setup ---
app = FastAPI()

# --- Connection Management ---
class ConnectionManager:
    """Manages active WebSocket connections."""
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

manager = ConnectionManager()


# --- WebSocket Endpoint ---
@app.websocket("/ws/{player_name}")
async def websocket_endpoint(websocket: WebSocket, player_name: str):
    await manager.connect(websocket)
    
    # Send initial welcome message
    await manager.send_personal_message(f"Welcome to the MUD, {player_name}!", websocket)
    
    try:
        while True:
            # 1. Receive command from frontend
            command_line = await websocket.receive_text()
            
            # 2. Execute command using your core logic
            # The executor returns a list of output lines
            output_lines = execute_command(player_name, command_line)

            # --- Extract Player State for GUI Update ---
            # We need the current player state to update the GUI.
            # We will use the same logic in the executor to get the current Player object.
            # (Note: In a larger app, you'd refactor execute_command to return the Player object.)
            
            # Re-fetch the player data (a slightly inefficient, but simple way to get fresh data)
            player_obj = execute_command.get_player_object(player_name) 

            # 3. Compile the response package
            response_data = {
                "type": "game_output",
                "output": output_lines,
                "player_state": {
                    "name": player_obj.name,
                    "level": player_obj.level,
                    "strength": player_obj.strength,
                    "agility": player_obj.agility,
                    # Placeholder for health/mana, as they are not yet in game_objects.py
                    "health": 100, 
                    "mana": 50 
                }
            }
            
            # 4. Send JSON response back to the client
            await websocket.send_json(response_data)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print(f"Client {player_name} disconnected.")

# --- Main Run Block ---
if __name__ == "__main__":
    # NOTE: Run this file with 'python api.py' 
    # OR run from the project root with: 'uvicorn mud_backend.api:app --reload'
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)