# mud_backend/app.py
import sys
import os
import time
import datetime
import threading 
import math
# --- MODIFIED: Import session ---
from flask import Flask, request, jsonify, render_template, session
from flask_socketio import SocketIO, emit, join_room, leave_room
# --- END MODIFIED ---

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
# --- MODIFIED: Secret key is required for sessions ---
app.config['SECRET_KEY'] = 'your-very-secret-key-please-change-me!'
socketio = SocketIO(app)
# --- END MODIFIED ---

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
                        # Use send_message() which appends to the player's list
                        # The next command response will send it.
                        receiver_obj.send_message(f"The offer from {giver_name} for {item_name} has expired.")
                        
                    # Notify giver
                    giver_obj = world_instance.get_player_obj(giver_name.lower())
                    if giver_obj:
                        giver_obj.send_message(f"Your offer to {receiver_name} for {item_name} has expired.")
            # --- END NEW: Trade Timeout ---

            # --- MODIFIED: 1.c. FAST TICK: Ability Cooldowns ONLY ---
            # --- (Regen is now handled in the 30s 'slow' tick) ---
            active_players_list = world_instance.get_all_players_info()
            for player_name_lower, player_data in active_players_list:
                player_obj = player_data.get("player_obj")
                if not player_obj:
                    continue
                
                # --- Ability Cooldown Checks (e.g., Spellup) ---
                # Check if 24 hours (86400s) has passed since last spellup
                if player_obj.spellup_uses_today > 0:
                    if current_time - player_obj.last_spellup_use_time > 86400:
                         player_obj.spellup_uses_today = 0
            # --- END MODIFIED: Ability Cooldowns ---
            
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

            # --- THIS IS THE FIX: Uncommented this block ---
            if did_global_tick:
               socketio.emit('tick')
            # --- END FIX ---

            time.sleep(1.0) # Main loop heartbeat

@socketio.on('connect')
def handle_connect():
    sid = request.sid
    print(f"[CONNECTION] Client connected: {sid}")
    # --- NEW: Start the login flow ---
    session['state'] = 'auth_user'
    emit("prompt_username", to=sid)
    # --- END NEW ---

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    # --- MODIFIED: Check session for player name ---
    player_name_to_remove = session.get('player_name')
    player_info = None
    
    if player_name_to_remove:
        player_info = world.remove_player(player_name_to_remove.lower())
    # --- END MODIFIED ---
            
    if player_name_to_remove and player_info:
        room_id = player_info["current_room_id"]
        print(f"[CONNECTION] Player {player_name_to_remove} disconnected: {sid}")
        disappears_message = f'<span class="keyword" data-name="{player_name_to_remove}" data-verbs="look">{player_name_to_remove}</span> disappears.'
        emit("message", disappears_message, to=room_id)
    else:
        print(f"[CONNECTION] Unauthenticated client disconnected: {sid}")

# ---
# --- NEW: MAJOR REFACTOR OF COMMAND HANDLING
# ---
@socketio.on('command')
def handle_command_event(data):
    sid = request.sid
    command = data.get("command", "").strip()
    state = session.get('state', 'auth_user')

    try:
        if state == 'auth_user':
            # --- 1. User sent their username ---
            username = command
            if not username:
                emit("prompt_username", to=sid)
                return
            
            session['username'] = username
            session['state'] = 'auth_pass'
            emit("prompt_password", to=sid)

        elif state == 'auth_pass':
            # --- 2. User sent their password ---
            password = command
            username = session.get('username')
            if not password or not username:
                session['state'] = 'auth_user'
                emit("login_failed", "Error. Please start over.\n", to=sid)
                emit("prompt_username", to=sid)
                return

            account = db.fetch_account(username)
            if not account:
                # --- Create new account ---
                print(f"[AUTH] New account creation: {username}")
                db.create_account(username, password)
                session['state'] = 'char_create_name'
                emit("prompt_create_character", to=sid)
            
            elif db.check_account_password(account, password):
                # --- Successful login ---
                print(f"[AUTH] Successful login: {username}")
                chars = db.fetch_characters_for_account(username)
                if not chars:
                    session['state'] = 'char_create_name'
                    emit("prompt_create_character", to=sid)
                else:
                    session['characters'] = [c['name'] for c in chars]
                    session['state'] = 'char_select'
                    emit("show_char_list", {"chars": session['characters']}, to=sid)
            else:
                # --- Failed login ---
                print(f"[AUTH] Failed login: {username}")
                session['state'] = 'auth_user'
                emit("login_failed", "Invalid username or password.\n", to=sid)
                emit("prompt_username", to=sid)
        
        elif state == 'char_create_name':
            # --- 3a. User is creating a new character ---
            new_char_name = command.capitalize()
            username = session.get('username')
            
            if not new_char_name or not new_char_name.isalpha() or len(new_char_name) < 3:
                emit("name_invalid", "Name must be at least 3 letters and contain no spaces or numbers.", to=sid)
                return

            if db.fetch_player_data(new_char_name):
                emit("name_taken", to=sid)
                return
            
            # Name is valid and available
            print(f"[AUTH] Account {username} creating new character: {new_char_name}")
            session['player_name'] = new_char_name
            session['state'] = 'in_game'
            
            # --- Call execute_command for the *first time* ---
            # We pass the account_username so the new player object gets linked
            result_data = execute_command(
                world, 
                new_char_name, 
                "look", # Start them with a "look"
                sid, 
                account_username=username
            )
            emit("command_response", result_data, to=sid)
            # Player is now in chargen

        elif state == 'char_select':
            # --- 3b. User is selecting a character ---
            char_name = command.capitalize()
            
            if char_name.lower() == 'create':
                session['state'] = 'char_create_name'
                emit("prompt_create_character", to=sid)
                return

            if char_name not in session.get('characters', []):
                emit("char_invalid", "That is not a valid character name.", to=sid)
                return
            
            # --- Check if character is already logged in ---
            if world.get_player_info(char_name.lower()):
                emit("char_invalid", "That character is already logged in.", to=sid)
                session['state'] = 'auth_user'
                emit("prompt_username", to=sid)
                return

            # --- Success! Log them in as this character ---
            print(f"[AUTH] Account {session['username']} logging in as: {char_name}")
            session['player_name'] = char_name
            session['state'] = 'in_game'
            
            # --- Call execute_command to load the player ---
            result_data = execute_command(world, char_name, "look", sid)
            
            # --- Handle room joining ---
            player_info = world.get_player_info(char_name.lower())
            if player_info:
                room_id = player_info.get("current_room_id")
                if room_id:
                    join_room(room_id, sid=sid)
                    arrives_message = f'<span class="keyword" data-name="{char_name}" data-verbs="look">{char_name}</span> arrives.'
                    emit("message", arrives_message, to=room_id, skip_sid=sid)
            
            emit("command_response", result_data, to=sid)

        elif state == 'in_game':
            # --- 4. User is IN THE GAME ---
            player_name = session.get('player_name')
            if not player_name:
                # Should not happen, but reset them
                session['state'] = 'auth_user'
                emit("login_failed", "Session error. Please log in again.\n", to=sid)
                emit("prompt_username", to=sid)
                return

            # --- This is the NORMAL command loop ---
            old_player_info = world.get_player_info(player_name.lower())
            old_room_id = old_player_info.get("current_room_id") if old_player_info else None
            
            result_data = execute_command(world, player_name, command, sid)

            new_player_info = world.get_player_info(player_name.lower())
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
            player_state = world.get_combat_state(player_id)
            if player_state and player_state.get("state_type") == "combat":
                player_in_combat = True
            
            if new_room_id and new_player_info and not player_in_combat:
                room_data = world.get_room(new_room_id)
                if room_data:
                    player_obj = new_player_info.get("player_obj")
                    live_room_objects = player_obj.room.objects if player_obj and hasattr(player_obj, 'room') else room_data.get("objects", [])

                    for obj in live_room_objects:
                        if obj.get("is_aggressive") and obj.get("is_monster"):
                            monster_uid = obj.get("uid")
                            if not monster_uid: continue

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
                                break
    except Exception as e:
        print(f"!!! CRITICAL ERROR in handle_command_event (state: {state}) !!!")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        # Attempt to reset the user
        session['state'] = 'auth_user'
        emit("login_failed", f"A server error occurred. Please log in again.\nError: {e}\n", to=sid)
        emit("prompt_username", to=sid)

# --- END REFACTOR ---


if __name__ == "__main__":
    # --- REFACTORED: Data loading is now done by the World instance ---
    # (The world instance was already created above)
    
    # --- REFACTORED: Pass 'world' to the thread ---
    threading.Thread(target=game_tick_thread, args=(world,), daemon=True).start()
    # --- END REFACTOR ---
    
    print("[SERVER START] Running SocketIO server on http://127.0.0.1:8000")
    socketio.run(app, port=8000, debug=True, use_reloader=False, allow_unsafe_werkzeug=True)