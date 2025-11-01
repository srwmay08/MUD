# mud_backend/app.py
import sys
import os
import time
import datetime
import threading 
from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room

# --- CRITICAL FIX 1: Add the PROJECT ROOT to the Python path ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# -----------------------------------------------------------

from mud_backend.core.command_executor import execute_command, _check_and_run_game_tick
from mud_backend.core import game_state
from mud_backend.core import db

# --- CRITICAL FIX 2: Define file paths ---
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mud_frontend', 'templates'))
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mud_frontend', 'static'))

# --- NEW: Initialize Flask and SocketIO ---
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.config['SECRET_KEY'] = 'your-very-secret-key!' # Change this
socketio = SocketIO(app)
# ---

# --- Route 1: Serve the HTML page (Unchanged) ---
@app.route("/")
def index():
    return render_template("index.html")

# ---
# NEW: BACKGROUND GAME TICK THREAD
# ---
def game_tick_thread():
    """
    A background thread that runs the game tick every N seconds
    independently of any player actions.
    """
    print("[SERVER START] Game Tick thread started.")
    with app.app_context():
        while True:
            # --- This is the broadcast function for the game loop ---
            def broadcast_to_room(room_id, message, msg_type):
                # We use socketio.emit to send to a "room"
                socketio.emit("message", message, to=room_id)

            # We create a dummy player object just to pass to the tick
            dummy_player_for_tick = type('Player', (object,), {'current_room_id': 'void'})()
            _check_and_run_game_tick(dummy_player_for_tick, broadcast_to_room)
            
            # Wait for the next tick
            time.sleep(game_state.TICK_INTERVAL_SECONDS)

# ---
# NEW: WEBSOCKET EVENT HANDLERS
# ---

@socketio.on('connect')
def handle_connect():
    """A new client has connected."""
    print(f"[CONNECTION] Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    """A client has disconnected."""
    sid = request.sid
    player_info = game_state.ACTIVE_PLAYERS.pop(sid, None)
    
    if player_info:
        player_name = player_info["player_name"]
        room_id = player_info["current_room_id"]
        print(f"[CONNECTION] Player {player_name} disconnected: {sid}")
        
        # Broadcast that the player has left
        emit("message", f"{player_name} disappears.", to=room_id)
    else:
        print(f"[CONNECTION] Unknown client disconnected: {sid}")

@socketio.on('command')
def handle_command_event(data):
    """
    Handles a command sent from a client.
    This replaces the old /api/command route.
    """
    sid = request.sid
    player_name = data.get("player_name")
    command_line = data.get("command", "")

    if not player_name:
        emit("message", "Error: No player name received.", to=sid)
        return

    # --- 1. Get player's old room (if they exist) ---
    old_player_info = game_state.ACTIVE_PLAYERS.get(sid)
    old_room_id = old_player_info.get("current_room_id") if old_player_info else None
    
    # --- 2. Execute the command ---
    # We pass the SID to execute_command so it can update the player's state
    result_data = execute_command(player_name, command_line, sid)

    # --- 3. Get player's new room (from the updated state) ---
    new_player_info = game_state.ACTIVE_PLAYERS.get(sid)
    new_room_id = new_player_info.get("current_room_id") if new_player_info else None

    # --- 4. Handle Room changes and broadcasts ---
    if new_room_id and old_room_id != new_room_id:
        # Player has moved or just logged in
        if old_room_id:
            leave_room(old_room_id, sid=sid)
            emit("message", f"{player_name} leaves.", to=old_room_id)
        
        join_room(new_room_id, sid=sid)
        emit("message", f"{player_name} arrives.", to=new_room_id, skip_sid=sid) # skip_sid prevents echo

    # --- 5. Send the command result *back to the sender* ---
    emit("command_response", result_data, to=sid)


if __name__ == "__main__":
    print("[SERVER START] Initializing database...")
    database = db.get_db()
    
    if database is not None:
        print("[SERVER START] Loading all rooms into game state cache...")
        game_state.GAME_ROOMS = db.fetch_all_rooms()
        print(f"[SERVER START] Successfully cached {len(game_state.GAME_ROOMS)} rooms.")
    else:
        print("[SERVER START] ERROR: Could not connect to database.")
    
    # --- NEW: Start the background tick thread ---
    threading.Thread(target=game_tick_thread, daemon=True).start()
    
    # --- NEW: Run the SocketIO server ---
    print("[SERVER START] Running SocketIO server on http://127.0.0.1:8000")
    # allow_unsafe_werkzeug=True is needed for the latest Flask versions
    socketio.run(app, port=8000, debug=True, use_reloader=False, allow_unsafe_werkzeug=True)