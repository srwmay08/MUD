# mud_project/game_logic/monster_respawn.py
import random
import time
import datetime 
import pytz     
import copy # For deepcopying templates

try:
    import config
    from . import combat 
    # Assuming GAME_EQUIPMENT_TABLES and GAME_ITEMS will be available globally or passed
    # For now, this module doesn't directly equip, it relies on data_loader or main logic to handle it
    # when the monster template is re-added to the room.
except ImportError as e:
    # ... (your existing mock config) ...
    pass


def _re_equip_entity_from_template(entity_runtime_data, entity_template, game_equipment_tables, game_items):
    """
    Helper to re-initialize the 'equipped' dict for a respawning NPC or Monster.
    This is similar to the logic in data_loader but applied to an existing runtime_data structure.
    """
    if not entity_runtime_data or not entity_template:
        return

    entity_runtime_data["equipped"] = {slot_key_cfg: None for slot_key_cfg in config.EQUIPMENT_SLOTS.keys()}
    equipment_table_id = entity_template.get("equipment_table_id")

    if equipment_table_id and game_equipment_tables:
        table = game_equipment_tables.get(equipment_table_id)
        if table:
            for slot_key_in_table, item_id_to_equip in table.get("slots", {}).items():
                if slot_key_in_table not in config.EQUIPMENT_SLOTS.keys():
                    if config.DEBUG_MODE: print(f"DEBUG RESPAWN_EQUIP: Invalid slot '{slot_key_in_table}' in equip table '{equipment_table_id}' for '{entity_template.get('name')}'.")
                    continue
                if item_id_to_equip and item_id_to_equip in game_items:
                    item_data_for_slot_check = game_items[item_id_to_equip]
                    item_defined_slots = item_data_for_slot_check.get("slot", [])
                    if not isinstance(item_defined_slots, list): item_defined_slots = [item_defined_slots]
                    if slot_key_in_table in item_defined_slots:
                        entity_runtime_data["equipped"][slot_key_in_table] = item_id_to_equip
                        if config.DEBUG_MODE and getattr(config, 'DEBUG_RESPAWN_VERBOSE', False):
                            print(f"DEBUG RESPAWN_EQUIP: Re-equipped '{item_id_to_equip}' to '{slot_key_in_table}' for '{entity_template.get('name')}'.")
                    elif config.DEBUG_MODE: print(f"DEBUG RESPAWN_EQUIP_WARN: Item '{item_id_to_equip}' cannot go in slot '{slot_key_in_table}' for '{entity_template.get('name')}'.")
                elif config.DEBUG_MODE: print(f"DEBUG RESPAWN_EQUIP_WARN: Item '{item_id_to_equip}' from table '{equipment_table_id}' not in GAME_ITEMS for '{entity_template.get('name')}'.")
        elif config.DEBUG_MODE: print(f"DEBUG RESPAWN_EQUIP_WARN: Equip table '{equipment_table_id}' not found for '{entity_template.get('name')}'.")
    # Also re-initialize other dynamic fields if necessary, e.g., current HP to max_hp from template
    entity_runtime_data["hp"] = entity_template.get("max_hp", entity_template.get("hp", 1))


def process_respawns(log_time_prefix, current_time_utc, 
                     tracked_defeated_entities_dict, 
                     game_rooms_dict, game_npcs_dict, game_monster_templates_dict, 
                     broadcast_callback,
                     recently_defeated_targets_dict, # From combat.py
                     game_equipment_tables_global, # NEW: Pass GAME_EQUIPMENT_TABLES
                     game_items_global             # NEW: Pass GAME_ITEMS
                     ):
    if config.DEBUG_MODE and getattr(config, 'DEBUG_GAME_TICK_RESPAWN_PHASE', True) and tracked_defeated_entities_dict: 
        print(f"{log_time_prefix} - RESPAWN_SYSTEM: Checking {len(tracked_defeated_entities_dict)} defeated entities.")
    
    respawned_entity_runtime_ids_to_remove = []

    for runtime_id, respawn_info in list(tracked_defeated_entities_dict.items()):
        entity_template_key = respawn_info["template_key"]
        is_eligible = current_time_utc >= respawn_info["eligible_at"]
        
        # ... (your existing eligibility and chance logging) ...

        if is_eligible:
            respawn_chance = respawn_info.get("chance", getattr(config, "NPC_DEFAULT_RESPAWN_CHANCE", 0.2))
            roll_for_respawn = random.random()
            should_respawn_by_chance = roll_for_respawn < respawn_chance

            # ... (your existing roll logging) ...

            if should_respawn_by_chance:
                room_id_to_respawn_in = respawn_info["room_id"]
                entity_type = respawn_info["type"] # "npc" or "monster"
                is_template_unique = respawn_info.get("is_unique", False)

                if room_id_to_respawn_in not in game_rooms_dict:
                    if config.DEBUG_MODE: print(f"{log_time_prefix} - RESPAWN_ERROR: Room {room_id_to_respawn_in} not found for {entity_template_key} ({runtime_id}).")
                    continue

                room_data = game_rooms_dict[room_id_to_respawn_in]
                room_entity_list_key = f"{entity_type}s" 
                
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
                if is_template_unique: # For unique NPCs/Monsters
                    # Check if an active instance (not marked as recently defeated) of this unique template already exists in the room's list
                    # This assumes unique entities are identified by their template_key in the room's list
                    if entity_template_key in room_data.get(room_entity_list_key, []) and \
                       runtime_id not in recently_defeated_targets_dict: # Check if it's *not* the one currently defeated and awaiting respawn
                        can_respawn_this_template_into_room = False
                        if config.DEBUG_MODE: 
                            print(f"{log_time_prefix} - RESPAWN_SKIP: Unique template {entity_display_name} (Key: {entity_template_key}) already actively present in room {room_id_to_respawn_in}.")
                
                if can_respawn_this_template_into_room:
                    if room_entity_list_key not in room_data: room_data[room_entity_list_key] = []
                    
                    # For monsters, we add their template key back to the room's monster list.
                    # The actual monster instance is conceptual until combat or interaction.
                    # For unique NPCs, their template key should already be in game_npcs_dict.
                    # We are essentially "activating" it again.
                    if entity_type == "monster":
                        # For non-unique monsters, we add their template key.
                        # The 'original_instance_index' might be used if you need to restore it to a specific "slot"
                        # in the room's monster list, but simple append is often fine.
                        room_data[room_entity_list_key].append(entity_template_key)
                        if config.DEBUG_MODE: print(f"{log_time_prefix} - RESPAWN_ACTION: Monster template '{entity_template_key}' added back to room {room_id_to_respawn_in}'s '{room_entity_list_key}' list.")
                    elif entity_type == "npc":
                        # For NPCs, they are typically referenced by their key from game_npcs_dict.
                        # We ensure the key is in the room's list if it was somehow removed.
                        # The main action is clearing their defeated status.
                        if entity_template_key not in room_data.get(room_entity_list_key, []):
                             room_data[room_entity_list_key].append(entity_template_key) # Ensure it's listed in room
                        
                        # Re-initialize equipped items for the NPC from its template
                        # The base_template_data is from GAME_NPCS, which should have been processed by data_loader
                        # to include an 'equipped' dict. If not, or if we need to ensure it's fresh:
                        npc_runtime_data_ref = game_npcs_dict.get(entity_template_key) # Get the global template
                        if npc_runtime_data_ref:
                             _re_equip_entity_from_template(npc_runtime_data_ref, base_template_data, game_equipment_tables_global, game_items_global)
                        if config.DEBUG_MODE: print(f"{log_time_prefix} - RESPAWN_ACTION: NPC '{entity_template_key}' marked as active in room {room_id_to_respawn_in}.")


                    # Clear runtime combat states
                    if runtime_id in combat.RUNTIME_ENTITY_HP: combat.RUNTIME_ENTITY_HP.pop(runtime_id, None)
                    if runtime_id in recently_defeated_targets_dict: recently_defeated_targets_dict.pop(runtime_id, None)
                    if runtime_id in combat.RECENTLY_DEFEATED_TARGETS_IN_ROOM: combat.RECENTLY_DEFEATED_TARGETS_IN_ROOM.pop(runtime_id, None) # Ensure global one is also cleared

                    # ... (your existing logging for state clear and success) ...
                    broadcast_callback(room_id_to_respawn_in, f"{entity_display_name} has appeared.", "ambient_spawn")
                    respawned_entity_runtime_ids_to_remove.append(runtime_id)
    
    for runtime_id_key_to_remove in respawned_entity_runtime_ids_to_remove:
        if config.DEBUG_MODE: print(f"{log_time_prefix} - RESPAWN_SYSTEM_CLEANUP: Removing '{runtime_id_key_to_remove}' from TRACKED_DEFEATED_ENTITIES.")
        tracked_defeated_entities_dict.pop(runtime_id_key_to_remove, None)
