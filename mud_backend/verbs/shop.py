# mud_backend/verbs/shop.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core import db
import math
import random 
import time
from typing import Tuple, Optional, Dict, Any, Union
from mud_backend.core.registry import VerbRegistry 
import uuid

def _find_item_in_hands(player, game_items_data: Dict[str, Any], target_name: str) -> Tuple[Optional[Any], Optional[str]]:
    for slot in ["mainhand", "offhand"]:
        item_ref = player.worn_items.get(slot)
        if item_ref:
            if isinstance(item_ref, dict): item_data = item_ref
            else: item_data = game_items_data.get(item_ref)
            
            if item_data:
                if (target_name == item_data.get("name", "").lower() or 
                    target_name in item_data.get("keywords", [])):
                    return item_ref, slot
    return None, None

def _find_item_in_inventory(player, game_items_data: Dict[str, Any], target_name: str) -> Any | None:
    for item_ref in player.inventory:
        if isinstance(item_ref, dict): item_data = item_ref
        else: item_data = game_items_data.get(item_ref)
        
        if item_data:
            if (target_name == item_data.get("name", "").lower() or 
                target_name in item_data.get("keywords", [])):
                return item_ref
    return None

def _get_shop_data(room) -> dict | None:
    """Helper to get shop data from a room."""
    for obj in room.objects:
        if "shop_data" in obj:
            s_data = obj.get("shop_data")
            if s_data and isinstance(s_data, dict):
                return s_data
    return None

def _get_supply_demand_modifier(shop_data: dict, item_type: str) -> float:
    counts = shop_data.get("sold_counts", {})
    count = counts.get(item_type, 0)
    reduction = count * 0.05
    return max(0.5, 1.0 - reduction)

def _get_item_buy_price(item_ref: Union[str, Dict[str, Any]], game_items_data: Dict[str, Any], shop_data: Optional[dict] = None) -> int:
    if isinstance(item_ref, dict): item_data = item_ref
    else: item_data = game_items_data.get(item_ref)
    
    if not item_data: return 0
    
    base = item_data.get("base_value", 0) * 2
    
    if shop_data:
        itype = item_data.get("type", "misc")
        if "weapon_type" in item_data: itype = "weapon"
        elif "armor_type" in item_data: itype = "armor"
        
        mod = _get_supply_demand_modifier(shop_data, itype)
        return int(base * mod)
        
    return base

def _get_item_sell_price(item_ref: Union[str, Dict[str, Any]], game_items_data: Dict[str, Any], shop_data: Optional[dict] = None) -> int:
    if isinstance(item_ref, dict): item_data = item_ref
    else: item_data = game_items_data.get(item_ref)

    if not item_data: return 0
        
    base_val = item_data.get("base_value", 0)
    
    if shop_data:
        itype = item_data.get("type", "misc")
        if "weapon_type" in item_data: itype = "weapon"
        elif "armor_type" in item_data: itype = "armor"
        
        mod = _get_supply_demand_modifier(shop_data, itype)
        base_val = int(base_val * mod)

    max_val = item_data.get("max_value") 
    if max_val and max_val > base_val:
        return random.randint(base_val, max_val)
        
    return base_val

@VerbRegistry.register(["list"]) 
class List(BaseVerb):
    def execute(self):
        shop_data = _get_shop_data(self.room)
        if not shop_data:
            if self.player.game_state == "training":
                self.player.send_message("You must 'check in' at the inn to train.")
                return
            self.player.send_message("You can't seem to shop here.")
            return
            
        inventory = shop_data.get("inventory", [])
        if not inventory:
            self.player.send_message("The shop has nothing for sale right now.")
            return

        self.player.send_message("--- Items for Sale ---")
        self.player.send_message("Use 'LOOK ON <CATEGORY> TABLE' to browse specific items.")
        
        game_items = self.world.game_items
        count = 0
        for item_ref in inventory:
            if count > 10: 
                self.player.send_message("... and many more items.")
                break
            if isinstance(item_ref, dict): name = item_ref.get("name")
            else: name = game_items.get(item_ref, {}).get("name", "An item")
            
            price = _get_item_buy_price(item_ref, game_items, shop_data)
            self.player.send_message(f"- {name:<30} {price} silver")
            count += 1
            
@VerbRegistry.register(["buy", "order"]) 
class Buy(BaseVerb):
    def execute(self):
        shop_data = _get_shop_data(self.room)
        if not shop_data:
            self.player.send_message("You can't seem to shop here.")
            return
            
        if not self.args:
            self.player.send_message("What do you want to buy?")
            return
            
        target_name = " ".join(self.args).lower()
        game_items = self.world.game_items
        
        item_to_buy = None
        item_index = -1
        
        for idx, item_ref in enumerate(shop_data.get("inventory", [])):
            if isinstance(item_ref, dict): item_data = item_ref
            else: item_data = game_items.get(item_ref)
            
            if item_data:
                if (target_name == item_data.get("name", "").lower() or 
                    target_name in item_data.get("keywords", [])):
                    item_to_buy = item_ref
                    item_index = idx
                    break
        
        if not item_to_buy:
            self.player.send_message("That item is not for sale here.")
            return
            
        price = _get_item_buy_price(item_to_buy, game_items, shop_data)
        player_silver = self.player.wealth.get("silvers", 0)
        
        if player_silver < price:
            self.player.send_message(f"You can't afford that. It costs {price} silver and you have {player_silver}.")
            return
            
        self.player.wealth["silvers"] = player_silver - price
        
        if isinstance(item_to_buy, dict):
             import copy
             new_item = copy.deepcopy(item_to_buy)
             new_item["uid"] = uuid.uuid4().hex
             self.player.inventory.append(new_item)
             name = new_item.get("name")
        else:
             self.player.inventory.append(item_to_buy)
             name = game_items.get(item_to_buy, {}).get("name", "the item")
        
        shop_data["inventory"].pop(item_index)
        
        if isinstance(item_to_buy, dict): itype = item_to_buy.get("type", "misc")
        else: itype = game_items.get(item_to_buy, {}).get("type", "misc")
        
        if "sold_counts" in shop_data:
             if itype in shop_data["sold_counts"] and shop_data["sold_counts"][itype] > 0:
                 shop_data["sold_counts"][itype] -= 1

        self.player.send_message(f"You buy {name} for {price} silver.")

@VerbRegistry.register(["appraise"])
class Appraise(BaseVerb):
    def execute(self):
        shop_data = _get_shop_data(self.room)
        if not shop_data:
            self.player.send_message("You can't seem to shop here.")
            return

        if not self.args:
            self.player.send_message("Appraise what?")
            return

        target_name = " ".join(self.args).lower()
        game_items = self.world.game_items
        
        item_ref, loc = _find_item_in_hands(self.player, game_items, target_name)
        if not item_ref:
            item_ref = _find_item_in_inventory(self.player, game_items, target_name)
            
        if item_ref:
            price = _get_item_sell_price(item_ref, game_items, shop_data)
            name = ""
            if isinstance(item_ref, dict): name = item_ref.get("name")
            else: name = game_items.get(item_ref, {}).get("name")
            
            self.player.send_message(f"The pawnbroker glances at your {name}. 'I'd give you {price} silver for that.'")
            return
            
        for item_ref in shop_data.get("inventory", []):
            if isinstance(item_ref, dict): t_data = item_ref
            else: t_data = game_items.get(item_ref)
            
            if t_data and (target_name == t_data.get("name", "").lower() or target_name in t_data.get("keywords", [])):
                price = _get_item_buy_price(item_ref, game_items, shop_data)
                self.player.send_message(f"The pawnbroker says, 'That {t_data['name']} is worth {price} silver.'")
                return
        
        self.player.send_message(f"You don't have or see a '{target_name}'.")

@VerbRegistry.register(["sell"]) 
class Sell(BaseVerb):
    def execute(self):
        shop_data = _get_shop_data(self.room)
        if not shop_data:
            self.player.send_message("You can't seem to shop here.")
            return

        if not self.args:
            self.player.send_message("What do you want to sell?")
            return

        target_name = " ".join(self.args).lower()
        game_items = self.world.game_items
        
        item_ref, hand_slot = _find_item_in_hands(self.player, game_items, target_name)
        if not item_ref:
            self.player.send_message(f"You aren't holding a '{target_name}'.")
            return
            
        item_uid = item_ref.get("uid") if isinstance(item_ref, dict) else item_ref
        if item_uid in self.player.flags.get("marked_items", []):
            self.player.send_message(f"You have marked that item. You cannot sell it until you UNMARK it.")
            return

        price = _get_item_sell_price(item_ref, game_items, shop_data)
        
        if price <= 0:
            self.player.send_message("The pawnbroker shakes their head. 'Not worth my time.'")
            return
            
        self.player.worn_items[hand_slot] = None
        self.player.wealth["silvers"] = self.player.wealth.get("silvers", 0) + price
        
        if isinstance(item_ref, dict):
            new_stock = item_ref
        else:
            base_data = game_items.get(item_ref)
            if base_data:
                new_stock = base_data.copy()
                new_stock["uid"] = uuid.uuid4().hex
            else:
                new_stock = None
        
        if new_stock:
            new_stock["sold_timestamp"] = time.time()
            
            if "inventory" not in shop_data:
                shop_data["inventory"] = []
                
            shop_data["inventory"].append(new_stock)
            
            itype = new_stock.get("type", "misc")
            if "weapon_type" in new_stock: itype = "weapon"
            elif "armor_type" in new_stock: itype = "armor"
            
            if "sold_counts" not in shop_data:
                shop_data["sold_counts"] = {}
                
            shop_data["sold_counts"][itype] = shop_data["sold_counts"].get(itype, 0) + 1
            
            self.player.send_message(f"You sell {new_stock['name']} for {price} silver.")
            self.world.save_room(self.room)
        else:
            self.player.send_message("Error transferring item.")