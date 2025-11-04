# mud_backend/verbs/shop.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core import game_state
from mud_backend.core import db
import math
import random # <-- MAKE SURE THIS IMPORT IS HERE

# --- Helper Functions (copied from item_actions.py) ---

def _find_item_in_inventory(player, target_name: str) -> str | None:
    """Finds the first item_id in a player's inventory that matches."""
    for item_id in player.inventory:
        item_data = game_state.GAME_ITEMS.get(item_id)
        if item_data:
            if (target_name == item_data.get("name", "").lower() or 
                target_name in item_data.get("keywords", [])):
                return item_id
    # Check hands too
    for slot in ["mainhand", "offhand"]:
        item_id = player.worn_items.get(slot)
        if item_id:
            item_data = game_state.GAME_ITEMS.get(item_id)
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

# --- MODIFIED HELPER ---
def _get_item_buy_price(item_id: str) -> int:
    """Gets the price a shop SELLS an item for (fixed price)."""
    item_data = game_state.GAME_ITEMS.get(item_id)
    if not item_data:
        return 0
    # Shops sell for 2x base value
    return item_data.get("base_value", 0) * 2

# --- NEW HELPER ---
def _get_item_sell_price(item_id: str) -> int:
    """
    Gets the price a shop BUYS an item for.
    Uses value_range if it exists.
    """
    item_data = game_state.GAME_ITEMS.get(item_id)
    if not item_data:
        return 0
        
    base_val = item_data.get("base_value", 0)
    max_val = item_data.get("max_value") # Can be None
    
    # If max_value is defined and greater than base_value, pick a random price
    if max_val and max_val > base_val:
        return random.randint(base_val, max_val)
        
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
            # --- FIX: Check if this is the training room ---
            if self.player.game_state == "training":
                self.player.send_message("You must 'check in' at the inn to train.")
                return
            # --- END FIX ---
            self.player.send_message("You can't seem to shop here.")
            return
            
        inventory = shop_data.get("inventory", [])
        if not inventory:
            self.player.send_message("The shop has nothing for sale right now.")
            return

        self.player.send_message("--- Items for Sale ---")
        self.player.send_message("Item Name (type 'buy <name>')      Price")
        self.player.send_message("-----------------------------------------")
        
        for item_id in inventory:
            # --- USE NEW HELPER ---
            price = _get_item_buy_price(item_id)
            item_name = game_state.GAME_ITEMS.get(item_id, {}).get("name", "An item")
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
        
        # Find the item in the shop's inventory
        item_id_to_buy = None
        for item_id in shop_data.get("inventory", []):
            item_data = game_state.GAME_ITEMS.get(item_id)
            if item_data:
                if (target_name == item_data.get("name", "").lower() or 
                    target_name in item_data.get("keywords", [])):
                    item_id_to_buy = item_id
                    break
        
        if not item_id_to_buy:
            self.player.send_message("That item is not for sale here.")
            return
            
        # Check price and player silver
        # --- USE NEW HELPER ---
        price = _get_item_buy_price(item_id_to_buy)
        player_silver = self.player.wealth.get("silvers", 0)
        
        if player_silver < price:
            self.player.send_message(f"You can't afford that. It costs {price} silver and you have {player_silver}.")
            return
            
        # Perform transaction
        self.player.wealth["silvers"] = player_silver - price
        self.player.inventory.append(item_id_to_buy) # Add to pack
        
        item_name = game_state.GAME_ITEMS.get(item_id_to_buy, {}).get("name", "the item")
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
        item_id = _find_item_in_inventory(self.player, target_name)

        if not item_id:
            self.player.send_message(f"You don't have a '{target_name}'.")
            return
            
        # Check if the shop will buy this item
        if item_id not in shop_data.get("will_buy", []):
            self.player.send_message("The shopkeep looks at your item and shakes their head, 'I'm not interested in that.'")
            return
            
        # --- USE NEW HELPER ---
        price = _get_item_sell_price(item_id)
        
        if price == 0:
            self.player.send_message("The shopkeep tells you, 'That item is worthless.'")
        else:
            self.player.send_message(f"The shopkeep offers you {price} silver for your {target_name}.")

class Sell(BaseVerb):
    """
    Handles the 'sell' command.
    SELL <item name>
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
        item_id = _find_item_in_inventory(self.player, target_name)

        if not item_id:
            self.player.send_message(f"You don't have a '{target_name}'.")
            return
            
        # Check if the shop will buy this item
        if item_id not in shop_data.get("will_buy", []):
            self.player.send_message("The shopkeep isn't interested in that item.")
            return
            
        # --- USE NEW HELPER ---
        price = _get_item_sell_price(item_id)
        
        if price == 0:
            self.player.send_message("That item is worthless.")
            return
            
        # Perform Transaction - find where the item is and remove it
        item_location = None
        if item_id in self.player.inventory:
            item_location = "inventory"
        else:
            for slot in ["mainhand", "offhand"]:
                if self.player.worn_items.get(slot) == item_id:
                    item_location = slot
                    break
        
        if item_location == "inventory":
            self.player.inventory.remove(item_id)
        elif item_location:
            self.player.worn_items[item_location] = None
        else:
            self.player.send_message("An error occurred. You seem to have lost the item.")
            return
            
        self.player.wealth["silvers"] = self.player.wealth.get("silvers", 0) + price
        item_name = game_state.GAME_ITEMS.get(item_id, {}).get("name", "the item")
        self.player.send_message(f"You sell {item_name} for {price} silver.")