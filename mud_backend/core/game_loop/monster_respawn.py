# mud_backend/core/game_loop/monster_respawn.py
import random
import time
import datetime 
import pytz     
import copy # For deepcopying templates

try:
    import config
    # --- UPDATED IMPORTS ---
    # We no longer import combat, we import the global state
    from mud_backend.core import game_state 
except ImportError as e:
    # ... (your existing mock config) ...
    class MockConfig:
        DEBUG_MODE = True
        EQUIPMENT_SLOTS = {"torso": "Torso", "mainhand": "Main Hand", "offhand": "Off Hand"}
        NPC_DEFAULT_RESPAWN_CHANCE = 0.2
    config = MockConfig()
    
    # --- ADD MOCK GAME_STATE FOR FALLBACK ---
    class MockGameState:
        RUNTIME_MONSTER_HP = {}
        DEFEATED_MONSTERS = {}
        GAME_ROOMS = {}
    game_state = MockGameState()
    pass


def _re_equip_entity_from_template(entity_runtime_data, entity_template, game_equipment_tables, game_items):
    """
    Helper to re-initialize the 'equipped' dict for a respawning NPC or Monster.
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
    
    entity_runtime_data["hp"] = entity_template.get("max_hp", entity_template.get("hp", 1))


def process_respawns(log_time_prefix, current_time_utc, 
                     broadcast_callback,
                     # --- Pass in the data it needs ---
                     game_npcs_dict, game_monster_templates_dict, 
                     game_equipment_tables_global, 
                     game_items_global             
                     ):
    """
    Processes all respawns.
    This function now reads its state from the global 'game_state' module.
    """
    
    # --- NEW: Get state from the global game_state module ---
    tracked_defeated_entities_dict = game_state.DEFEATED_MONSTERS
    game_rooms_dict = game_state.GAME_ROOMS
    # ---
    
    if config.DEBUG_MODE and getattr(config, 'DEBUG_GAME_TICK_RESPAWN_PHASE', True) and tracked_defeated_entities_dict: 
        print(f"{log_time_prefix} - RESPAWN_SYSTEM: Checking {len(tracked_defeated_entities_dict)} defeated entities.")
    
    respawned_entity_runtime_ids_to_remove = []

    for runtime_id, respawn_info in list(tracked_defeated_entities_dict.items()):
        entity_template_key = respawn_info.get("template_key", runtime_id) # Fallback for older entries
        is_eligible = current_time_utc >= respawn_info.get("eligible_at", current_time_utc)
        
        if is_eligible:
            respawn_chance = respawn_info.get("chance", getattr(config, "NPC_DEFAULT_RESPAWN_CHANCE", 0.2))
            roll_for_respawn = random.random()
            should_respawn_by_chance = roll_for_respawn < respawn_chance

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
                    # --- This is a critical fallback ---
                    # If monster templates aren't loaded, find the original in the room
                    original_room_data = db.fetch_room_data(room_id_to_respawn_in)
                    if original_room_data:
                         base_template_data = next((obj for obj in original_room_data.get("objects", []) if obj.get("monster_id") == entity_template_key), None)
                    
                    if not base_template_data:
                        if config.DEBUG_MODE: print(f"{log_time_prefix} - RESPAWN_ERROR: Template data for '{entity_template_key}' (type: {entity_type}) not found. Cannot respawn.")
                        continue
                
                entity_display_name = base_template_data.get("name", entity_template_key)
                
                can_respawn_this_template_into_room = True
                if is_template_unique: 
                    # Check if an active instance is already in the room's *live* object list
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
                        # (Logic for NPCs, if they are stored differently)
                        pass

                    # --- Clear runtime combat states from game_state ---
                    if runtime_id in game_state.RUNTIME_MONSTER_HP:
                        game_state.RUNTIME_MONSTER_HP.pop(runtime_id, None)
                    # ---
                    
                    broadcast_callback(room_id_to_respawn_in, f"{entity_display_name} has appeared.", "ambient_spawn")
                    respawned_entity_runtime_ids_to_remove.append(runtime_id)
    
    for runtime_id_key_to_remove in respawned_entity_runtime_ids_to_remove:
        if config.DEBUG_MODE: print(f"{log_time_prefix} - RESPAWN_SYSTEM_CLEANUP: Removing '{runtime_id_key_to_remove}' from DEFEATED_MONSTERS.")
        tracked_defeated_entities_dict.pop(runtime_id_key_to_remove, None)