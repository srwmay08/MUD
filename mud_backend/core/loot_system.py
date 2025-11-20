# mud_backend/core/loot_system.py
import random
import uuid
import copy
import time
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

def generate_loot_from_table(world: 'World', table_id: str) -> List[Dict[str, Any]]:
    """
    Generates a list of item instances based on a weighted loot table.
    """
    # Access via property for backward compatibility or direct attribute
    loot_tables = getattr(world, "game_loot_tables", {}) 
    loot_table = loot_tables.get(table_id)
    
    if not loot_table:
        return []

    generated_items = []
    game_items = getattr(world, "game_items", {})

    # 1. Support for new "Weighted" format (Phase 3)
    if isinstance(loot_table, dict) and loot_table.get("type") == "weighted":
        entries = loot_table.get("entries", [])
        rolls = loot_table.get("rolls", 1)
        
        if not entries:
            return []

        population = []
        weights = []
        
        for entry in entries:
            population.append(entry)
            weights.append(entry.get("weight", 1))
            
        picks = random.choices(population, weights=weights, k=rolls)
        
        for pick in picks:
            item_id = pick.get("item_id")
            if item_id == "nothing" or not item_id:
                continue
                
            item_template = game_items.get(item_id)
            if item_template:
                new_item = copy.deepcopy(item_template)
                new_item["uid"] = uuid.uuid4().hex
                
                if "min" in pick and "max" in pick:
                    # Handle quantity if item supports it
                    pass
                
                generated_items.append(new_item)

    # 2. Fallback for legacy "List" format
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
    """
    Creates a container object representing the corpse.
    """
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
        "decay_time": time.time() + 300 
    }
    
    # Generate Loot using a Mock World wrapper to satisfy generate_loot_from_table signature
    class MockWorld:
        def __init__(self):
            self.game_loot_tables = game_loot_tables
            self.game_items = game_items_data
    
    mock_world = MockWorld()
    loot_table_id = defeated_entity_template.get("loot_table_id")
    
    if loot_table_id:
        generated_loot = generate_loot_from_table(mock_world, loot_table_id)
        corpse_data["items"].extend(generated_loot)

    # Drop Equipped Items (10% chance)
    equipped = defeated_entity_template.get("equipped", {})
    for slot, item_id in equipped.items():
        if item_id and random.random() < 0.10: 
            item_template = game_items_data.get(item_id)
            if item_template:
                dropped_item = copy.deepcopy(item_template)
                dropped_item["uid"] = uuid.uuid4().hex
                corpse_data["items"].append(dropped_item)

    return corpse_data

def process_corpse_decay(world: 'World') -> Dict[str, List[str]]:
    """
    Iterates active rooms to find and decay corpses.
    Returns a dictionary mapping room_ids to a list of decay messages.
    """
    decay_messages = {}
    current_time = time.time()
    
    # We only need to check Active Rooms
    # Iterate a copy of items to allow modification
    # Note: world.get_all_rooms() returns dicts, but we want to modify ActiveRoom objects directly if possible.
    # However, since corpse data is inside the object list, modifying the ActiveRoom.objects list works.
    
    # Use World lock because we are modifying room contents
    with world.room_lock:
        for room_id, room_obj in world.active_rooms.items():
            objects_to_remove = []
            
            # Check objects in this room
            for obj in room_obj.objects:
                # Identify corpses by keywords or type (heuristics)
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
                
                # Save the room state change
                world.save_room(room_obj)
                
    return decay_messages