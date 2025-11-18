# mud_backend/app.py
import sys
import os
import time
import datetime
import threading 
import math
import random
from flask import Flask, request, jsonify, render_template, session
from flask_socketio import SocketIO, emit, join_room, leave_room

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mud_backend.core.command_executor import execute_command
from mud_backend.core.game_loop_handler import check_and_run_game_tick

from mud_backend.core.game_state import World
from mud_backend.core import db

from mud_backend.core import combat_system 
from mud_backend.core.game_loop import monster_ai
from mud_backend import config

from mud_backend.core.quest_handler import get_active_quest_for_npc
from mud_backend.core.game_objects import Player
# --- NEW: Import faction handler ---
from mud_backend.core import faction_handler
# --- END NEW ---
# ---
# --- THIS IS THE FIX: Import the moved function
# ---
from mud_backend.core.room_handler import _handle_npc_idle_dialogue
# ---
# --- END FIX
# ---

# ---
# --- THIS IS THE FIX: This function is now in game_loop_handler
# ---
# (def _get_absorption_room_type... has been REMOVED)
# ---
# --- END FIX
# ---

template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mud_frontend', 'templates'))
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mud_frontend', 'static'))
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.config['SECRET_KEY'] = 'your-very-secret-key-please-change-me!'
socketio = SocketIO(app)

print("[SERVER START] Initializing database...")
database = db.get_db()
print("[SERVER START] Creating World instance...")
world = World()
world.socketio = socketio 
# ---
# --- THIS IS THE FIX
# ---
world.app = app # Give the world access to the Flask app context
# ---
# --- END FIX
# ---
if database is not None:
    world.load_all_data(database)
else:
     print("[SERVER START] ERROR: Could not connect to database. World is empty.")


@app.route("/")
def index():
    return render_template("index.html")

# ---
# --- THIS IS THE FIX: The function is now defined in room_handler.py
# ---
# (The local definition of _handle_npc_idle_dialogue has been removed)
# ---
# --- END FIX
# ---


def game_tick_thread(world_instance: World):
    """
    A background thread that runs various game loops at different intervals.
    """
    print("[SERVER START] Game Tick thread started.")
    with app.app_context():
        while True:
            current_time = time.time()
            log_time = datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S')
            log_prefix = f"{log_time} - GAME_TICK"

            def broadcast_to_room(room_id, message, msg_type, skip_sid=None):
                # ---
                # --- MODIFIED: Check AMBIENT and SHOWDEATH flags
                # ---
                is_ambient = msg_type in ["ambient", "ambient_move", "ambient_spawn", "ambient_decay"]
                is_death = msg_type == "combat_death"
                
                # --- THIS IS THE FIX: Support list/set of SIDs ---
                sids_to_skip = set()
                if isinstance(skip_sid, str):
                    sids_to_skip.add(skip_sid)
                elif isinstance(skip_sid, (list, set)):
                    sids_to_skip.update(skip_sid)
                # --- END FIX ---


                if not is_ambient and not is_death:
                    # Normal broadcast (e.g., combat hits)
                    
                    # --- THIS IS THE FIX: Iterate to allow skipping multiple SIDs ---
                    room_occupants = world_instance.get_all_players_info()
                    for p_name, p_data in room_occupants:
                        if p_data.get("current_room_id") == room_id:
                            p_sid = p_data.get("sid")
                            if p_sid and p_sid not in sids_to_skip:
                                socketio.emit(msg_type, message, to=p_sid)
                    return
                    # --- END FIX ---
                
                # Flag-checked broadcast: Iterate over players in the room
                for p_name, p_data in world_instance.get_all_players_info():
                    if p_data.get("current_room_id") == room_id:
                        player_obj = p_data.get("player_obj")
                        player_sid = p_data.get("sid")
                        
                        # --- THIS IS THE FIX: Use set for skipping ---
                        if not player_obj or not player_sid or player_sid in sids_to_skip:
                            continue
                        # --- END FIX ---

                        # Check flags
                        if is_ambient and player_obj.flags.get("ambient", "on") == "off":
                            continue # Skip this player
                        
                        if is_death and player_obj.flags.get("showdeath", "on") == "off":
                            continue # Skip this player
                            
                        # This player should receive the message
                        socketio.emit(msg_type, message, to=player_sid)
                # ---
                # --- END MODIFIED
                # ---
                
            def send_to_player(player_name, message, msg_type):
                player_info = world_instance.get_player_info(player_name.lower())
                if not player_info:
                    return

                # ---
                # --- MODIFIED: Check SHOWDEATH flag
                # ---
                player_obj = player_info.get("player_obj")
                sid = player_info.get("sid")
                
                if not player_obj or not sid:
                    return

                # Check flags
                if msg_type == "combat_death" and player_obj.flags.get("showdeath", "on") == "off":
                    return # Skip this message
                
                socketio.emit(msg_type, message, to=sid)
                # ---
                # --- END MODIFIED
                # ---

            def send_vitals_to_player(player_name, vitals_data):
                """Emits a 'update_vitals' event to a specific player."""
                player_info = world_instance.get_player_info(player_name.lower())
                if player_info:
                    sid = player_info.get("sid")
                    if sid:
                        socketio.emit("update_vitals", vitals_data, to=sid)

            combat_system.process_combat_tick(
                world=world_instance,
                broadcast_callback=broadcast_to_room,
                send_to_player_callback=send_to_player,
                send_vitals_callback=send_vitals_to_player
            )
            
            if world_instance.pending_trades:
                expired_trades = []
                with world_instance.trade_lock:
                    trade_items = list(world_instance.pending_trades.items())
                
                for receiver_name, offer_data in trade_items:
                    if current_time - offer_data.get("offer_time", 0) > 30:
                        expired_trades.append((receiver_name, offer_data))
                
                for receiver_name, offer_data in expired_trades:
                    world_instance.remove_pending_trade(receiver_name)
                    
                    giver_name = offer_data.get("from_player_name")
                    item_name = offer_data.get("item_name", "their offer")
                    trade_type = offer_data.get("trade_type", "give")

                    receiver_obj = world_instance.get_player_obj(receiver_name)
                    if receiver_obj:
                        receiver_obj.send_message(f"The offer from {giver_name} for {item_name} has expired.")
                        
                    giver_obj = world_instance.get_player_obj(giver_name.lower())
                    if giver_obj:
                        giver_obj.send_message(f"Your offer to {receiver_name} for {item_name} has expired.")

            # ---
            # --- NEW: CHECK PENDING GROUP INVITES
            # ---
            if world_instance.pending_group_invites:
                expired_invites = []
                with world_instance.group_lock:
                    invite_items = list(world_instance.pending_group_invites.items())
                
                for invitee_name, invite_data in invite_items:
                    if current_time - invite_data.get("time", 0) > 30:
                        expired_invites.append((invitee_name, invite_data))
                
                for invitee_name, invite_data in expired_invites:
                    world_instance.remove_pending_group_invite(invitee_name)
                    
                    inviter_name = invite_data.get("from_player_name", "Someone")
                    
                    # Notify the invitee (who declined by timing out)
                    invitee_obj = world_instance.get_player_obj(invitee_name)
                    if invitee_obj:
                        invitee_obj.send_message(f"The group invitation from {inviter_name} has expired.")
                    
                    # Notify the inviter
                    inviter_obj = world_instance.get_player_obj(inviter_name.lower())
                    if inviter_obj:
                        inviter_obj.send_message(f"Your group invitation to {invitee_name.capitalize()} has expired.")
            # ---
            # --- END NEW LOGIC
            # ---
            
            active_players_list = world_instance.get_all_players_info()
            for player_name_lower, player_data in active_players_list:
                player_obj = player_data.get("player_obj")
                if not player_obj:
                    continue
                
                if player_obj.spellup_uses_today > 0:
                    if current_time - player_obj.last_spellup_use_time > 86400:
                         player_obj.spellup_uses_today = 0
                
                if player_obj.buffs:
                    expired_buffs = [key for key, data in player_obj.buffs.items() if current_time >= data.get("expires_at", 0)]
                    for key in expired_buffs:
                        player_obj.buffs.pop(key, None)
                        if key == "spirit_shield":
                            send_to_player(player_obj.name, "The dim aura fades from around you.", "message")
            
            if current_time - world_instance.last_monster_tick_time >= config.MONSTER_TICK_INTERVAL_SECONDS:
                world_instance.last_monster_tick_time = current_time
                monster_log_prefix = f"{log_time} - MONSTER_TICK"
                
                # Handle monster movement
                monster_ai.process_monster_ai(
                    world=world_instance,
                    log_time_prefix=monster_log_prefix,
                    broadcast_callback=broadcast_to_room
                )
                
                # Handle monster ambient messages
                monster_ai.process_monster_ambient_messages(
                    world=world_instance,
                    log_time_prefix=monster_log_prefix,
                    broadcast_callback=broadcast_to_room
                )

            # ---
            # --- NEW: Band XP Payout Tick (Every 5 minutes)
            # ---
            time_since_last_band_payout = current_time - world_instance.last_band_payout_time
            if time_since_last_band_payout >= 300: # 300 seconds = 5 minutes
                world_instance.last_band_payout_time = current_time
                
                if config.DEBUG_MODE:
                    print(f"{log_prefix} - Processing Band XP Payout...")
                
                try:
                    with world_instance.player_lock:
                        for player_name, player_data in world_instance.get_all_players_info():
                            player_obj = player_data.get("player_obj")
                            if player_obj and player_obj.band_xp_bank > 0 and player_obj.death_sting_points == 0:
                                amount = player_obj.band_xp_bank
                                player_obj.band_xp_bank = 0
                                
                                # Use add_field_exp directly, as this is a *payout*
                                # not a new *gain*. grant_experience is for new XP.
                                player_obj.add_field_exp(amount, is_band_share=True)
                                
                                # Save the player's new state (bank emptied)
                                db.save_game_state(player_obj)
                                
                except Exception as e:
                    print(f"[ERROR] Failed during Band XP Payout: {e}")
            # ---
            # --- END NEW
            # ---

            did_global_tick = check_and_run_game_tick(
                world=world_instance,
                broadcast_callback=broadcast_to_room,
                send_to_player_callback=send_to_player,
                send_vitals_callback=send_vitals_to_player
            )

            if did_global_tick:
               socketio.emit('tick')

            time.sleep(1.0) 

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
        # ---
        # --- MODIFIED: Get player object *before* removing
        # ---
        player_obj = world.get_player_obj(player_name_to_remove.lower())
        player_info = world.remove_player(player_name_to_remove.lower()) # This handles group leave
            
    if player_name_to_remove and player_info:
        room_id = player_info["current_room_id"]
        print(f"[CONNECTION] Player {player_name_to_remove} disconnected: {sid}")
        disappears_message = f'<span class="keyword" data-name="{player_name_to_remove}" data-verbs="look">{player_name_to_remove}</span> disappears.'
        emit("message", disappears_message, to=room_id)
        
        # --- NEW: Save player on disconnect ---
        if player_obj:
            db.save_game_state(player_obj)
        # --- END NEW ---
    else:
        print(f"[CONNECTION] Unauthenticated client disconnected: {sid}")

@socketio.on('command')
def handle_command_event(data):
    sid = request.sid
    command = data.get("command", "").strip()
    state = session.get('state', 'auth_user')

    try:
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
                emit("login_failed", "Error. Please start over.\n", to=sid)
                emit("prompt_username", to=sid)
                return

            account = db.fetch_account(username)
            if not account:
                print(f"[AUTH] New account creation: {username}")
                db.create_account(username, password)
                session['state'] = 'char_create_name'
                emit("prompt_create_character", to=sid)
            
            elif db.check_account_password(account, password):
                print(f"[AUTH] Successful login: {username}")
                chars = db.fetch_characters_for_account(username)
                if not chars:
                    session['state'] = 'char_create_name'
                    # --- THIS IS THE FIX ---
                    # Send the message from the server only in this specific case
                    emit("message", "No characters found on this account.", to=sid)
                    # --- END FIX ---
                    emit("prompt_create_character", to=sid)
                else:
                    session['characters'] = [c['name'] for c in chars]
                    session['state'] = 'char_select'
                    emit("show_char_list", {"chars": session['characters']}, to=sid)
            
            # ---
            # --- NEW: Handle bad password
            # ---
            else:
                print(f"[AUTH] Failed login for: {username}")
                emit("login_failed", "Invalid password.", to=sid)
                session['state'] = 'auth_user'
                emit("prompt_username", to=sid)
            # --- END NEW ---
        
        elif state == 'char_create_name':
            new_char_name = command.capitalize()
            username = session.get('username')
            
            if not new_char_name or not new_char_name.isalpha() or len(new_char_name) < 3:
                emit("name_invalid", "Name must be at least 3 letters and contain no spaces or numbers.", to=sid)
                return

            if db.fetch_player_data(new_char_name):
                emit("name_taken", to=sid)
                return
            
            print(f"[AUTH] Account {username} creating new character: {new_char_name}")
            session['player_name'] = new_char_name
            session['state'] = 'in_game'
            
            result_data = execute_command(
                world, 
                new_char_name, 
                "look", 
                sid, 
                account_username=username
            )
            emit("command_response", result_data, to=sid)

        elif state == 'char_select':
            char_name = command.capitalize()
            
            if char_name.lower() == 'create':
                session['state'] = 'char_create_name'
                emit("prompt_create_character", to=sid)
                return

            if char_name not in session.get('characters', []):
                emit("char_invalid", "That is not a valid character name.", to=sid)
                return
            
            if world.get_player_info(char_name.lower()):
                emit("char_invalid", "That character is already logged in.", to=sid)
                session['state'] = 'auth_user'
                emit("prompt_username", to=sid)
                return

            print(f"[AUTH] Account {session['username']} logging in as: {char_name}")
            session['player_name'] = char_name
            session['state'] = 'in_game'
            
            result_data = execute_command(world, char_name, "look", sid)
            
            player_info = world.get_player_info(char_name.lower())
            if player_info:
                room_id = player_info.get("current_room_id")
                if room_id:
                    join_room(room_id, sid=sid)
                    arrives_message = f'<span class="keyword" data-name="{char_name}" data-verbs="look">{char_name}</span> arrives.'
                    emit("message", arrives_message, to=room_id, skip_sid=sid)
                    socketio.start_background_task(
                        _handle_npc_idle_dialogue, 
                        world, 
                        char_name, 
                        room_id
                    )
            
            emit("command_response", result_data, to=sid)
            
            # ---
            # --- NEW: Send Band join/pending messages on login
            # ---
            player_obj = world.get_player_obj(char_name.lower())
            if player_obj:
                # 1. Check for pending band invites
                band_with_invite = world.get_band_invite_for_player(player_obj.name.lower())
                if band_with_invite:
                    leader_name = band_with_invite["leader"].capitalize()
                    player_obj.send_message(
                        f"{leader_name} has invited you to join their adventuring band. "
                        f"Type '<span class='keyword' data-command='band join {leader_name}'>BAND JOIN {leader_name}</span>' to accept."
                    )
                
                # 2. Check for banked XP
                if player_obj.band_xp_bank > 0:
                    if player_obj.death_sting_points > 0:
                        player_obj.send_message(f"You have {player_obj.band_xp_bank} banked experience from your band, but you must work off your Death's Sting to receive it.")
                    else:
                        # Grant it immediately
                        amount = player_obj.band_xp_bank
                        player_obj.band_xp_bank = 0
                        player_obj.add_field_exp(amount, is_band_share=True)
                        db.save_game_state(player_obj) # Save change
            # ---
            # --- END NEW
            # ---


        elif state == 'in_game':
            player_name = session.get('player_name')
            if not player_name:
                session['state'] = 'auth_user'
                emit("login_failed", "Session error. Please log in again.\n", to=sid)
                emit("prompt_username", to=sid)
                return

            old_player_info = world.get_player_info(player_name.lower())
            old_room_id = old_player_info.get("current_room_id") if old_player_info else None
            
            result_data = execute_command(world, player_name, command, sid)

            new_player_info = world.get_player_info(player_name.lower())
            new_room_id = new_player_info.get("current_room_id") if new_player_info else None
            
            player_obj = new_player_info.get("player_obj") if new_player_info else None
            
            if new_room_id and old_room_id != new_room_id:
                if old_room_id:
                    leave_room(old_room_id, sid=sid)
                    leaves_message = f'<span class="keyword" data-name="{player_name}" data-verbs="look">{player_name}</span> leaves.'
                    emit("message", leaves_message, to=old_room_id, skip_sid=sid)
                
                join_room(new_room_id, sid=sid)
                arrives_message = f'<span class="keyword" data-name="{player_name}" data-verbs="look">{player_name}</span> arrives.'

                # ---
                # --- THIS IS THE FIX: Skip all followers in the new room
                # ---
                sids_to_skip = {sid}
                if player_obj:
                    group = world.get_group(player_obj.group_id)
                    if group and group["leader"] == player_name.lower():
                        for member_key in group["members"]:
                            if member_key == player_name.lower(): continue
                            member_info = world.get_player_info(member_key)
                            if member_info and member_info.get("current_room_id") == new_room_id:
                                member_sid = member_info.get("sid")
                                if member_sid:
                                    sids_to_skip.add(member_sid)

                # Use the robust broadcast_to_room function defined in the tick thread
                broadcast_to_room(new_room_id, arrives_message, "message", skip_sid=sids_to_skip)
                # ---
                # --- END FIX
                # ---

                socketio.start_background_task(
                    _handle_npc_idle_dialogue, 
                    world, 
                    player_name, 
                    new_room_id
                )
                
            emit("command_response", result_data, to=sid)

            # ---
            # --- NEW: AGGRO CHECKS (Player and NPC)
            # ---
            if player_obj and new_room_id:
                player_id = player_name.lower()
                player_state = world.get_combat_state(player_id)
                player_in_combat = player_state and player_state.get("state_type") == "combat"
                
                room_data = world.get_room(new_room_id)
                if room_data:
                    # Use a copy to iterate over while checking for combat
                    room_objects_copy = list(room_data.get("objects", []))
                    
                    for obj in room_objects_copy:
                        # --- Check 1: Should this object aggro the player? ---
                        if not player_in_combat and (obj.get("is_monster") or obj.get("is_npc")):
                            monster_uid = obj.get("uid")
                            if not monster_uid: continue
                            
                            is_aggressive = obj.get("is_aggressive", False)
                            is_kos_to_player = faction_handler.is_player_kos_to_entity(player_obj, obj)
                            
                            is_defeated = world.get_defeated_monster(monster_uid) is not None
                            monster_state = world.get_combat_state(monster_uid)
                            monster_in_combat = monster_state and monster_state.get("state_type") == "combat"
                                
                            if (is_aggressive or is_kos_to_player) and not is_defeated and not monster_in_combat:
                                emit("message", f"The **{obj['name']}** notices you and attacks!", to=sid)
                                current_time = time.time()
                                world.set_combat_state(monster_uid, {
                                    "state_type": "combat", 
                                    "target_id": player_id,
                                    "next_action_time": current_time,
                                    "current_room_id": new_room_id
                                })
                                if world.get_monster_hp(monster_uid) is None:
                                    world.set_monster_hp(monster_uid, obj.get("max_hp", 50))
                                
                                player_in_combat = True # Player is now in combat, skip other aggro checks
                        
                        # --- Check 2: Should this object aggro another NPC? ---
                        if obj.get("is_monster") or obj.get("is_npc"):
                            # This helper checks if the NPC is in combat and finds a KOS target
                            monster_ai._check_and_start_npc_combat(world, obj, new_room_id)
            # ---
            # --- END AGGRO CHECKS
            # ---

    except Exception as e:
        print(f"!!! CRITICAL ERROR in handle_command_event (state: {state}) !!!")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        session['state'] = 'auth_user'
        emit("login_failed", f"A server error occurred. Please log in again.\nError: {e}\n", to=sid)
        emit("prompt_username", to=sid)


if __name__ == "__main__":
    threading.Thread(target=game_tick_thread, args=(world,), daemon=True).start()
    
    print("[SERVER START] Running SocketIO server on http://127.0.0.1:8024")
    socketio.run(app, host='0.0.0.0', port=8024, debug=True, use_reloader=False, allow_unsafe_werkzeug=True)