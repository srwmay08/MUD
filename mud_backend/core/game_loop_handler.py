# mud_backend/core/game_loop_handler.py
import time
import datetime
from typing import Callable

from mud_backend.core import game_state
from mud_backend.core.game_objects import Player 
from mud_backend.core.game_loop import environment
from mud_backend.core.game_loop import monster_respawn
from mud_backend.core import loot_system
from mud_backend import config # <-- ADDED MISSING IMPORT

def _prune_active_players(log_prefix: str, broadcast_callback: Callable):
    """Prunes players who have timed out from the active list."""
    current_time = time.time()
    stale_players = []
    player_list = []
    
    with game_state.PLAYER_LOCK:
        player_list = list(game_state.ACTIVE_PLAYERS.items())
    
    for player_name, data in player_list:
        if (current_time - data["last_seen"]) > game_state.PLAYER_TIMEOUT_SECONDS:
            stale_players.append(player_name)
            
    if stale_players:
        for player_name in stale_players:
            player_info = None
            with game_state.PLAYER_LOCK:
                player_info = game_state.ACTIVE_PLAYERS.pop(player_name, None)
            
            if player_info:
                room_id = player_info.get("current_room_id", "unknown")
                disappears_message = f'<span class="keyword" data-name="{player_name}" data-verbs="look">{player_name}</span> disappears.'
                broadcast_callback(room_id, disappears_message, "ambient")
                print(f"{log_prefix}: Pruned stale player {player_name} from room {room_id}.")

def check_and_run_game_tick(broadcast_callback: Callable, send_to_player_callback: Callable) -> bool:
    """
    Checks if enough time has passed and runs the global game tick.
    Returns True if a tick ran, False otherwise.
    """
    current_time = time.time()
    
    if (current_time - game_state.LAST_GAME_TICK_TIME) < game_state.TICK_INTERVAL_SECONDS:
        return False
        
    game_state.LAST_GAME_TICK_TIME = current_time
    game_state.GAME_TICK_COUNTER += 1
    
    temp_active_players = {}
    active_players_list = []
    with game_state.PLAYER_LOCK:
        active_players_list = list(game_state.ACTIVE_PLAYERS.items())
    
    for player_name, data in active_players_list:
        player_obj = data.get("player_obj")
        if not player_obj:
            player_obj = Player(player_name, data["current_room_id"])
        temp_active_players[player_name] = player_obj
    
    log_time = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    log_prefix = f"{log_time} - GAME_TICK ({game_state.GAME_TICK_COUNTER})" 
    if config.DEBUG_MODE:
         print(f"{log_prefix}: Running global tick...")

    # 1. Prune stale players
    _prune_active_players(log_prefix, broadcast_callback)

    # 2. Update environment
    environment.update_environment_state(
        game_tick_counter=game_state.GAME_TICK_COUNTER,
        active_players_dict=temp_active_players,
        log_time_prefix=log_prefix,
        broadcast_callback=broadcast_callback
    )

    # 3. Process monster/NPC respawns
    monster_respawn.process_respawns(
        log_time_prefix=log_prefix,
        broadcast_callback=broadcast_callback,
        send_to_player_callback=send_to_player_callback,
        game_npcs_dict={}, 
        game_equipment_tables_global={}, 
        game_items_global=game_state.GAME_ITEMS 
    )
    
    # 4. Monster AI is now independent (handled in app.py loop)

    # 5. Process Corpse Decay
    decay_messages_by_room = loot_system.process_corpse_decay(
        game_rooms_dict=game_state.GAME_ROOMS,
        log_time_prefix=log_prefix
    )
    for room_id, messages in decay_messages_by_room.items():
        for msg in messages:
            broadcast_callback(room_id, msg, "ambient_decay")
    
    if config.DEBUG_MODE:
        print(f"{log_prefix}: Global tick complete.")
        
    return True