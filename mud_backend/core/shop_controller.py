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
        self.data = self._load_data()
        
        # Initialize
        self.check_schedule()
        self.refresh_display_case()

    def _load_data(self):
        path = os.path.join(config.DATA_PATH, "shops", self.filename)
        if not os.path.exists(path):
            return {"inventory": [], "balance": 0, "display_case_items": []}
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading shop data {self.filename}: {e}")
            return {}

    def save_data(self):
        path = os.path.join(config.DATA_PATH, "shops", self.filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=4)
        except Exception as e:
            print(f"Error saving shop data {self.filename}: {e}")

    def check_schedule(self):
        """Updates the NPC in the room based on the time of day."""
        if "schedule" not in self.data:
            return

        schedule = self.data["schedule"]
        current_hour = time.localtime().tm_hour 
        
        day_start = schedule.get("day_start", 6)
        night_start = schedule.get("night_start", 20)
        
        target_npc_data = None
        if day_start <= current_hour < night_start:
            target_npc_data = schedule.get("day_npc")
        else:
            target_npc_data = schedule.get("night_npc")
            
        if not target_npc_data:
            return

        # Check if correct NPC is present
        npc_present = False
        to_remove = []
        
        for obj in self.room.objects:
            if obj.get("is_npc") and obj.get("shop_data"):
                if obj.get("name") == target_npc_data["name"]:
                    npc_present = True
                else:
                    to_remove.append(obj)
        
        for obj in to_remove:
            self.room.objects.remove(obj)
            self.world.broadcast_to_room(self.room, f"{obj['name']} finishes their shift and leaves.")

        if not npc_present:
            new_npc = {
                "name": target_npc_data["name"],
                "keywords": target_npc_data.get("keywords", ["shopkeeper"]),
                "description": target_npc_data["description"],
                "is_npc": True,
                "shop_data": {"enabled": True}, 
                "verbs": ["look", "talk to", "give", "list", "order", "buy"]
            }
            self.room.objects.append(new_npc)
            self.world.broadcast_to_room(self.room, f"{target_npc_data['name']} arrives to tend the shop.")
            self.world.save_room(self.room)

    def refresh_display_case(self):
        """Populates the display case container with physical items from stock."""
        case = None
        for obj in self.room.objects:
            if "display case" in obj.get("name", "").lower():
                case = obj
                break
        
        if not case:
            return

        now = time.time()
        last_restock = self.data.get("last_restock_time", 0)
        interval = self.data.get("restock_interval", 3600)
        should_restock = (now - last_restock) > interval
        
        physically_empty = len(case.get("container_storage", {}).get("in", [])) == 0
        
        if should_restock or (physically_empty and self.data.get("display_case_items")):
            if should_restock:
                inventory = [i for i in self.data.get("inventory", []) if i.get("qty", 0) > 0]
                if inventory:
                    selected = random.sample(inventory, min(3, len(inventory)))
                    self.data["display_case_items"] = [item["id"] for item in selected]
                    self.data["last_restock_time"] = now
                    self.save_data()
            
            if "container_storage" not in case:
                case["container_storage"] = {}
            case["container_storage"]["in"] = []
            
            for item_id in self.data.get("display_case_items", []):
                item_def = next((i for i in self.data["inventory"] if i["id"] == item_id), None)
                if item_def:
                    item_obj = copy.deepcopy(item_def)
                    item_obj["uid"] = uuid.uuid4().hex
                    item_obj["description"] += " (On display)"
                    case["container_storage"]["in"].append(item_obj)
            
            self.world.save_room(self.room)

    def get_inventory(self):
        return self.data.get("inventory", [])

    def find_item_index_by_keyword(self, keyword):
        """Finds the first item in inventory matching the keyword."""
        keyword = keyword.lower()
        for idx, item in enumerate(self.data.get("inventory", [])):
            if keyword in item.get("name", "").lower() or keyword in item.get("keywords", []):
                return idx
        return -1

    def buy_item(self, item_index, quantity, player):
        inventory = self.data.get("inventory", [])
        if item_index < 0 or item_index >= len(inventory):
            return None, "Invalid item selection."
            
        item_ref = inventory[item_index]
        if item_ref["qty"] < quantity:
            return None, "Not enough stock available."
            
        cost = item_ref["base_value"] * quantity
        if player.wealth["silvers"] < cost:
            return None, f"You cannot afford that. Cost: {cost}."
            
        player.wealth["silvers"] -= cost
        item_ref["qty"] -= quantity
        self.data["balance"] += cost
        self.save_data()
        
        items_to_give = []
        for _ in range(quantity):
            new_item = copy.deepcopy(item_ref)
            new_item["uid"] = uuid.uuid4().hex
            new_item.pop("qty", None)
            new_item.pop("id", None)
            items_to_give.append(new_item)
            
        return items_to_give, f"You buy {quantity} x {item_ref['name']} for {cost} silver."

    def get_keeper_name(self):
        for obj in self.room.objects:
            if obj.get("is_npc") and obj.get("shop_data"):
                return obj.get("name")
        return "The Shopkeeper"