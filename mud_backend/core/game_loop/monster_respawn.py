# mud_backend/core/game_loop/monster_respawn.py
import random
import time
import datetime 
import pytz     
import copy 
import uuid # <-- NEW IMPORT

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
    tracked_defeated_entities_dict = game_state.DEFEATED_MONSTERS
    game_rooms_dict = game_state.GAME_ROOMS
    game_monster_templates_dict = game_state.GAME_MONSTER_TEMPLATES
    
    respawned_entity_runtime_ids_to_remove = []

    with game_state.COMBAT_LOCK:
        # Note: tracked_defeated_entities_dict keys are now UIDs, not template IDs
        for runtime_uid, respawn_info in list(tracked_defeated_entities_dict.items()):
            entity_template_key = respawn_info.get("template_key")
            if not entity_template_key:
                 # Fallback for old data if any exists
                 entity_template_key = respawn_info.get("monster_id", "unknown")

            if not isinstance(respawn_info, dict):
                continue
            
            eligible_at = respawn_info.get("eligible_at", current_time_float)
            is_eligible = current_time_float >= eligible_at

            if is_eligible:
                respawn_chance = respawn_info.get("chance", getattr(config, "NPC_DEFAULT_RESPAWN_CHANCE", 0.2))
                if random.random() < respawn_chance:
                    room_id_to_respawn_in = respawn_info["room_id"]
                    entity_type = respawn_info["type"]
                    is_template_unique = respawn_info.get("is_unique", False)

                    if room_id_to_respawn_in not in game_rooms_dict:
                        continue

                    room_data = game_rooms_dict[room_id_to_respawn_in]
                    
                    base_template_data = None
                    if entity_type == "monster":
                        base_template_data = game_monster_templates_dict.get(entity_template_key)

                    if not base_template_data:
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
                            new_monster = copy.deepcopy(base_template_data)
                            # --- NEW: Assign a unique runtime ID ---
                            new_monster_uid = uuid.uuid4().hex
                            new_monster["uid"] = new_monster_uid
                            # ---------------------------------------
                            room_data["objects"].append(new_monster)
                            
                            # Use the new UID for aggro checks below
                            monster_id_to_check = new_monster_uid 
                        
                        else:
                             monster_id_to_check = None # NPC case

                        broadcast_callback(room_id_to_respawn_in, f"The {entity_display_name} appears.", "ambient_spawn")

                        # --- Clear runtime combat states for the OLD dead UID ---
                        if runtime_uid in game_state.RUNTIME_MONSTER_HP:
                            game_state.RUNTIME_MONSTER_HP.pop(runtime_uid, None)
                        
                        # --- AGGRO CHECK ON RESPAWN ---
                        if entity_type == "monster" and base_template_data.get("is_aggressive"):
                            # Find all players in this room
                            players_in_room = []
                            with game_state.PLAYER_LOCK:
                                for p_name, p_data in game_state.ACTIVE_PLAYERS.items():
                                    if p_data.get("current_room_id") == room_id_to_respawn_in:
                                        players_in_room.append(p_data.get("player_obj"))
                            
                            for player_obj in players_in_room:
                                if not player_obj: continue
                                player_id = player_obj.name.lower()
                                player_state = game_state.COMBAT_STATE.get(player_id)
                                player_in_combat = player_state and player_state.get("state_type") == "combat"

                                if not player_in_combat:
                                    send_to_player_callback(player_obj.name, f"The **{entity_display_name}** notices you and attacks!", "combat_other")
                                    monster_rt = combat_system.calculate_roundtime(base_template_data.get("stats", {}).get("AGI", 50))
                                    
                                    # Use the NEW unique ID for the new combat state
                                    game_state.COMBAT_STATE[monster_id_to_check] = {
                                        "state_type": "combat",
                                        "target_id": player_id,
                                        "next_action_time": current_time_float,
                                        "current_room_id": room_id_to_respawn_in
                                    }
                                    game_state.RUNTIME_MONSTER_HP[monster_id_to_check] = base_template_data.get("max_hp", 1)
                                    break 
                        # --- END AGGRO CHECK ---

                        respawned_entity_runtime_ids_to_remove.append(runtime_uid)
                        
        for runtime_uid_to_remove in respawned_entity_runtime_ids_to_remove:
            tracked_defeated_entities_dict.pop(runtime_uid_to_remove, None)