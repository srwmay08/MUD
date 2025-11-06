# mud_backend/app.py
import sys
import os
import time
import datetime
import threading 
import math
from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mud_backend.core.command_executor import execute_command
from mud_backend.core.game_loop_handler import check_and_run_game_tick
from mud_backend.core import game_state
from mud_backend.core import db
from mud_backend.core import combat_system 
from mud_backend import config

def _get_absorption_room_type(room_id: str) -> str:
    """Determines the room type for experience absorption."""
    if room_id in getattr(config, 'NODE_ROOM_IDS', []):
        return "on_node"
    if room_id in getattr(config, 'TOWN_ROOM_IDS', []):
        return "in_town"
    return "other"

template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mud_frontend', 'templates'))
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mud_frontend', 'static'))
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.config['SECRET_KEY'] = 'your-very-secret-key!'
socketio = SocketIO(app)

@app.route("/")
def index():
    return render_template("index.html")

def game_tick_thread():
    """
    A background thread that runs the game tick every N seconds.
    """
    print("[SERVER START] Game Tick thread started.")
    with app.app_context():
        while True:
            def broadcast_to_room(room_id, message, msg_type, skip_sid=None):
                if skip_sid:
                    socketio.emit("message", message, to=room_id, skip_sid=skip_sid)
                else:
                    socketio.emit("message", message, to=room_id)
                
            def send_to_player(player_name, message, msg_type):
                player_info = None
                with game_state.PLAYER_LOCK:
                    player_info = game_state.ACTIVE_PLAYERS.get(player_name.lower())
                
                if player_info:
                    sid = player_info.get("sid")
                    if sid:
                        socketio.emit("message", message, to=sid)

            check_and_run_game_tick(
                broadcast_callback=broadcast_to_room,
                send_to_player_callback=send_to_player 
            )
            
            combat_system.process_combat_tick(
                broadcast_callback=broadcast_to_room,
                send_to_player_callback=send_to_player
            )

            # --- XP ABSORPTION & HP REGEN ---
            active_players_list = []
            with game_state.PLAYER_LOCK:
                active_players_list = list(game_state.ACTIVE_PLAYERS.items())
            
            for player_name_lower, player_data in active_players_list:
                player_obj = player_data.get("player_obj")
                if not player_obj:
                    continue

                if player_obj.unabsorbed_exp > 0:
                    room_id = player_obj.current_room_id
                    room_type = _get_absorption_room_type(room_id)
                    player_obj.absorb_exp_pulse(room_type=room_type)
                    
                if player_obj.hp < player_obj.max_hp:
                    hp_to_regen = player_obj.hp_regeneration
                    if hp_to_regen > 0:
                        player_obj.hp = min(player_obj.max_hp, player_obj.hp + hp_to_regen)
                        
            socketio.emit('tick')
            time.sleep(1.0) # Check every second, but only run tick if interval passed

@socketio.on('connect')
def handle_connect():
    print(f"[CONNECTION] Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    player_name_to_remove = None
    player_info = None

    with game_state.PLAYER_LOCK:
        for name, data in game_state.ACTIVE_PLAYERS.items():
            if data["sid"] == sid:
                player_name_to_remove = name
                player_info = data
                break
        if player_name_to_remove and player_info:
            game_state.ACTIVE_PLAYERS.pop(player_name_to_remove, None)
            
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
    with game_state.PLAYER_LOCK:
        old_player_info = game_state.ACTIVE_PLAYERS.get(player_name.lower())
        old_room_id = old_player_info.get("current_room_id") if old_player_info else None
    
    result_data = execute_command(player_name, command_line, sid)

    new_player_info = None
    new_room_id = None
    with game_state.PLAYER_LOCK:
        new_player_info = game_state.ACTIVE_PLAYERS.get(player_name.lower())
        new_room_id = new_player_info.get("current_room_id") if new_player_info else None
    
    if new_room_id and old_room_id != new_room_id:
        if old_room_id:
            leave_room(old_room_id, sid=sid)
            leaves_message = f'<span class="keyword" data-name="{player_name}" data-verbs="look">{player_name}</span> leaves.'
            emit("message", leaves_message, to=old_room_id)
        
        join_room(new_room_id, sid=sid)
        arrives_message = f'<span class="keyword" data-name="{player_name}" data-verbs="look">{player_name}</span> arrives.'
        emit("message", arrives_message, to=new_room_id, skip_sid=sid)
        
    emit("command_response", result_data, to=sid)

    # --- AGGRO CHECK ---
    player_id = player_name.lower()
    player_in_combat = False
    with game_state.COMBAT_LOCK:
        player_state = game_state.COMBAT_STATE.get(player_id)
        if player_state and player_state.get("state_type") == "combat":
            player_in_combat = True
    
    if new_room_id and new_player_info and not player_in_combat:
        room_data = game_state.GAME_ROOMS.get(new_room_id)
        if room_data:
            player_obj = new_player_info.get("player_obj")
            live_room_objects = player_obj.room.objects if player_obj and hasattr(player_obj, 'room') else room_data.get("objects", [])

            for obj in live_room_objects:
                if obj.get("is_aggressive") and obj.get("is_monster"):
                    monster_id = obj.get("monster_id")
                    if not monster_id: continue

                    with game_state.COMBAT_LOCK:
                        is_defeated = monster_id in game_state.DEFEATED_MONSTERS
                        monster_state = game_state.COMBAT_STATE.get(monster_id)
                        monster_in_combat = monster_state and monster_state.get("state_type") == "combat"
                        
                        if monster_id and not is_defeated and not monster_in_combat:
                            emit("message", f"The **{obj['name']}** notices you and attacks!", to=sid)
                            current_time = time.time()
                            game_state.COMBAT_STATE[monster_id] = {
                                "state_type": "combat", 
                                "target_id": player_id,
                                "next_action_time": current_time,
                                "current_room_id": new_room_id
                            }
                            if monster_id not in game_state.RUNTIME_MONSTER_HP:
                                game_state.RUNTIME_MONSTER_HP[monster_id] = obj.get("max_hp", 1)
                            break 

if __name__ == "__main__":
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
        print("[SERVER START] Data loaded.")
    else:
        print("[SERVER START] ERROR: Could not connect to database.")
    
    threading.Thread(target=game_tick_thread, daemon=True).start()
    
    print("[SERVER START] Running SocketIO server on http://127.0.0.1:8000")
    socketio.run(app, port=8000, debug=True, use_reloader=False, allow_unsafe_werkzeug=True)