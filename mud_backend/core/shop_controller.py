# mud_backend/core/shop_controller.py
import json
import os
import random
import time
import copy
import uuid
from mud_backend import config

class ShopController:
    def __init__(self, shop_filename, room, world):
        self.filename = shop_filename
        self.room = room
        self.world = world
        
        # 1. Load the Static Template (Read-Only)
        self.template = self._load_template()
        
        # 2. Load or Initialize the Dynamic State (Stored in Room Data)
        self.state = self._load_or_create_state()
        
        # 3. Run Logic
        self._simulate_economy()  # Drain/Regen inventory based on time
        self.check_schedule()     # Update NPC
        self.refresh_display_case() # Update physical display case

    def _load_template(self):
        """Loads the static JSON definition."""
        path = os.path.join(config.DATA_PATH, "shops", self.filename)
        if not os.path.exists(path):
            return {"inventory": [], "balance": 0, "display_case_items": []}
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading shop template {self.filename}: {e}")
            return {}

    def _load_or_create_state(self):
        """
        Loads state from the Room's persistence data. 
        If missing, initializes it from the template.
        """
        # If state exists in the room DB, return it
        if "shop_state" in self.room.data:
            return self.room.data["shop_state"]

        # Otherwise, create a fresh state from the template
        initial_state = {
            "balance": self.template.get("balance", 1000),
            "last_tick_time": time.time(),
            "inventory": copy.deepcopy(self.template.get("inventory", [])),
            "display_case_items": [] # IDs of items currently in the case
        }
        
        # Save immediately to DB
        self.room.data["shop_state"] = initial_state
        self.world.save_room(self.room)
        return initial_state

    def save_state(self):
        """Saves the dynamic state to the Room Data (Database), NOT the JSON file."""
        self.room.data["shop_state"] = self.state
        self.world.save_room(self.room)

    def _simulate_economy(self):
        """
        Drains and replenishes items based on elapsed time to simulate a living economy.
        """
        now = time.time()
        last_tick = self.state.get("last_tick_time", now)
        elapsed = now - last_tick
        
        # Only process if at least 5 minutes (300s) have passed
        if elapsed < 300:
            return

        # Template for max limits
        template_inv = {item["id"]: item for item in self.template.get("inventory", [])}
        
        updated = False
        
        for item in self.state["inventory"]:
            item_id = item["id"]
            if item_id not in template_inv: continue
            
            max_qty = template_inv[item_id].get("qty", 10)
            current_qty = item["qty"]
            
            # 1. Drain (Simulate Sales): 10% chance to lose 1-3 items
            if current_qty > 0 and random.random() < 0.1:
                loss = random.randint(1, 3)
                item["qty"] = max(0, current_qty - loss)
                updated = True

            # 2. Replenish (Restock): 20% chance to gain 1-5 items up to max
            if current_qty < max_qty and random.random() < 0.2:
                gain = random.randint(1, 5)
                item["qty"] = min(max_qty, current_qty + gain)
                updated = True

        if updated:
            self.state["last_tick_time"] = now
            self.save_state()

    def check_schedule(self):
        """Updates the NPC in the room based on the time of day."""
        if "schedule" not in self.template:
            return

        schedule = self.template["schedule"]
        current_hour = time.localtime().tm_hour 
        
        day_start = schedule.get("day_start", 6)
        night_start = schedule.get("night_start", 20)
        
        target_npc_data = schedule.get("day_npc") if day_start <= current_hour < night_start else schedule.get("night_npc")
        if not target_npc_data: return

        # Sync NPC logic (removed for brevity, essentially same as before but checks room.data['objects'])
        # We need to ensure the NPC is in room.data["objects"] for persistence
        
        # (Simplified NPC swap logic here for robustness)
        # Check if we need to swap
        needs_swap = True
        
        # Look in ROOM DATA, not just live objects
        current_objects = self.room.data.get("objects", [])
        for obj in current_objects:
            if obj.get("is_npc") and obj.get("shop_data"):
                if obj.get("name") == target_npc_data["name"]:
                    needs_swap = False
                else:
                    # Remove wrong NPC from data
                    current_objects.remove(obj)
                    self.world.broadcast_to_room(self.room.room_id, f"{obj['name']} finishes their shift.", "general")
                break
        
        if needs_swap:
            new_npc = {
                "uid": uuid.uuid4().hex,
                "name": target_npc_data["name"],
                "keywords": target_npc_data.get("keywords", ["shopkeeper"]),
                "description": target_npc_data["description"],
                "is_npc": True,
                "shop_data": {"enabled": True},
                "verbs": ["look", "talk to", "give", "list", "order", "buy"]
            }
            if "objects" not in self.room.data: self.room.data["objects"] = []
            self.room.data["objects"].append(new_npc)
            self.world.broadcast_to_room(self.room.room_id, f"{target_npc_data['name']} arrives to tend the shop.", "general")
            self.world.save_room(self.room)

    def refresh_display_case(self):
        """
        Populates the display case by modifying the ROOM DATA directly.
        This ensures changes persist through re-hydration.
        """
        # 1. Find the case stub in persistent data
        case_stub = None
        if "objects" in self.room.data:
            for obj in self.room.data["objects"]:
                if "display case" in obj.get("name", "").lower():
                    case_stub = obj
                    break
        
        if not case_stub: return

        # 2. Check logic
        if "container_storage" not in case_stub: case_stub["container_storage"] = {}
        current_contents = case_stub["container_storage"].get("in", [])

        # Refill if empty
        if not current_contents:
            inventory = [i for i in self.state["inventory"] if i["qty"] > 0]
            if inventory:
                # Pick 3 random items
                selected = random.sample(inventory, min(3, len(inventory)))
                new_items = []
                for item_def in selected:
                    item_obj = copy.deepcopy(item_def)
                    item_obj["uid"] = uuid.uuid4().hex
                    item_obj["description"] += " (On display)"
                    # Remove quantity tracking for the physical display copy
                    item_obj.pop("qty", None)
                    new_items.append(item_obj)
                
                case_stub["container_storage"]["in"] = new_items
                self.world.save_room(self.room)

    def get_inventory(self):
        return self.state.get("inventory", [])

    def find_item_index_by_keyword(self, keyword):
        keyword = keyword.lower()
        for idx, item in enumerate(self.state.get("inventory", [])):
            if keyword in item.get("name", "").lower() or keyword in item.get("keywords", []):
                return idx
        return -1

    def buy_item(self, item_index, quantity, player):
        inventory = self.state.get("inventory", [])
        if item_index < 0 or item_index >= len(inventory):
            return None, "Invalid item selection."
            
        item_ref = inventory[item_index]
        if item_ref["qty"] < quantity:
            return None, "Not enough stock available."
            
        cost = item_ref["base_value"] * quantity
        if player.wealth["silvers"] < cost:
            return None, f"You cannot afford that. Cost: {cost}."
            
        # Transact
        player.wealth["silvers"] -= cost
        item_ref["qty"] -= quantity
        self.state["balance"] += cost
        
        # Save state to Room Data
        self.save_state()
        
        items_to_give = []
        for _ in range(quantity):
            new_item = copy.deepcopy(item_ref)
            new_item["uid"] = uuid.uuid4().hex
            new_item.pop("qty", None)
            new_item.pop("id", None)
            items_to_give.append(new_item)
            
        return items_to_give, f"You buy {quantity} x {item_ref['name']} for {cost} silver."

    def get_keeper_name(self):
        # Check persistent objects
        for obj in self.room.data.get("objects", []):
            if obj.get("is_npc") and obj.get("shop_data"):
                return obj.get("name")
        return "The Shopkeeper"