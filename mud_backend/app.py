# mud_backend/app.py
import sys
import os
import time
import datetime
import threading 
import math
import random
import queue 
from flask import Flask, request, jsonify, render_template, session
from flask_socketio import SocketIO, emit, join_room, leave_room

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mud_backend.core.command_executor import execute_command
from mud_backend.core.game_loop_handler import check_and_run_game_tick

from mud_backend.core.game_state import World
from mud_backend.core import db
from mud_backend.core import scripting

from mud_backend.core import combat_system 
from mud_backend.core.game_loop import monster_ai
from mud_backend import config

from mud_backend.core.quest_handler import get_active_quest_for_npc
from mud_backend.core.game_objects import Player
from mud_backend.core import faction_handler
from mud_backend.core.room_handler import _handle_npc_idle_dialogue


template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mud_frontend', 'templates'))
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mud_frontend', 'static'))
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.config['SECRET_KEY'] = 'your-very-secret-key-please-change-me!'
socketio = SocketIO(app)

# --- PHASE 2: EVENT QUEUE ---
game_event_queue = queue.Queue()
# ----------------------------

print("[SERVER START] Initializing database...")
database = db.get_db()
print("[SERVER START] Creating World instance...")
world = World()
world.socketio = socketio 
world.app = app 

if database is not None:
    world.load_all_data(database)
else:
     print("[SERVER START] ERROR: Could not connect to database. World is empty.")


@app.route("/")
def index():
    return render_template("index.html")


def persistence_thread(world_instance: World):
    """Saves dirty players to DB every 60 seconds."""
    print("[SERVER] Persistence thread started.")
    while True:
        time.sleep(60) 
        count = 0
        active_names = list(world_instance.active_players.keys())
        for name in active_names:
            p_info = world_instance.get_player_info(name)
            if not p_info: continue
            player = p_info.get("player_obj")
            if player and player._is_dirty:
                db.save_game_state(player)
                player._is_dirty = False
                count += 1
        if count > 0:
            print(f"[PERSISTENCE] Saved {count} players to database.")


def game_loop_thread(world_instance: World):
    """
    The Main Game Loop.
    Consumes the Event Queue AND runs game ticks.
    """
    print("[SERVER START] Game Loop thread started.")
    with app.app_context():
        while True:
            # 1. Process Event Queue (Up to 50 events per tick to prevent starvation)
            events_processed = 0
            while not game_event_queue.empty() and events_processed < 50:
                try:
                    func, args = game_event_queue.get_nowait()
                    func(**args)
                    events_processed += 1
                except queue.Empty:
                    break
                except Exception as e:
                    print(f"[GAME LOOP ERROR] {e}")
                    import traceback
                    traceback.print_exc()

            # 2. Run Game Logic (Ticks)
            current_time = time.time()
            log_time = datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S')
            
            # -- Callbacks (Local) --
            def broadcast_to_room(room_id, message, msg_type, skip_sid=None):
                world_instance.broadcast_to_room(room_id, message, msg_type, skip_sid)

            def send_to_player(player_name, message, msg_type):
                world_instance.send_message_to_player(player_name.lower(), message, msg_type)

            def send_vitals_to_player(player_name, vitals_data):
                p_info = world_instance.get_player_info(player_name.lower())
                if p_info:
                    sid = p_info.get("sid")
                    if sid:
                        socketio.emit("update_vitals", vitals_data, to=sid)

            # --- Player Queue Check (RT) ---
            active_player_keys = list(world_instance.active_players.keys())
            for player_key in active_player_keys:
                p_info = world_instance.get_player_info(player_key)
                if not p_info: continue
                player_obj = p_info.get("player_obj")
                sid = p_info.get("sid")
                
                if player_obj and player_obj.command_queue:
                    combat_state = world_instance.get_combat_state(player_key)
                    in_rt = False
                    if combat_state:
                        if current_time < combat_state.get("next_action_time", 0):
                            in_rt = True
                    
                    if not in_rt:
                        cmd_to_run = player_obj.command_queue.pop(0)
                        result_data = execute_command(world_instance, player_obj.name, cmd_to_run, sid)
                        socketio.emit("command_response", result_data, to=sid)

            # --- Combat Tick ---
            combat_system.process_combat_tick(
                world=world_instance,
                broadcast_callback=broadcast_to_room,
                send_to_player_callback=send_to_player,
                send_vitals_callback=send_vitals_to_player
            )
            
            # --- Trade Expiration ---
            if world_instance.pending_trades:
                expired_trades = []
                with world_instance.trade_lock:
                    trade_items = list(world_instance.pending_trades.items())
                
                for receiver_name, offer_data in trade_items:
                    if current_time - offer_data.get("offer_time", 0) > 30:
                        expired_trades.append((receiver_name, offer_data))
                
                for receiver_name, offer_data in expired_trades:
                    world_instance.remove_pending_trade(receiver_name)
                    giver_obj = world_instance.get_player_obj(offer_data.get("from_player_name", "").lower())
                    rec_obj = world_instance.get_player_obj(receiver_name)
                    if rec_obj: rec_obj.send_message("Trade offer expired.")
                    if giver_obj: giver_obj.send_message("Trade offer expired.")

            # --- Group Invite Expiration ---
            if world_instance.pending_group_invites:
                expired_invites = []
                with world_instance.group_lock:
                    invite_items = list(world_instance.pending_group_invites.items())
                for invitee_name, invite_data in invite_items:
                    if current_time - invite_data.get("time", 0) > 30:
                        expired_invites.append((invitee_name, invite_data))
                for invitee_name, invite_data in expired_invites:
                    world_instance.remove_pending_group_invite(invitee_name)
            
            # --- Buff/Spellup Expiration ---
            for player_name_lower, player_data in active_player_keys:
                 p_info = world_instance.get_player_info(player_name_lower)
                 if not p_info: continue
                 player_obj = p_info.get("player_obj")
                 if not player_obj: continue
                 
                 if player_obj.spellup_uses_today > 0:
                    if current_time - player_obj.last_spellup_use_time > 86400:
                         player_obj.spellup_uses_today = 0
                 
                 if player_obj.buffs:
                    expired_buffs = [key for key, data in player_obj.buffs.items() if current_time >= data.get("expires_at", 0)]
                    for key in expired_buffs:
                        player_obj.buffs.pop(key, None)
                        if key == "spirit_shield":
                            send_to_player(player_obj.name, "The dim aura fades from around you.", "message")

            # --- Monster Tick ---
            if current_time - world_instance.last_monster_tick_time >= config.MONSTER_TICK_INTERVAL_SECONDS:
                world_instance.last_monster_tick_time = current_time
                monster_log_prefix = f"{log_time} - MONSTER_TICK"
                monster_ai.process_monster_ai(world_instance, monster_log_prefix, broadcast_to_room)
                monster_ai.process_monster_ambient_messages(world_instance, monster_log_prefix, broadcast_to_room)

            # --- Band Payout ---
            if current_time - world_instance.last_band_payout_time >= 300:
                world_instance.last_band_payout_time = current_time
                with world_instance.player_lock:
                    for player_name, player_data in world_instance.get_all_players_info():
                        player_obj = player_data.get("player_obj")
                        if player_obj and player_obj.band_xp_bank > 0 and player_obj.death_sting_points == 0:
                            amount = player_obj.band_xp_bank
                            player_obj.band_xp_bank = 0
                            player_obj.add_field_exp(amount, is_band_share=True)
                            db.save_game_state(player_obj)

            # --- Global Tick (Regen, Env) ---
            did_global_tick = check_and_run_game_tick(
                world=world_instance,
                broadcast_callback=broadcast_to_room,
                send_to_player_callback=send_to_player,
                send_vitals_callback=send_vitals_to_player
            )
            if did_global_tick:
               socketio.emit('tick')

            time.sleep(0.05) 

@socketio.on('connect')
def handle_connect():
    sid = request.sid
    print(f"[CONNECTION] Client connected: {sid}")
    session['state'] = 'auth_user'
    emit("prompt_username", to=sid)

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    player_name_to_remove = session.get('player_name')
    player_info = None
    
    if player_name_to_remove:
        player_obj = world.get_player_obj(player_name_to_remove.lower())
        player_info = world.remove_player(player_name_to_remove.lower()) 
            
    if player_name_to_remove and player_info:
        room_id = player_info["current_room_id"]
        print(f"[CONNECTION] Player {player_name_to_remove} disconnected: {sid}")
        disappears_message = f'<span class="keyword" data-name="{player_name_to_remove}" data-verbs="look">{player_name_to_remove}</span> disappears.'
        emit("message", disappears_message, to=room_id)
        
        if player_obj:
            db.save_game_state(player_obj)
    else:
        print(f"[CONNECTION] Unauthenticated client disconnected: {sid}")


# --- WORKER FUNCTION ---
def process_command_worker(player_name, command, sid, old_room_id=None):
    """
    The actual logic to run inside the thread.
    Includes Phase 3 Script Triggering on Room Entry.
    """
    try:
        # Execute Logic
        result_data = execute_command(world, player_name, command, sid)
        
        # Post-Execution Logic (Room Switching & Aggro)
        new_player_info = world.get_player_info(player_name.lower())
        new_room_id = new_player_info.get("current_room_id") if new_player_info else None
        player_obj = new_player_info.get("player_obj") if new_player_info else None
        
        if new_room_id and old_room_id and old_room_id != new_room_id:
            leave_room(old_room_id, sid=sid)
            leaves_message = f'<span class="keyword" data-name="{player_name}" data-verbs="look">{player_name}</span> leaves.'
            world.broadcast_to_room(old_room_id, leaves_message, "message") 
            
            join_room(new_room_id, sid=sid)
            arrives_message = f'<span class="keyword" data-name="{player_name}" data-verbs="look">{player_name}</span> arrives.'
            world.broadcast_to_room(new_room_id, arrives_message, "message", skip_sid=sid)
            
            socketio.start_background_task(
                _handle_npc_idle_dialogue, 
                world, 
                player_name, 
                new_room_id
            )
            
            # --- PHASE 3: TRIGGER CHECK ("on_enter") ---
            # Optimization: World.active_rooms holds the actual objects.
            # We access the active room dictionary directly to get the object.
            real_active_room = world.active_rooms.get(new_room_id)
            
            if real_active_room and real_active_room.triggers:
                on_enter_script = real_active_room.triggers.get("on_enter")
                if on_enter_script:
                    # Execute Script
                    if config.DEBUG_MODE:
                        print(f"[SCRIPT] Triggering on_enter for {new_room_id}: {on_enter_script}")
                    scripting.execute_script(world, player_obj, real_active_room, on_enter_script)
            # -------------------------------------------
            
        socketio.emit("command_response", result_data, to=sid)

        # Aggro Checks
        if player_obj and new_room_id:
            player_id = player_name.lower()
            player_state = world.get_combat_state(player_id)
            player_in_combat = player_state and player_state.get("state_type") == "combat"
            
            room_data = world.get_room(new_room_id)
            if room_data:
                objects = room_data.get("objects", [])
                
                for obj in objects:
                    if not player_in_combat and (obj.get("is_monster") or obj.get("is_npc")):
                        monster_uid = obj.get("uid")
                        if not monster_uid: continue
                        
                        is_aggressive = obj.get("is_aggressive", False)
                        is_kos_to_player = faction_handler.is_player_kos_to_entity(player_obj, obj)
                        
                        is_defeated = world.get_defeated_monster(monster_uid) is not None
                        monster_state = world.get_combat_state(monster_uid)
                        monster_in_combat = monster_state and monster_state.get("state_type") == "combat"
                            
                        if (is_aggressive or is_kos_to_player) and not is_defeated and not monster_in_combat:
                            socketio.emit("message", f"The **{obj['name']}** notices you and attacks!", to=sid)
                            current_time = time.time()
                            world.set_combat_state(monster_uid, {
                                "state_type": "combat", 
                                "target_id": player_id,
                                "next_action_time": current_time,
                                "current_room_id": new_room_id
                            })
                            if world.get_monster_hp(monster_uid) is None:
                                world.set_monster_hp(monster_uid, obj.get("max_hp", 50))
                            
                            player_in_combat = True 
                    
                    if obj.get("is_monster") or obj.get("is_npc"):
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

    try:
        if state in ['auth_user', 'auth_pass', 'char_create_name', 'char_select']:
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

            game_event_queue.put((
                process_command_worker, 
                {
                    "player_name": player_name, 
                    "command": command, 
                    "sid": sid, 
                    "old_room_id": old_room_id
                }
            ))

    except Exception as e:
        print(f"Error in handle_command_event: {e}")
        import traceback
        traceback.print_exc()
        session['state'] = 'auth_user'
        emit("login_failed", "Server error.", to=sid)


if __name__ == "__main__":
    threading.Thread(target=game_loop_thread, args=(world,), daemon=True).start()
    threading.Thread(target=persistence_thread, args=(world,), daemon=True).start()
    
    print("[SERVER START] Running SocketIO server on http://127.0.0.1:8024")
    socketio.run(app, host='0.0.0.0', port=8024, debug=True, use_reloader=False, allow_unsafe_werkzeug=True)