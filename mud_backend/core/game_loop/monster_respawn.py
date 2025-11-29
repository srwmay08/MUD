# mud_backend/core/game_loop/monster_respawn.py
import random
import time
import copy 
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

from mud_backend import config
from mud_backend.core import combat_system
from mud_backend.core import faction_handler


def _re_equip_entity_from_template(entity_runtime_data, entity_template, game_equipment_tables, game_items):
    """
    Helper to re-populate a monster's equipment from its template.
    """
    if not entity_runtime_data or not entity_template:
        return

    entity_runtime_data["equipped"] = {slot_key_cfg: None for slot_key_cfg in config.EQUIPMENT_SLOTS.keys()}
    
    template_equipped = entity_template.get("equipped", {})
    for slot, item_id in template_equipped.items():
        if slot in entity_runtime_data["equipped"]:
             entity_runtime_data["equipped"][slot] = item_id

    if "hp" not in entity_template and "max_hp" in entity_template:
         entity_runtime_data["hp"] = entity_template["max_hp"]
    elif "hp" in entity_template:
         entity_runtime_data["hp"] = entity_template["hp"]


def process_respawns(world: 'World',
                     log_time_prefix, 
                     broadcast_callback,
                     send_to_player_callback,
                     game_npcs_dict, 
                     game_equipment_tables_global, 
                     game_items_global             
                     ):
    
    current_time_float = time.time()
    all_defeated = world.get_all_defeated_monsters()
    respawned_entity_runtime_ids_to_remove = []
    
    for runtime_uid, respawn_info in all_defeated:
        entity_template_key = respawn_info.get("template_key")
        if not entity_template_key:
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

                active_room = world.get_active_room_safe(room_id_to_respawn_in)
                if not active_room:
                    world.get_room(room_id_to_respawn_in) # Forces hydration
                    active_room = world.get_active_room_safe(room_id_to_respawn_in)
                
                if not active_room:
                    continue
                
                with active_room.lock:
                    current_room_objects = active_room.objects
                    
                    base_template_data = None
                    if entity_type == "monster":
                        base_template_data = world.game_monster_templates.get(entity_template_key)
                    elif entity_type == "npc":
                         if entity_template_key:
                             base_template_data = world.game_monster_templates.get(entity_template_key)

                    if not base_template_data:
                        continue
                    
                    entity_display_name = base_template_data.get("name", entity_template_key)
                    
                    can_respawn_this_template_into_room = True
                    if is_template_unique: 
                        id_key_to_check = "monster_id" if entity_type == "monster" else "uid"
                        id_val_to_check = entity_template_key if entity_type == "monster" else runtime_uid
                        
                        if any(obj.get(id_key_to_check) == id_val_to_check for obj in current_room_objects):
                            can_respawn_this_template_into_room = False
                    
                    if can_respawn_this_template_into_room:
                        new_entity = copy.deepcopy(base_template_data)
                        
                        if entity_type == "monster":
                            new_monster_uid = uuid.uuid4().hex
                            new_entity["uid"] = new_monster_uid
                            monster_id_to_check = new_monster_uid 
                            
                            # --- LEVEL RANGE LOGIC ---
                            level_range = new_entity.get("level_range")
                            if level_range and isinstance(level_range, list) and len(level_range) == 2:
                                min_lvl, max_lvl = level_range
                                actual_level = random.randint(min_lvl, max_lvl)
                                new_entity["level"] = actual_level
                                # Scale HP: +10% per level above minimum? Or base it on template.
                                # Simple scaling: If template HP is for level X, scale by ratio.
                                base_level = new_entity.get("level", 1) # This is the template default
                                if actual_level > base_level:
                                    ratio = 1.0 + ((actual_level - base_level) * 0.1)
                                    new_entity["max_hp"] = int(new_entity.get("max_hp", 10) * ratio)
                                    new_entity["hp"] = new_entity["max_hp"]
                            # -------------------------

                        else: # NPC
                            new_entity["uid"] = runtime_uid 
                            monster_id_to_check = runtime_uid
                            new_entity["hp"] = new_entity.get("max_hp", 50)

                        active_room.objects.append(new_entity)

                        # Register in Spatial Index
                        world.register_mob(monster_id_to_check, room_id_to_respawn_in)
                        
                        broadcast_callback(room_id_to_respawn_in, f"The {entity_display_name} appears.", "ambient_spawn")
                        world.remove_monster_hp(runtime_uid)
                        
                        # --- AGGRO CHECK ---
                        is_aggressive = base_template_data.get("is_aggressive", False)
                        players_in_world = world.get_all_players_info()
                        
                        for p_name, p_data in players_in_world:
                            if p_data.get("current_room_id") == room_id_to_respawn_in:
                                player_obj = p_data.get("player_obj")
                                if not player_obj: continue
                                player_id = player_obj.name.lower()
                                
                                is_kos = faction_handler.is_player_kos_to_entity(player_obj, base_template_data)
                                
                                player_state = world.get_combat_state(player_id)
                                player_in_combat = player_state and player_state.get("state_type") == "combat"

                                if (is_aggressive or is_kos) and not player_in_combat:
                                    send_to_player_callback(player_obj.name, f"The **{entity_display_name}** notices you and attacks!", "combat_other")
                                    monster_rt = combat_system.calculate_roundtime(base_template_data.get("stats", {}).get("AGI", 50))
                                    
                                    world.set_combat_state(monster_id_to_check, {
                                        "state_type": "combat",
                                        "target_id": player_id,
                                        "next_action_time": current_time_float,
                                        "current_room_id": room_id_to_respawn_in
                                    })
                                    world.set_monster_hp(monster_id_to_check, new_entity.get("max_hp", 50))
                                    break 

                        respawned_entity_runtime_ids_to_remove.append(runtime_uid)
                
                world.save_room(active_room)
                
    for runtime_uid_to_remove in respawned_entity_runtime_ids_to_remove:
        world.remove_defeated_monster(runtime_uid_to_remove)