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

# --- REFACTORED: Import World class, not global state ---
from mud_backend.core.game_state import World
from mud_backend.core import db
# --- END REFACTOR ---

from mud_backend.core import combat_system 
from mud_backend.core.game_loop import monster_ai
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

# --- REFACTORED: Create the World instance ---
print("[SERVER START] Initializing database...")
database = db.get_db()
print("[SERVER START] Creating World instance...")
world = World()
world.socketio = socketio # <-- THIS IS THE FIX
if database is not None:
    world.load_all_data(database)
else:
     print("[SERVER START] ERROR: Could not connect to database. World is empty.")
# --- END REFACTOR ---


@app.route("/")
def index():
    return render_template("index.html")

# --- REFACTORED: Pass 'world' object to the thread ---
def game_tick_thread(world_instance: World):
    """
    A background thread that runs various game loops at different intervals.
    """
    print("[SERVER START] Game Tick thread started.")
    with app.app_context():
        while True:
            current_time = time.time()

            def broadcast_to_room(room_id, message, msg_type, skip_sid=None):
                if skip_sid:
                    socketio.emit("message", message, to=room_id, skip_sid=skip_sid)
                else:
                    socketio.emit("message", message, to=room_id)
                
            def send_to_player(player_name, message, msg_type):
                # --- REFACTORED: Use world object ---
                player_info = world_instance.get_player_info(player_name.lower())
                # --- END REFACTOR ---
                
                if player_info:
                    sid = player_info.get("sid")
                    if sid:
                        socketio.emit("message", message, to=sid)

            # --- 1. FAST TICK: Combat (approx every 1s via sleep at end) ---
            # --- REFACTORED: Pass world object ---
            combat_system.process_combat_tick(
                world=world_instance,
                broadcast_callback=broadcast_to_room,
                send_to_player_callback=send_to_player
            )
            
            # --- NEW: 1.b. FAST TICK: Pending Trade Timeouts (approx every 1s) ---
            if world_instance.pending_trades:
                expired_trades = []
                # Use list() to avoid mutation during iteration
                with world_instance.trade_lock:
                    trade_items = list(world_instance.pending_trades.items())
                
                for receiver_name, offer_data in trade_items:
                    if current_time - offer_data.get("offer_time", 0) > 30:
                        expired_trades.append((receiver_name, offer_data))
                
                for receiver_name, offer_data in expired_trades:
                    # Remove the trade first
                    world_instance.remove_pending_trade(receiver_name)
                    
                    giver_name = offer_data.get("from_player_name")
                    item_name = offer_data.get("item_name", "their offer")
                    trade_type = offer_data.get("trade_type", "give")

                    # Notify receiver
                    receiver_obj = world_instance.get_player_obj(receiver_name)
                    if receiver_obj:
                        receiver_obj.send_message(f"The offer from {giver_name} for {item_name} has expired.")
                        
                    # Notify giver
                    giver_obj = world_instance.get_player_obj(giver_name.lower())
                    if giver_obj:
                        if trade_type == "exchange":
                            giver_obj.send_message(f"Your exchange with {receiver_name} for {item_name} has expired.")
                        else:
                            giver_obj.send_message(f"Your offer to {receiver_name} for {item_name} has expired.")
            # --- END NEW: Trade Timeout ---
            
            # --- 2. INDEPENDENT TICK: Monster AI Movement ---
            # --- REFACTORED: Use world attributes for timers ---
            if current_time - world_instance.last_monster_tick_time >= config.MONSTER_TICK_INTERVAL_SECONDS:
                world_instance.last_monster_tick_time = current_time
                # --- END REFACTOR ---
                log_time = datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S')
                # --- REFACTORED: Pass world object ---
                monster_ai.process_monster_ai(
                    world=world_instance,
                    log_time_prefix=f"{log_time} - MONSTER_TICK",
                    broadcast_callback=broadcast_to_room
                )

            # --- 3. SLOW TICK: Global Game Tick (30s) ---
            # --- REFACTORED: Pass world object ---
            did_global_tick = check_and_run_game_tick(
                world=world_instance,
                broadcast_callback=broadcast_to_room,
                send_to_player_callback=send_to_player 
            )

            if did_global_tick:
                # --- XP ABSORPTION & HP REGEN (Now tied strictly to the 30s tick) ---
                # --- REFACTORED: Use world object ---
                active_players_list = world_instance.get_all_players_info()
                # --- END REFACTOR ---
                
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

            time.sleep(1.0) # Main loop heartbeat

@socketio.on('connect')
def handle_connect():
    print(f"[CONNECTION] Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    player_name_to_remove = None
    player_info = None

    # --- REFACTORED: Use world object ---
    for name, data in world.get_all_players_info():
        if data["sid"] == sid:
            player_info = world.remove_player(name)
            if player_info:
                player_name_to_remove = name
                break
    # --- END REFACTOR ---
            
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

    # --- REFACTORED: Use world object ---
    old_player_info = world.get_player_info(player_name.lower())
    old_room_id = old_player_info.get("current_room_id") if old_player_info else None
    
    result_data = execute_command(world, player_name, command_line, sid)

    new_player_info = world.get_player_info(player_name.lower())
    # --- END REFACTOR ---
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
    # --- REFACTORED: Use world object ---
    player_state = world.get_combat_state(player_id)
    if player_state and player_state.get("state_type") == "combat":
        player_in_combat = True
    
    if new_room_id and new_player_info and not player_in_combat:
        room_data = world.get_room(new_room_id)
        # --- END REFACTOR ---
        if room_data:
            player_obj = new_player_info.get("player_obj")
            live_room_objects = player_obj.room.objects if player_obj and hasattr(player_obj, 'room') else room_data.get("objects", [])

            for obj in live_room_objects:
                if obj.get("is_aggressive") and obj.get("is_monster"):
                    monster_uid = obj.get("uid")
                    if not monster_uid: continue

                    # --- REFACTORED: Use world object ---
                    is_defeated = world.get_defeated_monster(monster_uid) is not None
                    monster_state = world.get_combat_state(monster_uid)
                    monster_in_combat = monster_state and monster_state.get("state_type") == "combat"
                        
                    if monster_uid and not is_defeated and not monster_in_combat:
                        emit("message", f"The **{obj['name']}** notices you and attacks!", to=sid)
                        current_time = time.time()
                        world.set_combat_state(monster_uid, {
                            "state_type": "combat", 
                            "target_id": player_id,
                            "next_action_time": current_time,
                            "current_room_id": new_room_id
                        })
                        if world.get_monster_hp(monster_uid) is None:
                            world.set_monster_hp(monster_uid, obj.get("max_hp", 1))
                        # --- END REFACTOR ---
                        break 

if __name__ == "__main__":
    # --- REFACTORED: Data loading is now done by the World instance ---
    # (The world instance was already created above)
    
    # --- REFACTORED: Pass 'world' to the thread ---
    threading.Thread(target=game_tick_thread, args=(world,), daemon=True).start()
    # --- END REFACTOR ---
    
    print("[SERVER START] Running SocketIO server on http://127.0.0.1:8000")
    socketio.run(app, port=8000, debug=True, use_reloader=False, allow_unsafe_werkzeug=True)