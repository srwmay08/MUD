# mud_backend/core/game_loop_handler.py
import time
import datetime
from typing import Callable, TYPE_CHECKING

# --- REFACTORED: Import World for type hinting ---
if TYPE_CHECKING:
    from mud_backend.core.game_state import World
# --- END REFACTORED ---

# --- REMOVED: from mud_backend.core import game_state ---
from mud_backend.core.game_objects import Player 
from mud_backend.core.game_loop import environment
from mud_backend.core.game_loop import monster_respawn
from mud_backend.core import loot_system
from mud_backend import config # <-- ADDED MISSING IMPORT

# --- REFACTORED: Accept world object ---
def _prune_active_players(world: 'World', log_prefix: str, broadcast_callback: Callable):
    """Prunes players who have timed out from the active list."""
    current_time = time.time()
    stale_players = []
    player_list = []
    
    # --- FIX: Use world object ---
    player_list = world.get_all_players_info()
    
    for player_name, data in player_list:
        if (current_time - data["last_seen"]) > world.player_timeout_seconds:
            stale_players.append(player_name)
            
    if stale_players:
        for player_name in stale_players:
            player_info = None
            # --- FIX: Use world object ---
            player_info = world.remove_player(player_name)
            
            if player_info:
                room_id = player_info.get("current_room_id", "unknown")
                disappears_message = f'<span class="keyword" data-name="{player_name}" data-verbs="look">{player_name}</span> disappears.'
                broadcast_callback(room_id, disappears_message, "ambient")
                print(f"{log_prefix}: Pruned stale player {player_name} from room {room_id}.")

# --- REFACTORED: Accept world object ---
def check_and_run_game_tick(world: 'World', broadcast_callback: Callable, send_to_player_callback: Callable) -> bool:
    """
    Checks if enough time has passed and runs the global game tick.
    Returns True if a tick ran, False otherwise.
    """
    current_time = time.time()
    
    # --- FIX: Use world object attributes ---
    if (current_time - world.last_game_tick_time) < world.tick_interval_seconds:
        return False
        
    world.last_game_tick_time = current_time
    world.game_tick_counter += 1
    # --- END FIX ---
    
    temp_active_players = {}
    active_players_list = []
    # --- FIX: Use world object ---
    active_players_list = world.get_all_players_info()
    
    for player_name, data in active_players_list:
        player_obj = data.get("player_obj")
        if not player_obj:
            # --- FIX: Inject world into Player constructor ---
            player_obj = Player(world, player_name, data["current_room_id"])
        temp_active_players[player_name] = player_obj
    
    log_time = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    log_prefix = f"{log_time} - GAME_TICK ({world.game_tick_counter})" # Use world.game_tick_counter
    if config.DEBUG_MODE:
         print(f"{log_prefix}: Running global tick...")

    # 1. Prune stale players
    _prune_active_players(world, log_prefix, broadcast_callback)

    # 2. Update environment
    # --- FIX: Pass world object ---
    environment.update_environment_state(
        world=world,
        game_tick_counter=world.game_tick_counter,
        active_players_dict=temp_active_players,
        log_time_prefix=log_prefix,
        broadcast_callback=broadcast_callback
    )

    # 3. Process monster/NPC respawns
    # --- FIX: Pass world object ---
    monster_respawn.process_respawns(
        world=world,
        log_time_prefix=log_prefix,
        broadcast_callback=broadcast_callback,
        send_to_player_callback=send_to_player_callback,
        game_npcs_dict={}, 
        game_equipment_tables_global={}, 
        game_items_global=world.game_items 
    )
    
    # 4. Monster AI is now independent (handled in app.py loop)

    # 5. Process Corpse Decay
    decay_messages_by_room = loot_system.process_corpse_decay(
        game_rooms_dict=world.game_rooms, # Pass world's room dict
        log_time_prefix=log_prefix
    )
    for room_id, messages in decay_messages_by_room.items():
        for msg in messages:
            broadcast_callback(room_id, msg, "ambient_decay")
    
    if config.DEBUG_MODE:
        print(f"{log_prefix}: Global tick complete.")
        
    return True