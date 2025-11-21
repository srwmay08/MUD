# mud_backend/core/loot_system.py
import random
import uuid
import copy
import time
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

def generate_loot_from_table(world: 'World', table_id: str) -> List[Dict[str, Any]]:
    loot_tables = getattr(world, "game_loot_tables", {}) 
    loot_table = loot_tables.get(table_id)
    
    if not loot_table: return []

    generated_items = []
    game_items = getattr(world, "game_items", {})

    if isinstance(loot_table, dict) and loot_table.get("type") == "weighted":
        entries = loot_table.get("entries", [])
        rolls = loot_table.get("rolls", 1)
        
        if not entries: return []
        population = []
        weights = []
        for entry in entries:
            population.append(entry)
            weights.append(entry.get("weight", 1))
        
        if not population: return []
        
        picks = random.choices(population, weights=weights, k=rolls)
        
        for pick in picks:
            item_id = pick.get("item_id")
            if item_id == "nothing" or not item_id: continue
            item_template = game_items.get(item_id)
            if item_template:
                new_item = copy.deepcopy(item_template)
                new_item["uid"] = uuid.uuid4().hex
                generated_items.append(new_item)

    elif isinstance(loot_table, list):
        for entry in loot_table:
            chance = entry.get("chance", 0.0)
            if random.random() < chance:
                item_id = entry.get("item_id")
                item_template = game_items.get(item_id)
                if item_template:
                    new_item = copy.deepcopy(item_template)
                    new_item["uid"] = uuid.uuid4().hex
                    generated_items.append(new_item)

    return generated_items

def create_corpse_object_data(defeated_entity_template, defeated_entity_runtime_id, game_items_data, game_loot_tables, game_equipment_tables_data):
    corpse_name = f"corpse of {defeated_entity_template['name']}"
    corpse_desc = f"The dead body of {defeated_entity_template['name']} lies here."
    
    corpse_data = {
        "uid": uuid.uuid4().hex,
        "name": corpse_name,
        "description": corpse_desc,
        "type": "container",
        "is_container": True,
        "is_open": True,
        "capacity": 100,
        "items": [],
        "keywords": ["corpse", "body", "remains"],
        "decay_time": time.time() + 300,
        # Persist skinning info
        "original_template_key": defeated_entity_template.get("monster_id"),
        "original_name": defeated_entity_template.get("name"),
        "skinnable": defeated_entity_template.get("skinnable", False),
        "skinned": False
    }
    
    # Generate Loot using a Mock World wrapper
    class MockWorld:
        def __init__(self):
            self.game_loot_tables = game_loot_tables
            self.game_items = game_items_data
    
    mock_world = MockWorld()
    loot_table_id = defeated_entity_template.get("loot_table_id")
    
    if loot_table_id:
        generated_loot = generate_loot_from_table(mock_world, loot_table_id)
        corpse_data["items"].extend(generated_loot)

    equipped = defeated_entity_template.get("equipped", {})
    for slot, item_id in equipped.items():
        if item_id and random.random() < 0.10: 
            item_template = game_items_data.get(item_id)
            if item_template:
                dropped_item = copy.deepcopy(item_template)
                dropped_item["uid"] = uuid.uuid4().hex
                corpse_data["items"].append(dropped_item)

    return corpse_data

# --- NEW: SKINNING LOOT GEN ---
def generate_skinning_loot(monster_template: dict, player_skill_value: int, game_items_data: dict) -> list:
    """
    Calculates skinning success and returns a list of item_ids (yields).
    """
    skinning_config = monster_template.get("skinning", {})
    if not skinning_config:
        return []
        
    base_dc = skinning_config.get("base_dc", 10)
    success_item = skinning_config.get("item_yield_success_key")
    failed_item = skinning_config.get("item_yield_failed_key")
    
    # Roll: Skill + d100 vs DC
    roll = player_skill_value + random.randint(1, 100)
    
    if roll >= base_dc:
        return [success_item] if success_item else []
    else:
        return [failed_item] if failed_item else []

def process_corpse_decay(world: 'World') -> Dict[str, List[str]]:
    decay_messages = {}
    current_time = time.time()
    
    # Use directory lock for the snapshot
    with world.room_directory_lock:
        active_room_ids = list(world.active_rooms.keys())

    for room_id in active_room_ids:
        room_obj = world.get_active_room_safe(room_id)
        if not room_obj: continue
        
        with room_obj.lock:
            objects_to_remove = []
            
            for obj in room_obj.objects:
                if obj.get("type") == "container" and "corpse" in obj.get("keywords", []):
                    decay_at = obj.get("decay_time", 0)
                    if decay_at > 0 and current_time >= decay_at:
                        objects_to_remove.append(obj)
            
            if objects_to_remove:
                if room_id not in decay_messages:
                    decay_messages[room_id] = []
                
                for obj in objects_to_remove:
                    room_obj.objects.remove(obj)
                    decay_messages[room_id].append(f"The {obj['name']} decays into dust.")
                
                world.save_room(room_obj)
                
    return decay_messages