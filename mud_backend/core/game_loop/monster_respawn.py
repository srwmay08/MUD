# mud_backend/core/game_loop/monster_respawn.py
import random
import time
import datetime 
import pytz     
import copy 

from mud_backend import config
from mud_backend.core import game_state 
from mud_backend.core import combat_system


def _re_equip_entity_from_template(entity_runtime_data, entity_template, game_equipment_tables, game_items):
    """
    Helper to re-populate a monster's equipment from its template.
    """
    if not entity_runtime_data or not entity_template:
        return

    # 1. Reset equipment slots
    entity_runtime_data["equipped"] = {slot_key_cfg: None for slot_key_cfg in config.EQUIPMENT_SLOTS.keys()}
    
    # 2. Re-equip items defined in the template
    template_equipped = entity_template.get("equipped", {})
    for slot, item_id in template_equipped.items():
        if slot in entity_runtime_data["equipped"]:
             entity_runtime_data["equipped"][slot] = item_id

    # 3. Reset HP to max
    if "hp" not in entity_template and "max_hp" in entity_template:
         entity_runtime_data["hp"] = entity_template["max_hp"]
    elif "hp" in entity_template:
         entity_runtime_data["hp"] = entity_template["hp"]


def process_respawns(log_time_prefix, 
                     broadcast_callback,
                     send_to_player_callback,
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
    game_monster_templates_dict = game_state.GAME_MONSTER_TEMPLATES
    # ---
    
    respawned_entity_runtime_ids_to_remove = []

    # --- ADD LOCK ---
    # We lock the entire respawn process to prevent race conditions
    with game_state.COMBAT_LOCK:
        if config.DEBUG_MODE and getattr(config, 'DEBUG_GAME_TICK_RESPAWN_PHASE', True) and tracked_defeated_entities_dict: 
            print(f"{log_time_prefix} - RESPAWN_SYSTEM: Checking {len(tracked_defeated_entities_dict)} defeated entities.")
        
        for runtime_id, respawn_info in list(tracked_defeated_entities_dict.items()):
            entity_template_key = respawn_info.get("template_key", runtime_id) 
            
            if not isinstance(respawn_info, dict):
                if config.DEBUG_MODE: print(f"{log_time_prefix} - RESPAWN_WARN: Skipping invalid respawn entry for {runtime_id}")
                continue
            
            eligible_at = respawn_info.get("eligible_at", current_time_float)
            is_eligible = current_time_float >= eligible_at

            if config.DEBUG_MODE and getattr(config, 'DEBUG_GAME_TICK_RESPAWN_PHASE', True):
                print(f"{log_time_prefix} - RESPAWN_DEBUG: Entity {runtime_id} (Template: {entity_template_key}). Eligible: {is_eligible} (at {eligible_at:.0f}s).")

            if is_eligible:
                respawn_chance = respawn_info.get("chance", getattr(config, "NPC_DEFAULT_RESPAWN_CHANCE", 0.2))
                roll_for_respawn = random.random()
                should_respawn_by_chance = roll_for_respawn < respawn_chance

                if config.DEBUG_MODE and getattr(config, 'DEBUG_GAME_TICK_RESPAWN_PHASE', True):
                     print(f"{log_time_prefix} - RESPAWN_DEBUG: Chance Check: Roll={roll_for_respawn:.2f} vs Chance={respawn_chance:.2f}. Respawn: {should_respawn_by_chance}")

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
                            room_data["objects"].append(copy.deepcopy(base_template_data))
                            if config.DEBUG_MODE: print(f"{log_time_prefix} - RESPAWN_ACTION: Monster '{entity_template_key}' added back to room {room_id_to_respawn_in}'s object list.")
                        
                        elif entity_type == "npc":
                            pass # (NPC logic)

                        # --- Broadcast Appearance FIRST ---
                        broadcast_callback(room_id_to_respawn_in, f"The {entity_display_name} appears.", "ambient_spawn")
                        # ----------------------------------

                        # --- Clear runtime combat states from game_state ---
                        if runtime_id in game_state.RUNTIME_MONSTER_HP:
                            game_state.RUNTIME_MONSTER_HP.pop(runtime_id, None)
                        
                        # --- AGGRO CHECK ON RESPAWN ---
                        monster_obj = base_template_data
                        
                        if monster_obj.get("is_aggressive") and monster_obj.get("is_monster"):
                            monster_id_to_check = runtime_id # This is the ID we are respawning
                            
                            # Find all players in this room
                            players_in_room = []
                            with game_state.PLAYER_LOCK:
                                for p_name, p_data in game_state.ACTIVE_PLAYERS.items():
                                    if p_data.get("current_room_id") == room_id_to_respawn_in:
                                        players_in_room.append(p_data.get("player_obj"))
                            
                            for player_obj in players_in_room:
                                if not player_obj:
                                    continue
                                
                                player_id = player_obj.name.lower()
                                
                                # Check if player is *already* in combat
                                player_state = game_state.COMBAT_STATE.get(player_id)
                                player_in_combat = player_state and player_state.get("state_type") == "combat"

                                if not player_in_combat:
                                    # Player is not in combat. Monster attacks!
                                    send_to_player_callback(player_obj.name, f"The **{monster_obj['name']}** notices you and attacks!", "combat_other")
                                    
                                    monster_rt = combat_system.calculate_roundtime(monster_obj.get("stats", {}).get("AGI", 50))
                                    
                                    game_state.COMBAT_STATE[monster_id_to_check] = {
                                        "state_type": "combat",
                                        "target_id": player_id,
                                        "next_action_time": current_time_float, # Attacks immediately
                                        "current_room_id": room_id_to_respawn_in
                                    }
                                    
                                    if monster_id_to_check not in game_state.RUNTIME_MONSTER_HP:
                                        game_state.RUNTIME_MONSTER_HP[monster_id_to_check] = monster_obj.get("max_hp", 1)
                                    
                                    # Aggro one player and stop
                                    break 
                        # --- END AGGRO CHECK ---

                        respawned_entity_runtime_ids_to_remove.append(runtime_id)
                        
                    elif config.DEBUG_MODE:
                         print(f"{log_time_prefix} - RESPAWN_ACTION: Skipping unique monster {entity_template_key} as one already exists in the room.")
        
        for runtime_id_key_to_remove in respawned_entity_runtime_ids_to_remove:
            if config.DEBUG_MODE: print(f"{log_time_prefix} - RESPAWN_SYSTEM_CLEANUP: Removing '{runtime_id_key_to_remove}' from DEFEATED_MONSTERS.")
            tracked_defeated_entities_dict.pop(runtime_id_key_to_remove, None)
    # --- END LOCK ---