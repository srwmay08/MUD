# mud_backend/app.py
import sys
import os
import time
import datetime
import threading 
import math
from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room

# --- (Imports are unchanged) ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- UPDATED IMPORTS ---
from mud_backend.core.command_executor import execute_command
from mud_backend.core.game_loop_handler import check_and_run_game_tick # <-- CHANGED
# ---
from mud_backend.core import game_state
from mud_backend.core import db
from mud_backend.core import combat_system 
from mud_backend import config # <-- NEW IMPORT

# --- NEW HELPER: Determine Absorption Room Type ---
def _get_absorption_room_type(room_id: str) -> str:
    """Determines the room type for experience absorption."""
    # Check for "on node" (highest priority)
    if room_id in getattr(config, 'NODE_ROOM_IDS', []):
        return "on_node"
    # Check for "in town"
    if room_id in getattr(config, 'TOWN_ROOM_IDS', []):
        return "in_town"
    # Default to "other"
    return "other"
# --- END NEW HELPER ---

# --- (Flask App Setup is Unchanged) ---
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mud_frontend', 'templates'))
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mud_frontend', 'static'))
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.config['SECRET_KEY'] = 'your-very-secret-key!'
socketio = SocketIO(app)

# --- (index route is unchanged) ---
@app.route("/")
def index():
    return render_template("index.html")

# ---
# UPDATED: BACKGROUND GAME TICK THREAD
# ---
def game_tick_thread():
    """
    A background thread that runs the game tick every N seconds.
    """
    print("[SERVER START] Game Tick thread started.")
    with app.app_context():
        while True:
            # --- Broadcast to a room (for weather, etc.) ---
            # --- THIS IS THE FIX 1 ---
            def broadcast_to_room(room_id, message, msg_type, skip_sid=None):
                if skip_sid:
                    socketio.emit("message", message, to=room_id, skip_sid=skip_sid)
                else:
                    socketio.emit("message", message, to=room_id)
            # --- END FIX 1 ---
                
            # --- NEW: Send a message to a specific player ---
            def send_to_player(player_name, message, msg_type):
                player_info = None
                # --- ADD LOCK ---
                with game_state.PLAYER_LOCK:
                    player_info = game_state.ACTIVE_PLAYERS.get(player_name.lower())
                # --- END LOCK ---
                
                if player_info:
                    sid = player_info.get("sid")
                    if sid:
                        socketio.emit("message", message, to=sid)
            # ---

            # --- Call the function we actually imported: 'check_and_run_game_tick'
            check_and_run_game_tick(broadcast_to_room)
            # --- END FIX ---
            
            # --- Run the combat tick with *both* callbacks ---
            # This function will manage its own locks internally
            combat_system.process_combat_tick(
                broadcast_callback=broadcast_to_room,
                send_to_player_callback=send_to_player
            )

            # --- REVISED: XP ABSORPTION & HP REGEN LOGIC ---
            
            # Create a snapshot of the player list to iterate over
            # This prevents holding the lock during the entire (slow) loop
            active_players_list = []
            # --- ADD LOCK ---
            with game_state.PLAYER_LOCK:
                active_players_list = list(game_state.ACTIVE_PLAYERS.items())
            # --- END LOCK ---
            
            # Now we iterate over the safe snapshot
            for player_name_lower, player_data in active_players_list:
                player_obj = player_data.get("player_obj")
                
                if not player_obj:
                    continue

                # 1. Absorb XP (which also handles CON recovery)
                if player_obj.unabsorbed_exp > 0:
                    # --- MODIFIED: Pass the calculated room type to enable rate logic ---
                    room_id = player_obj.current_room_id
                    room_type = _get_absorption_room_type(room_id)
                    player_obj.absorb_exp_pulse(room_type=room_type)
                    # --- END MODIFIED ---
                    
                # 2. Regenerate HP
                if player_obj.hp < player_obj.max_hp:
                    hp_to_regen = player_obj.hp_regeneration
                    if hp_to_regen > 0:
                        player_obj.hp = min(player_obj.max_hp, player_obj.hp + hp_to_regen)
                        # We don't message the player on every tick,
                        # it would be too spammy.
                        
            # --- END REVISED LOGIC ---
            
            socketio.emit('tick')
            
            # Reads interval from game_state (which gets it from config)
            time.sleep(game_state.TICK_INTERVAL_SECONDS)

# ---
# (WebSocket Event Handlers are unchanged)
# ---

@socketio.on('connect')
def handle_connect():
    print(f"[CONNECTION] Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    player_name_to_remove = None
    player_info = None

    # --- ADD LOCK ---
    with game_state.PLAYER_LOCK:
        for name, data in game_state.ACTIVE_PLAYERS.items():
            if data["sid"] == sid:
                player_name_to_remove = name
                player_info = data
                break
        
        if player_name_to_remove and player_info:
            game_state.ACTIVE_PLAYERS.pop(player_name_to_remove, None)
    # --- END LOCK ---
            
    if player_name_to_remove and player_info:
        room_id = player_info["current_room_id"]
        print(f"[CONNECTION] Player {player_name_to_remove} disconnected: {sid}")
        disappears_message = f'<span class="keyword" data-name="{player_name_to_remove}" data-verbs="look">{player_name_to_remove}</span> disappears.'
        emit("message", disappears_message, to=room_id)
    else:
        print(f"[CONNECTION] Unknown client disconnected: {sid}")

@socketio.on('command')
def handle_command_event(data):
    sid = request.sid
    player_name = data.get("player_name")
    command_line = data.get("command", "")
    if not player_name:
        emit("message", "Error: No player name received.", to=sid)
        return

    old_player_info = None
    old_room_id = None
    # --- ADD LOCK ---
    with game_state.PLAYER_LOCK:
        old_player_info = game_state.ACTIVE_PLAYERS.get(player_name.lower())
        old_room_id = old_player_info.get("current_room_id") if old_player_info else None
    # --- END LOCK ---
    
    result_data = execute_command(player_name, command_line, sid)

    new_player_info = None
    new_room_id = None
    # --- ADD LOCK ---
    with game_state.PLAYER_LOCK:
        new_player_info = game_state.ACTIVE_PLAYERS.get(player_name.lower())
        new_room_id = new_player_info.get("current_room_id") if new_player_info else None
    # --- END LOCK ---
    
    # --- Movement Logic ---
    if new_room_id and old_room_id != new_room_id:
        if old_room_id:
            leave_room(old_room_id, sid=sid)
            leaves_message = f'<span class="keyword" data-name="{player_name}" data-verbs="look">{player_name}</span> leaves.'
            emit("message", leaves_message, to=old_room_id)
        
        join_room(new_room_id, sid=sid)
        arrives_message = f'<span class="keyword" data-name="{player_name}" data-verbs="look">{player_name}</span> arrives.'
        emit("message", arrives_message, to=new_room_id, skip_sid=sid)
        
    # ---
    # --- THIS IS THE FIX 2: Send command response *before* checking aggro
    # ---
    emit("command_response", result_data, to=sid)
    # --- END FIX 2 ---


    # ---
    # --- AGGRO CHECK (MOVED) ---
    # This logic is now OUTSIDE the movement block.
    # It will run on *every command* (look, inv, get, etc.)
    # ---
    
    # Only check for aggro if the player is in a room and *not* already in combat
    player_id = player_name.lower()
    
    player_in_combat = False
    # --- ADD LOCK ---
    with game_state.COMBAT_LOCK:
        player_in_combat = player_id in game_state.COMBAT_STATE
    # --- END LOCK ---
    
    if new_room_id and new_player_info and not player_in_combat:
        
        room_data = game_state.GAME_ROOMS.get(new_room_id)
        if room_data:
            player_obj = new_player_info.get("player_obj")
            
            # --- FIX: We must get the "live" room objects from the player object ---
            # (Because execute_command() puts the filtered list in player.room.objects)
            if player_obj and hasattr(player_obj, 'room'):
                live_room_objects = player_obj.room.objects
            else:
                # Fallback, though less ideal
                live_room_objects = room_data.get("objects", [])
            # --- END FIX ---

            for obj in live_room_objects:
                if obj.get("is_aggressive") and obj.get("is_monster"):
                    monster_id = obj.get("monster_id")
                    if not monster_id:
                        continue

                    # --- ADD LOCK ---
                    # We must check and update combat state atomically
                    with game_state.COMBAT_LOCK:
                        is_defeated = monster_id in game_state.DEFEATED_MONSTERS
                        monster_in_combat = monster_id in game_state.COMBAT_STATE
                        
                        # Check if monster is alive and not already fighting
                        if monster_id and not is_defeated and not monster_in_combat:
                            
                            # ---
                            # --- START COMBAT (MODIFIED) ---
                            # ---
                            
                            # --- THIS IS THE FIX: Notify player of aggro ---
                            emit("message", f"The **{obj['name']}** notices you and attacks!", to=sid)
                            # --- END FIX ---
                            
                            current_time = time.time()
                            
                            # --- THIS IS THE FIX: ONLY add the monster to combat. ---
                            # --- The player will not auto-attack. ---
                            monster_rt = combat_system.calculate_roundtime(obj.get("stats", {}).get("AGI", 50))
                            game_state.COMBAT_STATE[monster_id] = {
                                "target_id": player_id,
                                "next_action_time": current_time, # Monster attacks immediately
                                "current_room_id": new_room_id
                            }
                            if monster_id not in game_state.RUNTIME_MONSTER_HP:
                                game_state.RUNTIME_MONSTER_HP[monster_id] = obj.get("max_hp", 1)
                            
                            # --- END FIX ---
                            
                            # Only aggro one monster at a time
                            break 
                    # --- END LOCK ---
    # --- END AGGRO CHECK ---

    # --- MOVED: This is now sent *before* the aggro check ---
    # emit("command_response", result_data, to=sid)


if __name__ == "__main__":
    # --- (Startup logic is unchanged) ---
    print("[SERVER START] Initializing database...")
    database = db.get_db()
    if database is not None:
        print("[SERVER START] Loading all rooms into game state cache...")
        game_state.GAME_ROOMS = db.fetch_all_rooms()
        print("[SERVER START] Loading all monster templates...")
        game_state.GAME_MONSTER_TEMPLATES = db.fetch_all_monsters()
        print("[SERVER START] Loading all loot tables...")
        game_state.GAME_LOOT_TABLES = db.fetch_all_loot_tables()
        print("[SERVER START] Loading all items...")
        game_state.GAME_ITEMS = db.fetch_all_items()
        print("[SERVER START] Loading level table...")
        game_state.GAME_LEVEL_TABLE = db.fetch_all_levels()
        print("[SERVER START] Loading all skills...")
        game_state.GAME_SKILLS = db.fetch_all_skills()
        print(f"[SERVER START] Successfully cached {len(game_state.GAME_ROOMS)} rooms, "
              f"{len(game_state.GAME_MONSTER_TEMPLATES)} monsters, "
              f"{len(game_state.GAME_LOOT_TABLES)} loot tables, "
              f"{len(game_state.GAME_ITEMS)} items, "
              f"and {len(game_state.GAME_SKILLS)} skills.")
    else:
        print("[SERVER START] ERROR: Could not connect to database.")
    
    threading.Thread(target=game_tick_thread, daemon=True).start()
    
    print("[SERVER START] Running SocketIO server on http://127.0.0.1:8000")
    socketio.run(app, port=8000, debug=True, use_reloader=False, allow_unsafe_werkzeug=True)