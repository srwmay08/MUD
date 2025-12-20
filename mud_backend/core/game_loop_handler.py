# mud_backend/core/game_loop_handler.py
import time
import datetime
from typing import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

from mud_backend.core.game_objects import Player
from mud_backend.core.game_loop import environment
from mud_backend.core.game_loop import monster_respawn
from mud_backend.core import loot_system
from mud_backend import config

def _get_absorption_room_type(room_id: str) -> str:
    """Determines the room type for experience absorption."""
    if room_id in getattr(config, 'NODE_ROOM_IDS', []):
        return "on_node"
    if room_id in getattr(config, 'TOWN_ROOM_IDS', []):
        return "in_town"
    return "other"

def _prune_active_players(world: 'World', log_prefix: str, broadcast_callback: Callable):
    current_time = time.time()
    stale_players = []
    player_list = []
    player_list = world.get_all_players_info()

    for player_name, data in player_list:
        player_obj = data.get("player_obj")
        idletime_minutes = 30
        idlekick_on = "on"

        if player_obj:
            idlekick_on = player_obj.flags.get("idlekick", "on")
            idletime_minutes = player_obj.flags.get("idletime", 30)

        if idlekick_on == "off":
            continue

        player_timeout_seconds = idletime_minutes * 60
        if (current_time - data["last_seen"]) > player_timeout_seconds:
            stale_players.append(player_name)

    if stale_players:
        for player_name in stale_players:
            player_info = None
            player_info = world.remove_player(player_name)
            if player_info:
                room_id = player_info.get("current_room_id", "unknown")
                disappears_message = f'<span class="keyword" data-name="{player_name}" data-verbs="look">{player_name}</span> disappears.'
                broadcast_callback(room_id, disappears_message, "ambient")
                print(f"{log_prefix}: Pruned stale player {player_name} from room {room_id}.")

def _process_player_vitals(world: 'World', log_prefix: str, send_to_player_callback: Callable, send_vitals_callback: Callable):
    if config.DEBUG_MODE:
        print(f"{log_prefix}: Processing player vitals...")

    active_players_list = world.get_all_players_info()

    for player_name, data in active_players_list:
        player_obj = data.get("player_obj")
        if not player_obj:
            continue

        vitals_changed = False

        # 1. Regenerate Stats
        hp_regen_amount = player_obj.hp_regeneration
        if player_obj.hp < player_obj.max_hp and hp_regen_amount > 0:
            player_obj.hp = min(player_obj.max_hp, player_obj.hp + hp_regen_amount)
            vitals_changed = True

        mana_regen_amount = player_obj.mana_regeneration_per_pulse
        if player_obj.mana < player_obj.max_mana and mana_regen_amount > 0:
            player_obj.mana = min(player_obj.max_mana, player_obj.mana + mana_regen_amount)
            vitals_changed = True

        stamina_regen_amount = player_obj.stamina_regen_per_pulse
        if player_obj.stamina < player_obj.max_stamina and stamina_regen_amount > 0:
            player_obj.stamina = min(player_obj.max_stamina, player_obj.stamina + stamina_regen_amount)
            vitals_changed = True

        spirit_regen_amount = player_obj.spirit_regeneration_per_pulse
        if player_obj.spirit < player_obj.max_spirit and spirit_regen_amount > 0:
            player_obj.spirit = min(player_obj.max_spirit, player_obj.spirit + spirit_regen_amount)
            vitals_changed = True

        # 2. Process Wounds & Bandages (FIX: Always run this!)
        # Previous logic only ran this via get_vitals() which only ran if vitals_changed was True.
        # Now we run it explicitly to check for healing/scaring.
        player_obj._process_wounds()

        # If wounds healed, the player object will be marked dirty.
        if player_obj._is_dirty:
            vitals_changed = True

        # 3. Absorb Exp
        room_type = _get_absorption_room_type(player_obj.current_room_id)
        absorption_msg = player_obj.absorb_exp_pulse(room_type)
        if absorption_msg:
            vitals_changed = True
            send_to_player_callback(player_obj.name, absorption_msg, "message")

        # 4. Send Update if needed
        if vitals_changed:
            vitals_data = player_obj.get_vitals()
            send_vitals_callback(player_obj.name, vitals_data)
            # Reset dirty flag after sending to avoid spamming next tick if nothing else changed
            player_obj._is_dirty = False

def check_and_run_game_tick(world: 'World', broadcast_callback: Callable, send_to_player_callback: Callable, send_vitals_callback: Callable) -> bool:
    current_time = time.time()

    if (current_time - world.last_game_tick_time) < world.tick_interval_seconds:
        return False

    world.last_game_tick_time = current_time
    world.game_tick_counter += 1

    # --- Auction Tick ---
    if world.game_tick_counter % 2 == 0:
        world.auction_manager.tick()

    # --- NEW: Treasure Pressure Decay ---
    # Decay pressure slightly every tick to simulate recovery over time
    world.treasure_manager.decay_pressure()

    temp_active_players = {}
    active_players_list = []
    active_players_list = world.get_all_players_info()

    for player_name, data in active_players_list:
        player_obj = data.get("player_obj")
        if not player_obj:
            player_obj = Player(world, player_name, data["current_room_id"])
        temp_active_players[player_name] = player_obj

    log_time = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    log_prefix = f"{log_time} - GAME_TICK ({world.game_tick_counter})"
    if config.DEBUG_MODE:
        print(f"{log_prefix}: Running global tick...")

    _prune_active_players(world, log_prefix, broadcast_callback)

    environment.update_environment_state(
        world=world,
        game_tick_counter=world.game_tick_counter,
        active_players_dict=temp_active_players,
        log_time_prefix=log_prefix,
        broadcast_callback=broadcast_callback
    )

    environment.process_room_periodic_events(world)

    monster_respawn.process_respawns(
        world=world,
        log_time_prefix=log_prefix,
        broadcast_callback=broadcast_callback,
        send_to_player_callback=send_to_player_callback,
        game_npcs_dict={},
        game_equipment_tables_global={},
        game_items_global=world.game_items
    )

    decay_messages_by_room = loot_system.process_corpse_decay(world)
    for room_id, messages in decay_messages_by_room.items():
        for msg in messages:
            broadcast_callback(room_id, msg, "ambient_decay")

    _process_player_vitals(
        world=world,
        log_prefix=log_prefix,
        send_to_player_callback=send_to_player_callback,
        send_vitals_callback=send_vitals_callback
    )

    if config.DEBUG_MODE:
        print(f"{log_prefix}: Global tick complete.")

    return True