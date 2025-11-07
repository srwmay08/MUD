# mud_backend/verbs/shop.py
from mud_backend.verbs.base_verb import BaseVerb
# --- REFACTORED: Removed game_state import ---
from mud_backend.core import db
import math
import random 
from typing import Tuple, Optional, Dict, Any

# --- REFACTORED: Pass game_items_data ---
def _find_item_in_hands(player, game_items_data: Dict[str, Any], target_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Finds the first item_id in a player's hands that matches.
    Returns (item_id, slot_name) or (None, None)
    """
    for slot in ["mainhand", "offhand"]:
        item_id = player.worn_items.get(slot)
        if item_id:
            # --- FIX: Use passed game_items_data ---
            item_data = game_items_data.get(item_id)
            if item_data:
                if (target_name == item_data.get("name", "").lower() or 
                    target_name in item_data.get("keywords", [])):
                    return item_id, slot
    return None, None

# --- REFACTORED: Pass game_items_data ---
def _find_item_in_inventory(player, game_items_data: Dict[str, Any], target_name: str) -> str | None:
    """Finds the first item_id in a player's inventory that matches."""
    for item_id in player.inventory:
        # --- FIX: Use passed game_items_data ---
        item_data = game_items_data.get(item_id)
        if item_data:
            if (target_name == item_data.get("name", "").lower() or 
                target_name in item_data.get("keywords", [])):
                return item_id
    return None

def _get_shop_data(room) -> dict | None:
    """Helper to get shop data from a room."""
    for obj in room.objects:
        if obj.get("shop_data"):
            return obj.get("shop_data")
    return None

# --- REFACTORED: Pass game_items_data ---
def _get_item_buy_price(item_id: str, game_items_data: Dict[str, Any]) -> int:
    """Gets the price a shop SELLS an item for (fixed price)."""
    # --- FIX: Use passed game_items_data ---
    item_data = game_items_data.get(item_id)
    if not item_data:
        return 0
    # Shops sell for 2x base value
    return item_data.get("base_value", 0) * 2

# --- REFACTORED: Pass game_items_data ---
def _get_item_sell_price(item_id: str, game_items_data: Dict[str, Any]) -> int:
    """
    Gets the price a shop BUYS an item for.
    Uses value_range if it exists.
    """
    # --- FIX: Use passed game_items_data ---
    item_data = game_items_data.get(item_id)
    if not item_data:
        return 0
        
    base_val = item_data.get("base_value", 0)
    max_val = item_data.get("max_value") # Can be None
    
    # If max_value is defined and greater than base_val, pick a random price
    if max_val and max_val > base_val:
        try:
            return random.randint(base_val, max_val)
        except ValueError:
            return base_val # Fallback if max_val < base_val
        
    # Otherwise, return the fixed base_value
    return base_val

# --- Shop Verbs ---

class List(BaseVerb):
    """
    Handles the 'list' command in a shop.
    Lists all items for sale.
    """
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
        self.player.send_message("Item Name (type 'buy <name>')      Price")
        self.player.send_message("-----------------------------------------")
        
        # --- FIX: Get game_items from self.world ---
        game_items = self.world.game_items
        
        for item_id in inventory:
            # --- FIX: Pass game_items to helper ---
            price = _get_item_buy_price(item_id, game_items)
            item_name = game_items.get(item_id, {}).get("name", "An item")
            self.player.send_message(f"- {item_name:<30} {price} silver")
            
class Buy(BaseVerb):
    """
    Handles the 'buy' command.
    BUY <item name>
    """
    def execute(self):
        shop_data = _get_shop_data(self.room)
        if not shop_data:
            self.player.send_message("You can't seem to shop here.")
            return
            
        if not self.args:
            self.player.send_message("What do you want to buy?")
            return
            
        target_name = " ".join(self.args).lower()
        
        # --- FIX: Get game_items from self.world ---
        game_items = self.world.game_items
        
        # Find the item in the shop's inventory
        item_id_to_buy = None
        for item_id in shop_data.get("inventory", []):
            # --- FIX: Use local game_items ---
            item_data = game_items.get(item_id)
            if item_data:
                if (target_name == item_data.get("name", "").lower() or 
                    target_name in item_data.get("keywords", [])):
                    item_id_to_buy = item_id
                    break
        
        if not item_id_to_buy:
            self.player.send_message("That item is not for sale here.")
            return
            
        # Check price and player silver
        # --- FIX: Pass game_items to helper ---
        price = _get_item_buy_price(item_id_to_buy, game_items)
        player_silver = self.player.wealth.get("silvers", 0)
        
        if player_silver < price:
            self.player.send_message(f"You can't afford that. It costs {price} silver and you have {player_silver}.")
            return
            
        # Perform transaction
        self.player.wealth["silvers"] = player_silver - price
        self.player.inventory.append(item_id_to_buy) # Add to pack
        
        # --- FIX: Use local game_items ---
        item_name = game_items.get(item_id_to_buy, {}).get("name", "the item")
        self.player.send_message(f"You buy {item_name} for {price} silver.")

class Appraise(BaseVerb):
    """
    Handles the 'appraise' command.
    APPRAISE <item name>
    """
    def execute(self):
        shop_data = _get_shop_data(self.room)
        if not shop_data:
            self.player.send_message("You can't seem to shop here.")
            return

        if not self.args:
            self.player.send_message("What do you want to appraise?")
            return

        target_name = " ".join(self.args).lower()
        
        # --- FIX: Get game_items from self.world ---
        game_items = self.world.game_items
        
        # Appraise should work on items in hands OR inventory
        # --- FIX: Pass game_items to helper ---
        item_id, location = _find_item_in_hands(self.player, game_items, target_name)
        if not item_id:
            # --- FIX: Pass game_items to helper ---
            item_id = _find_item_in_inventory(self.player, game_items, target_name)
            
        if not item_id:
            self.player.send_message(f"You don't have a '{target_name}'.")
            return
            
        # Check if the shop will buy this item
        if item_id not in shop_data.get("will_buy", []):
            self.player.send_message("The shopkeep looks at your item and shakes their head, 'I'm not interested in that.'")
            return
            
        # --- FIX: Pass game_items to helper ---
        price = _get_item_sell_price(item_id, game_items)
        
        if price == 0:
            self.player.send_message("The shopkeep tells you, 'That item is worthless.'")
        else:
            self.player.send_message(f"The shopkeep offers you {price} silver for your {target_name}.")

class Sell(BaseVerb):
    """
    Handles the 'sell' command.
    SELL <item name>
    SELL BACKPACK
    """
    def execute(self):
        shop_data = _get_shop_data(self.room)
        if not shop_data:
            self.player.send_message("You can't seem to shop here.")
            return

        if not self.args:
            self.player.send_message("What do you want to sell?")
            return

        target_name = " ".join(self.args).lower()
        
        # --- FIX: Get game_items from self.world ---
        game_items = self.world.game_items
        
        # --- NEW: SELL BACKPACK LOGIC ---
        backpack_keywords = ["backpack", "pack", "back"]
        if target_name in backpack_keywords:
            self.player.send_message("You offer your backpack to the shopkeep to look through...")
            items_to_sell = []
            shop_will_buy_list = shop_data.get("will_buy", [])
            
            for item_id in self.player.inventory[:]:
                if item_id in shop_will_buy_list:
                    items_to_sell.append(item_id)
            
            if not items_to_sell:
                self.player.send_message("The shopkeep finds nothing of interest in your pack.")
                return
                
            total_silver = 0
            for item_id in items_to_sell:
                # --- FIX: Pass game_items to helper ---
                price = _get_item_sell_price(item_id, game_items)
                if price > 0:
                    self.player.inventory.remove(item_id)
                    total_silver += price
                    # --- FIX: Use local game_items ---
                    item_name = game_items.get(item_id, {}).get("name", "an item")
                    self.player.send_message(f"You sell {item_name} for {price} silver.")
            
            if total_silver > 0:
                self.player.wealth["silvers"] = self.player.wealth.get("silvers", 0) + total_silver
                self.player.send_message(f"You earned a total of {total_silver} silver.")
            else:
                self.player.send_message("The shopkeep finds nothing of value in your pack.")
            return
        # --- END: SELL BACKPACK LOGIC ---

        # --- DEFAULT: SELL <item> (must be in hands) ---
        # --- FIX: Pass game_items to helper ---
        item_id, item_location = _find_item_in_hands(self.player, game_items, target_name)

        if not item_id:
            self.player.send_message(f"You are not holding a '{target_name}' to sell.")
            return
            
        # Check if the shop will buy this item
        if item_id not in shop_data.get("will_buy", []):
            self.player.send_message("The shopkeep isn't interested in that item.")
            return
            
        # --- FIX: Pass game_items to helper ---
        price = _get_item_sell_price(item_id, game_items)
        
        if price == 0:
            self.player.send_message("That item is worthless.")
            return
            
        # Perform Transaction
        self.player.worn_items[item_location] = None # Remove from hand
        self.player.wealth["silvers"] = self.player.wealth.get("silvers", 0) + price
        # --- FIX: Use local game_items ---
        item_name = game_items.get(item_id, {}).get("name", "the item")
        self.player.send_message(f"You sell {item_name} for {price} silver.")