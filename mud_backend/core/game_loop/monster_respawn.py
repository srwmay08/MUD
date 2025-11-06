# mud_backend/core/game_loop/monster_respawn.py
import random
import time
import datetime 
import pytz     
import copy 

# --- THIS IS THE FIX ---
# 'config' is in 'mud_backend', not 'mud_backend.core'
from mud_backend import config
# --- END FIX ---
from mud_backend.core import game_state 


def _re_equip_entity_from_template(entity_runtime_data, entity_template, game_equipment_tables, game_items):
    # ... (function unchanged) ...
    if not entity_runtime_data or not entity_template:
        return
    entity_runtime_data["equipped"] = {slot_key_cfg: None for slot_key_cfg in config.EQUIPMENT_SLOTS.keys()}
    # ... (rest of logic) ...
    entity_runtime_data["hp"] = entity_template.get("max_hp", entity_template.get("hp", 1))


def process_respawns(log_time_prefix, 
                     broadcast_callback,
                     # --- Pass in the data it needs ---
                     game_npcs_dict, 
                     game_equipment_tables_global, 
                     game_items_global             
                     ):
    """
    Processes all respawns.
    This function now reads its state from the global 'game_state' module.
    """
    
    current_time_float = time.time()
    
    # --- Get state from the global game_state module ---
    tracked_defeated_entities_dict = game_state.DEFEATED_MONSTERS
    game_rooms_dict = game_state.GAME_ROOMS
    # --- UPDATED: Get monster templates ---
    game_monster_templates_dict = game_state.GAME_MONSTER_TEMPLATES
    # ---
    
    respawned_entity_runtime_ids_to_remove = []

    # --- ADD LOCK ---
    # We lock the entire respawn process to prevent race conditions
    # with the main thread trying to read/write combat state.
    with game_state.COMBAT_LOCK:
        if config.DEBUG_MODE and getattr(config, 'DEBUG_GAME_TICK_RESPAWN_PHASE', True) and tracked_defeated_entities_dict: 
            print(f"{log_time_prefix} - RESPAWN_SYSTEM: Checking {len(tracked_defeated_entities_dict)} defeated entities.")
        
        # Use .items() for Python 3
        # Use list() to create a snapshot in case the dict is modified
        for runtime_id, respawn_info in list(tracked_defeated_entities_dict.items()):
            entity_template_key = respawn_info.get("template_key", runtime_id) 
            
            # --- FIX: Ensure respawn_info is a dict ---
            if not isinstance(respawn_info, dict):
                if config.DEBUG_MODE: print(f"{log_time_prefix} - RESPAWN_WARN: Skipping invalid respawn entry for {runtime_id}")
                continue
            # ---
            
            eligible_at = respawn_info.get("eligible_at", current_time_float)
            is_eligible = current_time_float >= eligible_at

            # --- NEW DEBUG FEATURE ---
            if config.DEBUG_MODE and getattr(config, 'DEBUG_GAME_TICK_RESPAWN_PHASE', True):
                print(f"{log_time_prefix} - RESPAWN_DEBUG: Entity {runtime_id} (Template: {entity_template_key}). Eligible: {is_eligible} (at {eligible_at:.0f}s).")
            # --- END NEW DEBUG FEATURE ---

            if is_eligible:
                respawn_chance = respawn_info.get("chance", getattr(config, "NPC_DEFAULT_RESPAWN_CHANCE", 0.2))
                roll_for_respawn = random.random()
                should_respawn_by_chance = roll_for_respawn < respawn_chance

                # --- NEW DEBUG FEATURE ---
                if config.DEBUG_MODE and getattr(config, 'DEBUG_GAME_TICK_RESPAWN_PHASE', True):
                     print(f"{log_time_prefix} - RESPAWN_DEBUG: Chance Check: Roll={roll_for_respawn:.2f} vs Chance={respawn_chance:.2f}. Respawn: {should_respawn_by_chance}")
                # --- END NEW DEBUG FEATURE ---


                if should_respawn_by_chance:
                    room_id_to_respawn_in = respawn_info["room_id"]
                    entity_type = respawn_info["type"]
                    is_template_unique = respawn_info.get("is_unique", False)

                    if room_id_to_respawn_in not in game_rooms_dict:
                        if config.DEBUG_MODE: print(f"{log_time_prefix} - RESPAWN_ERROR: Room {room_id_to_respawn_in} not found for {entity_template_key} ({runtime_id}).")
                        continue

                    room_data = game_rooms_dict[room_id_to_respawn_in]
                    
                    base_template_data = None
                    if entity_type == "npc":
                        base_template_data = game_npcs_dict.get(entity_template_key)
                    elif entity_type == "monster":
                        # --- UPDATED: Get from global templates ---
                        base_template_data = game_monster_templates_dict.get(entity_template_key)

                    if not base_template_data:
                        if config.DEBUG_MODE: print(f"{log_time_prefix} - RESPAWN_ERROR: Template data for '{entity_template_key}' (type: {entity_type}) not found. Cannot respawn.")
                        continue
                    
                    entity_display_name = base_template_data.get("name", entity_template_key)
                    
                    can_respawn_this_template_into_room = True
                    if is_template_unique: 
                        current_room_objects = room_data.get("objects", [])
                        if any(obj.get("monster_id") == entity_template_key for obj in current_room_objects):
                            can_respawn_this_template_into_room = False
                    
                    if can_respawn_this_template_into_room:
                        if "objects" not in room_data: room_data["objects"] = []
                        
                        if entity_type == "monster":
                            # Add a deep copy of the monster template back to the room's objects
                            room_data["objects"].append(copy.deepcopy(base_template_data))
                            if config.DEBUG_MODE: print(f"{log_time_prefix} - RESPAWN_ACTION: Monster '{entity_template_key}' added back to room {room_id_to_respawn_in}'s object list.")
                        
                        elif entity_type == "npc":
                            pass # (NPC logic)

                        # --- Clear runtime combat states from game_state ---
                        if runtime_id in game_state.RUNTIME_MONSTER_HP:
                            game_state.RUNTIME_MONSTER_HP.pop(runtime_id, None)
                        # ---
                        
                        # --- THIS IS THE FIX: Re-enabled the broadcast ---
                        broadcast_callback(room_id_to_respawn_in, f"The {entity_display_name} appears.", "ambient_spawn")
                        # --- END FIX ---
                        respawned_entity_runtime_ids_to_remove.append(runtime_id)
                    elif config.DEBUG_MODE:
                         print(f"{log_time_prefix} - RESPAWN_ACTION: Skipping unique monster {entity_template_key} as one already exists in the room.")
        
        for runtime_id_key_to_remove in respawned_entity_runtime_ids_to_remove:
            if config.DEBUG_MODE: print(f"{log_time_prefix} - RESPAWN_SYSTEM_CLEANUP: Removing '{runtime_id_key_to_remove}' from DEFEATED_MONSTERS.")
            tracked_defeated_entities_dict.pop(runtime_id_key_to_remove, None)
    # --- END LOCK ---