# mud_backend/app.py
import eventlet
eventlet.monkey_patch(thread=False)

import sys
import os
import time
import datetime
import threading 
import queue 

from flask import Flask, request, render_template, session
from flask_socketio import SocketIO, emit, join_room

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mud_backend.core.command_executor import execute_command
from mud_backend.core.game_loop_handler import check_and_run_game_tick
from mud_backend.core.game_state import World
from mud_backend.core import db
from mud_backend.core import scripting
from mud_backend.core import combat_system 
from mud_backend.core.game_loop import monster_ai
from mud_backend import config
from mud_backend.core.room_handler import _handle_npc_idle_dialogue
from mud_backend.core.worker import WorkerManager

template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mud_frontend', 'templates'))
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mud_frontend', 'static'))
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.config['SECRET_KEY'] = 'your-very-secret-key-please-change-me!'

# Use eventlet for asynchronous networking
socketio = SocketIO(app, async_mode='eventlet')
game_event_queue = queue.Queue()

# --- GLOBAL DEFINITIONS ---
# These define the structure, but do not START anything yet.
print("[SERVER INIT] Defining World...")
world = World()
world.socketio = socketio 
world.app = app 
# Initialize the manager but DO NOT start it here
world.worker_manager = WorkerManager() 

@app.route("/")
def index():
    return render_template("index.html")

def persistence_task(world_instance: World):
    """Saves dirty players to DB every 60 seconds."""
    print("[SERVER] Persistence task started.")
    while True:
        socketio.sleep(60) 
        count = 0
        active_players = world_instance.get_all_players_info()
        for name, data in active_players:
            player = data.get("player_obj")
            if player and player._is_dirty:
                db.save_game_state(player)
                player._is_dirty = False
                count += 1
        if count > 0:
            print(f"[PERSISTENCE] Saved {count} players to database.")

def game_loop_task(world_instance: World):
    print("[SERVER START] Game Loop task started.")
    with app.app_context():
        while True:
            # 1. Process Event Queue
            events_processed = 0
            while not game_event_queue.empty() and events_processed < 50:
                try:
                    func, args = game_event_queue.get_nowait()
                    func(**args)
                    events_processed += 1
                except queue.Empty: break
                except Exception as e:
                    print(f"[GAME LOOP ERROR] {e}")
                    import traceback
                    traceback.print_exc()
            
            # Yield to allow heartbeats
            socketio.sleep(0)

            current_time = time.time()
            log_time = datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S')
            
            def broadcast_to_room(room_id, message, msg_type, skip_sid=None):
                world_instance.broadcast_to_room(room_id, message, msg_type, skip_sid)
            def send_to_player(player_name, message, msg_type):
                world_instance.send_message_to_player(player_name.lower(), message, msg_type)
            def send_vitals_to_player(player_name, vitals_data):
                p_info = world_instance.get_player_info(player_name.lower())
                if p_info and p_info.get("sid"):
                    socketio.emit("update_vitals", vitals_data, to=p_info["sid"])

            # 2. Process Player Queues
            active_players = world_instance.get_all_players_info()
            for player_key, p_info in active_players:
                player_obj = p_info.get("player_obj")
                sid = p_info.get("sid")
                if player_obj and player_obj.command_queue:
                    combat_state = world_instance.get_combat_state(player_key)
                    in_rt = False
                    if combat_state and current_time < combat_state.get("next_action_time", 0):
                         in_rt = True
                    if not in_rt:
                        cmd_to_run = player_obj.command_queue.pop(0)
                        result_data = execute_command(world_instance, player_obj.name, cmd_to_run, sid)
                        socketio.emit("command_response", result_data, to=sid)

            # 3. Combat Tick
            combat_system.process_combat_tick(world_instance, broadcast_to_room, send_to_player, send_vitals_to_player)
            
            # 4. Monster Tick
            if current_time - world_instance.last_monster_tick_time >= config.MONSTER_TICK_INTERVAL_SECONDS:
                world_instance.last_monster_tick_time = current_time
                monster_log_prefix = f"{log_time} - MONSTER_TICK"
                monster_ai.process_monster_ai(world_instance, monster_log_prefix, broadcast_to_room)
                monster_ai.process_monster_ambient_messages(world_instance, monster_log_prefix, broadcast_to_room)

            # 5. Global Tick
            did_global_tick = check_and_run_game_tick(
                world_instance, broadcast_to_room, send_to_player, send_vitals_to_player
            )
            if did_global_tick: socketio.emit('tick')
            
            socketio.sleep(0.05) 

@socketio.on('connect')
def handle_connect():
    sid = request.sid
    print(f"[CONNECTION] Client connected: {sid}")
    session['state'] = 'auth_user'
    emit("prompt_username", to=sid)

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    player_name = session.get('player_name')
    player_info = None
    if player_name:
        player_info = world.remove_player(player_name.lower()) 
    if player_name and player_info:
        room_id = player_info.get("current_room_id")
        if room_id:
            emit("message", f'<span class="keyword" data-name="{player_name}">{player_name}</span> disappears.', to=room_id)
        player_obj = player_info.get("player_obj")
        if player_obj: db.save_game_state(player_obj)
    else:
        print(f"[CONNECTION] Unauthenticated client disconnected: {sid}")

def process_command_worker(player_name, command, sid, old_room_id=None):
    try:
        result_data = execute_command(world, player_name, command, sid)
        new_player_info = world.get_player_info(player_name.lower())
        new_room_id = new_player_info.get("current_room_id") if new_player_info else None
        player_obj = new_player_info.get("player_obj") if new_player_info else None
        
        if new_room_id and old_room_id and old_room_id != new_room_id:
            world.socketio.server.leave_room(sid, old_room_id)
            
            # --- FIX: Use custom leave message if present ---
            leave_msg = result_data.get("leave_message")
            if not leave_msg:
                leave_msg = "leaves."
            
            world.broadcast_to_room(old_room_id, f'<span class="keyword" data-name="{player_name}">{player_name}</span> {leave_msg}', "message") 
            # ------------------------------------------------
            
            world.socketio.server.enter_room(sid, new_room_id)
            world.broadcast_to_room(new_room_id, f'<span class="keyword" data-name="{player_name}">{player_name}</span> arrives.', "message", skip_sid=sid)
            socketio.start_background_task(_handle_npc_idle_dialogue, world, player_name, new_room_id)
            
            real_active_room = world.get_active_room_safe(new_room_id)
            if real_active_room and real_active_room.triggers:
                on_enter_script = real_active_room.triggers.get("on_enter")
                if on_enter_script:
                    scripting.execute_script(world, player_obj, real_active_room, on_enter_script)
        
        socketio.emit("command_response", result_data, to=sid)

        if player_obj and new_room_id:
            room_data = world.get_room(new_room_id)
            if room_data:
                for obj in room_data.get("objects", []):
                    if (obj.get("is_monster") or obj.get("is_npc")):
                         monster_ai._check_and_start_npc_combat(world, obj, new_room_id)

    except Exception as e:
        print(f"Error in worker: {e}")
        import traceback
        traceback.print_exc()

@socketio.on('command')
def handle_command_event(data):
    sid = request.sid
    command = data.get("command", "").strip()
    state = session.get('state', 'auth_user')
    
    if state == 'auth_user':
        username = command
        if not username:
            emit("prompt_username", to=sid)
            return
        session['username'] = username
        session['state'] = 'auth_pass'
        emit("prompt_password", to=sid)

    elif state == 'auth_pass':
            password = command
            username = session.get('username')
            if not password or not username:
                session['state'] = 'auth_user'
                emit("login_failed", "Error.", to=sid)
                emit("prompt_username", to=sid)
                return
            account = db.fetch_account(username)
            if not account:
                db.create_account(username, password)
                session['state'] = 'char_create_name'
                emit("prompt_create_character", to=sid)
            elif db.check_account_password(account, password):
                chars = db.fetch_characters_for_account(username)
                if not chars:
                    session['state'] = 'char_create_name'
                    emit("message", "No characters found.", to=sid)
                    emit("prompt_create_character", to=sid)
                else:
                    session['characters'] = [c['name'] for c in chars]
                    session['state'] = 'char_select'
                    emit("show_char_list", {"chars": session['characters']}, to=sid)
            else:
                emit("login_failed", "Invalid password.", to=sid)
                session['state'] = 'auth_user'
                emit("prompt_username", to=sid)

    elif state == 'char_create_name':
        new_char_name = command.capitalize()
        username = session.get('username')
        if not new_char_name.isalpha() or len(new_char_name) < 3:
            emit("name_invalid", "Invalid name.", to=sid)
            return
        if db.fetch_player_data(new_char_name):
            emit("name_taken", to=sid)
            return
        session['player_name'] = new_char_name
        session['state'] = 'in_game'
        result_data = execute_command(world, new_char_name, "look", sid, account_username=username)
        emit("command_response", result_data, to=sid)
        
    elif state == 'char_select':
        char_name = command.capitalize()
        if char_name.lower() == 'create':
            session['state'] = 'char_create_name'
            emit("prompt_create_character", to=sid)
            return
        if char_name not in session.get('characters', []):
            emit("char_invalid", "Invalid character.", to=sid)
            return
        session['player_name'] = char_name
        session['state'] = 'in_game'
        result_data = execute_command(world, char_name, "look", sid)
        player_info = world.get_player_info(char_name.lower())
        if player_info:
            room_id = player_info.get("current_room_id")
            if room_id:
                join_room(room_id, sid=sid)
                world.broadcast_to_room(room_id, f"{char_name} arrives.", "message", skip_sid=sid)
        emit("command_response", result_data, to=sid)

    elif state == 'in_game':
        player_name = session.get('player_name')
        if not player_name:
            session['state'] = 'auth_user'
            emit("login_failed", "Session error.", to=sid)
            return
        old_player_info = world.get_player_info(player_name.lower())
        old_room_id = old_player_info.get("current_room_id") if old_player_info else None
        game_event_queue.put((process_command_worker, {"player_name": player_name, "command": command, "sid": sid, "old_room_id": old_room_id}))

if __name__ == "__main__":
    # 1. Start Workers (Only in main process)
    print("[SERVER START] Starting Workers...")
    world.worker_manager.start()
    
    # 2. Load Data (Only in main process)
    print("[SERVER START] Loading Data...")
    world.load_all_data(db)
    
    # 3. Wire Events (Only in main process)
    world.event_bus.subscribe("save_room", lambda room: db.save_room_state(room))
    world.event_bus.subscribe("update_band_xp", lambda player_name, amount: db.update_player_band_xp_bank(player_name, amount))

    # 4. Start Background Tasks (Only in main process)
    print("[SERVER START] Starting Background Tasks...")
    socketio.start_background_task(game_loop_task, world)
    socketio.start_background_task(persistence_task, world)
    
    # 5. Run Server
    print("[SERVER START] Running SocketIO server on http://127.0.0.1:8024")
    socketio.run(app, host='0.0.0.0', port=8024, debug=True, use_reloader=False)