# mud_backend/core/loot_system.py
import random
import uuid
import copy
import time
import math
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from mud_backend import config

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

class TreasureManager:
    """
    Manages dynamic treasure generation based on hunting pressure.
    Implements the 'Gemstone IV' style system where over-hunting reduces loot quality.
    """
    def __init__(self, world: 'World'):
        self.world = world
        # Stores kill counts: {monster_id: pressure_value}
        self.hunting_pressure: Dict[str, float] = {} 
        self.last_decay_time = time.time()
        
        # Caches for dynamic generation
        self.gems_by_tier = {}      # tier (1-10) -> list of item_ids
        self.items_by_tier = {}     # tier (1-10) -> list of item_ids
        self.boxes_by_tier = {}     # tier (1-10) -> list of item_ids
        
        self._initialized = False

    def initialize_caches(self):
        """
        Scans all game items and buckets them into value tiers (1-10).
        """
        if self._initialized: return
        
        items = self.world.game_items
        count = 0
        for item_id, item in items.items():
            if item.get("item_type") == "quest": continue
            
            val = item.get("base_value", 0)
            tier = self._calculate_tier(val)
            
            # Categorize based on strict Item Type
            if item.get("item_type") == "gem":
                if tier not in self.gems_by_tier: self.gems_by_tier[tier] = []
                self.gems_by_tier[tier].append(item_id)
            
            elif item.get("item_type") == "treasure_chest":
                 if tier not in self.boxes_by_tier: self.boxes_by_tier[tier] = []
                 self.boxes_by_tier[tier].append(item_id)
            
            elif item.get("base_value", 0) > 0 and not item.get("is_npc_only") and item.get("item_type") != "container":
                 # General items (Weapons, Armor, Clothing, etc)
                 # Explicitly excluding 'container' type (backpacks) from random loot drops for now
                 if tier not in self.items_by_tier: self.items_by_tier[tier] = []
                 self.items_by_tier[tier].append(item_id)
            
            count += 1

        self._initialized = True
        print(f"[TREASURE] Indexed {count} items into value tiers.")

    def _calculate_tier(self, value: int) -> int:
        """Maps silver value to a 1-10 tier."""
        if value < 50: return 1
        if value < 150: return 2
        if value < 300: return 3
        if value < 600: return 4
        if value < 1000: return 5
        if value < 2000: return 6
        if value < 4000: return 7
        if value < 8000: return 8
        if value < 16000: return 9
        return 10

    def register_kill(self, monster_id: str):
        """Increases hunting pressure on a specific monster type."""
        current = self.hunting_pressure.get(monster_id, 0.0)
        self.hunting_pressure[monster_id] = current + 1.0

    def decay_pressure(self):
        """
        Called periodically to reduce hunting pressure.
        Allows over-hunted mobs to recover value over time.
        """
        now = time.time()
        # Decay check every minute
        if now - self.last_decay_time < 60: return 
        
        decay_amount = 0.5 # Reduces pressure count
        
        for mid in list(self.hunting_pressure.keys()):
            new_val = max(0.0, self.hunting_pressure[mid] - decay_amount)
            if new_val == 0:
                del self.hunting_pressure[mid]
            else:
                self.hunting_pressure[mid] = new_val
        
        self.last_decay_time = now

    def get_hunting_modifier(self, monster_id: str) -> int:
        """
        Calculates the Treasure Level modifier based on pressure.
        Positive = Underhunted (Bonus loot).
        Negative = Overhunted (Junk loot).
        """
        pressure = self.hunting_pressure.get(monster_id, 0)
        
        # Formula: 
        # 0 pressure -> +2 bonus
        # 5 pressure -> 0 (Baseline)
        # 10+ pressure -> -3 penalty (max)
        
        # Start with a small bonus for fresh mobs
        base_mod = 2.0
        
        # Subtract pressure
        # e.g. 0 kills -> +2
        # 5 kills/min -> 2 - (5*0.4) = 0
        # 10 kills/min -> 2 - (10*0.4) = -2
        mod = base_mod - (pressure * 0.4)
        
        # Cap limits
        mod = max(-5, min(5, mod))
        
        return int(mod)

    def generate_dynamic_loot(self, monster_template: Dict) -> List[Dict]:
        """
        Generates a list of item objects (dicts) based on the creature's 
        stats and current hunting pressure.
        """
        if not self._initialized: self.initialize_caches()
        
        monster_id = monster_template.get("monster_id")
        # Determine Base Treasure Level (1-10)
        # Can be set in template, otherwise derived from Level
        base_treasure_level = monster_template.get("treasure_level", 0)
        if base_treasure_level == 0:
            level = monster_template.get("level", 1)
            base_treasure_level = math.ceil(level / 3) # Lvl 30 = Tier 10
        
        # Apply Modifier
        modifier = self.get_hunting_modifier(monster_id)
        adjusted_level = base_treasure_level + modifier
        
        # Min tier 1, Max tier 10 (can overflow slightly for gems/boxes)
        adjusted_level = max(1, min(12, adjusted_level))
        
        loot = []
        
        # --- 1. Silvers (35% chance) ---
        if random.random() < 0.35:
            base_silver = adjusted_level * 25
            # Variance: 50% to 200%
            amount = random.randint(base_silver // 2, base_silver * 2)
            if amount > 0:
                coin_obj = {
                    "uid": uuid.uuid4().hex,
                    "name": f"a pile of {amount} silver",
                    "keywords": ["silver", "coins", "pile"],
                    "description": "A small pile of silver coins.",
                    "item_type": "currency",
                    "value": amount,
                    "is_item": True,
                    "verbs": ["GET"]
                }
                loot.append(coin_obj)

        # --- 2. Gems (60% chance) ---
        if random.random() < 0.60:
            # Tier is random 1 to AdjustedLevel
            tier_roll = random.randint(1, min(10, adjusted_level))
            
            potential_gems = self.gems_by_tier.get(tier_roll, [])
            # Fallback to lower tiers if current is empty
            while not potential_gems and tier_roll > 1:
                tier_roll -= 1
                potential_gems = self.gems_by_tier.get(tier_roll, [])
            
            if potential_gems:
                gem_id = random.choice(potential_gems)
                item = self._hydrate_item(gem_id)
                if item: loot.append(item)

        # --- 3. Items (30% chance) ---
        if random.random() < 0.30:
             tier_roll = random.randint(1, min(10, adjusted_level))
             potential_items = self.items_by_tier.get(tier_roll, [])
             
             # Fallback
             while not potential_items and tier_roll > 1:
                tier_roll -= 1
                potential_items = self.items_by_tier.get(tier_roll, [])

             if potential_items:
                 item_id = random.choice(potential_items)
                 item = self._hydrate_item(item_id)
                 if item: loot.append(item)
                 
        # --- 4. Chests/Boxes (11% chance) ---
        if random.random() < 0.11:
            # Boxes are high value, usually Tier 5+ unless low level mob
            box_tier = max(1, min(10, adjusted_level))
            potential_boxes = self.boxes_by_tier.get(box_tier, [])
            
            # Fallback logic
            if not potential_boxes:
                 # Try finding ANY box
                 for t in range(1, 11):
                     if self.boxes_by_tier.get(t):
                         potential_boxes = self.boxes_by_tier[t]
                         break
            
            if potential_boxes:
                box_id = random.choice(potential_boxes)
                box = self._hydrate_item(box_id)
                if box:
                    # FILL THE BOX
                    box_contents = []
                    
                    # Guaranteed Gem inside box
                    gem_tier = min(10, adjusted_level + 1)
                    gems = self.gems_by_tier.get(gem_tier, [])
                    if gems:
                        g = self._hydrate_item(random.choice(gems))
                        if g: box_contents.append(g)
                    
                    # Silver inside box
                    amt = random.randint(adjusted_level * 50, adjusted_level * 200)
                    s_obj = {
                        "uid": uuid.uuid4().hex,
                        "name": f"{amt} silver coins",
                        "keywords": ["silver", "coins"],
                        "item_type": "currency",
                        "value": amt,
                        "is_item": True
                    }
                    box_contents.append(s_obj)
                    
                    # Lock state (if locking implemented)
                    # box["is_locked"] = True 
                    
                    box["items"] = box_contents
                    box["is_closed"] = True 
                    loot.append(box)

        return loot

    def _hydrate_item(self, item_id):
        t = self.world.game_items.get(item_id)
        if t:
            i = copy.deepcopy(t)
            i["uid"] = uuid.uuid4().hex
            return i
        return None

def generate_loot_from_table(world: 'World', table_id: str) -> List[Dict[str, Any]]:
    # (Supports Generic Loot Tables)
    # Accepts "world" or a Mock object with game_loot_tables
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
        "items": [], # Will contain DICT objects, not IDs
        "keywords": ["corpse", "body", "remains"],
        "decay_time": time.time() + 300,
        # Persist info for Search/Skin
        "original_template_key": defeated_entity_template.get("monster_id"),
        "original_template": defeated_entity_template, # Keep ref for dynamic generation
        "original_name": defeated_entity_template.get("name"),
        "skinnable": defeated_entity_template.get("skinnable", False),
        "skinned": False,
        "dynamic_loot_generated": False # Flag for Search
    }
    
    # Generate Static Loot (from JSON tables) immediately
    class MockWorld:
        def __init__(self):
            self.game_loot_tables = game_loot_tables
            self.game_items = game_items_data
    
    mock_world = MockWorld()
    loot_table_id = defeated_entity_template.get("loot_table_id")
    
    if loot_table_id:
        generated_loot = generate_loot_from_table(mock_world, loot_table_id)
        corpse_data["items"].extend(generated_loot)

    # Drop Equipped items (Chance)
    equipped = defeated_entity_template.get("equipped", {})
    for slot, item_id in equipped.items():
        if item_id and random.random() < 0.05: # 5% chance to drop gear
            item_template = game_items_data.get(item_id)
            if item_template:
                dropped_item = copy.deepcopy(item_template)
                dropped_item["uid"] = uuid.uuid4().hex
                corpse_data["items"].append(dropped_item)

    return corpse_data

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