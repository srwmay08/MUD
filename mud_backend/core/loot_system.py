# mud_backend/core/loot_system.py
import random
import uuid
import copy
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

def generate_loot_from_table(world: 'World', table_id: str) -> List[Dict[str, Any]]:
    """
    Generates a list of item instances based on a weighted loot table.
    Supports 'rolls' (how many times to pick) and 'nothing' drops.
    """
    loot_table = world.game_loot_tables.get(table_id)
    if not loot_table:
        return []

    generated_items = []
    
    # 1. Support for new "Weighted" format
    # Structure expected:
    # {
    #    "type": "weighted",
    #    "rolls": 1,
    #    "entries": [
    #        {"item_id": "iron_sword", "weight": 10},
    #        {"item_id": "gold_coin", "weight": 50, "min": 1, "max": 5},
    #        {"item_id": "nothing", "weight": 40}
    #    ]
    # }
    
    if isinstance(loot_table, dict) and loot_table.get("type") == "weighted":
        entries = loot_table.get("entries", [])
        rolls = loot_table.get("rolls", 1)
        
        if not entries:
            return []

        # Prepare weights for random.choices
        population = []
        weights = []
        
        for entry in entries:
            population.append(entry)
            weights.append(entry.get("weight", 1))
            
        # Perform weighted picks
        picks = random.choices(population, weights=weights, k=rolls)
        
        for pick in picks:
            item_id = pick.get("item_id")
            
            if item_id == "nothing" or not item_id:
                continue
                
            item_template = world.game_items.get(item_id)
            if item_template:
                new_item = copy.deepcopy(item_template)
                new_item["uid"] = uuid.uuid4().hex
                
                # Handle Quantities (e.g., Coins)
                if "min" in pick and "max" in pick:
                    qty = random.randint(pick["min"], pick["max"])
                    # Assuming item supports stacking logic, usually stored in 'quantity' or separate logic
                    # For now, we assume it might be currency or stackable
                    if new_item.get("type") == "currency":
                         # Specialized currency handling could go here
                         pass
                
                generated_items.append(new_item)

    # 2. Fallback support for legacy "List" format
    # Structure: [{"item_id": "sword", "chance": 0.1}, ...]
    elif isinstance(loot_table, list):
        for entry in loot_table:
            chance = entry.get("chance", 0.0)
            if random.random() < chance:
                item_id = entry.get("item_id")
                item_template = world.game_items.get(item_id)
                if item_template:
                    new_item = copy.deepcopy(item_template)
                    new_item["uid"] = uuid.uuid4().hex
                    generated_items.append(new_item)

    return generated_items

def create_corpse_object_data(defeated_entity_template, defeated_entity_runtime_id, game_items_data, game_loot_tables, game_equipment_tables_data):
    """
    Creates a container object representing the corpse.
    Populates it with loot generated from the entity's loot_table_id.
    """
    corpse_name = f"corpse of {defeated_entity_template['name']}"
    corpse_desc = f"The dead body of {defeated_entity_template['name']} lies here."
    
    corpse_data = {
        "uid": uuid.uuid4().hex,
        "name": corpse_name,
        "description": corpse_desc,
        "type": "container",
        "is_container": True,
        "is_open": True,  # Corpses usually start open/searchable
        "capacity": 100,
        "items": [],
        "keywords": ["corpse", "body", "remains"],
        "decay_time": 300 
    }
    
    # 1. Generate Loot
    loot_table_id = defeated_entity_template.get("loot_table_id")
    if loot_table_id:
        # We need a World reference here strictly speaking, but this function is usually called from Attack verb
        # which has access to world. 
        # To fix the architectural dependency without passing 'world' into this util function in every call,
        # we can grab the tables from the passed-in dictionaries.
        
        # Temporary mini-world context for the generator
        class MockWorld:
            def __init__(self):
                self.game_loot_tables = game_loot_tables
                self.game_items = game_items_data
        
        mock_world = MockWorld()
        generated_loot = generate_loot_from_table(mock_world, loot_table_id)
        corpse_data["items"].extend(generated_loot)

    # 2. Drop Equipped Items (Optional - simple chance)
    equipped = defeated_entity_template.get("equipped", {})
    for slot, item_id in equipped.items():
        # 10% chance to drop equipped gear?
        if item_id and random.random() < 0.10: 
            item_template = game_items_data.get(item_id)
            if item_template:
                dropped_item = copy.deepcopy(item_template)
                dropped_item["uid"] = uuid.uuid4().hex
                corpse_data["items"].append(dropped_item)

    return corpse_data