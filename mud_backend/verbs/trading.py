# mud_backend/verbs/trading.py
import time
from mud_backend.verbs.base_verb import BaseVerb
# --- REFACTORED: Removed game_state and get_player_object imports ---

class Give(BaseVerb):
    """
    Handles the 'give' command.
    GIVE <player> <item>
    """
    def execute(self):
        if len(self.args) < 2:
            self.player.send_message("Usage: GIVE <player> <item>")
            return
            
        target_player_name = self.args[0].lower()
        target_item_name = " ".join(self.args[1:]).lower()
        
        # 1. Check if target player is real and in the same room
        # --- FIX: Use self.world to get player object ---
        target_player = self.world.get_player_obj(target_player_name)
        if not target_player or target_player.current_room_id != self.player.current_room_id:
            self.player.send_message(f"You don't see anyone named '{self.args[0]}' here.")
            return
            
        if target_player.name.lower() == self.player.name.lower():
            self.player.send_message("You can't give things to yourself.")
            return

        # 2. Find the item in the giver's inventory
        item_id_to_give = None
        for item_id in self.player.inventory:
            # --- FIX: Use self.world.game_items ---
            item_data = self.world.game_items.get(item_id)
            if item_data and (target_item_name == item_data['name'].lower() or target_item_name in item_data.get("keywords", [])):
                item_id_to_give = item_id
                break
        
        if not item_id_to_give:
            self.player.send_message(f"You don't have a '{target_item_name}' in your pack.")
            return
            
        # --- FIX: Use self.world.game_items ---
        item_data = self.world.game_items.get(item_id_to_give)

        # 3. Create a pending trade offer
        trade_offer = {
            "from_player_name": self.player.name,
            "item_id": item_id_to_give,
            "item_name": item_data['name'],
            "offer_time": time.time()
        }
        
        # --- FIX: Use self.world to set trade ---
        self.world.set_pending_trade(target_player.name.lower(), trade_offer)
        
        self.player.send_message(f"You offer {item_data['name']} to {target_player.name}.")
        
        # 4. Notify the target player
        target_player.send_message(f"{self.player.name} offers you {item_data['name']}.")
        target_player.send_message("Type 'ACCEPT' to take it or 'DECLINE' to refuse.")
        

class Accept(BaseVerb):
    """
    Handles the 'accept' command for trades.
    """
    def execute(self):
        player_key = self.player.name.lower()
        
        # 1. Check for a pending trade
        # --- FIX: Use self.world ---
        trade_offer = self.world.get_pending_trade(player_key)
        
        if not trade_offer:
            self.player.send_message("You have not been offered anything.")
            return
            
        # 2. Check if the offer is still valid (e.g., 30 seconds)
        if time.time() - trade_offer['offer_time'] > 30:
            self.player.send_message("The offer has expired.")
            # --- FIX: Use self.world ---
            self.world.remove_pending_trade(player_key)
            return
            
        # 3. Check if the giver is still here
        # --- FIX: Use self.world ---
        giver_player = self.world.get_player_obj(trade_offer['from_player_name'].lower())
        if not giver_player or giver_player.current_room_id != self.player.current_room_id:
            self.player.send_message(f"{trade_offer['from_player_name']} is no longer here.")
            # --- FIX: Use self.world ---
            self.world.remove_pending_trade(player_key)
            return
            
        # 4. Check if the giver still has the item
        item_id = trade_offer['item_id']
        if item_id not in giver_player.inventory:
            self.player.send_message(f"{giver_player.name} no longer has {trade_offer['item_name']}.")
            # --- FIX: Use self.world ---
            self.world.remove_pending_trade(player_key)
            return
            
        # 5. Success! Transfer the item.
        giver_player.inventory.remove(item_id)
        self.player.inventory.append(item_id)
        
        self.player.send_message(f"You accept {trade_offer['item_name']} from {giver_player.name}.")
        giver_player.send_message(f"{self.player.name} accepts your offer.")
        
        # 6. Clear the trade
        # --- FIX: Use self.world ---
        self.world.remove_pending_trade(player_key)

class Decline(BaseVerb):
    """
    Handles the 'decline' or 'cancel' command for trades.
    """
    def execute(self):
        player_key = self.player.name.lower()
        
        # 1. Check for a pending trade
        # --- FIX: Use self.world ---
        trade_offer = self.world.remove_pending_trade(player_key)
        
        if not trade_offer:
            self.player.send_message("You have no offers to decline.")
            return
            
        # 2. Notify players
        self.player.send_message(f"You decline the offer from {trade_offer['from_player_name']}.")
        
        # --- FIX: Use self.world ---
        giver_player = self.world.get_player_obj(trade_offer['from_player_name'].lower())
        if giver_player:
            giver_player.send_message(f"{self.player.name} declines your offer.")

# Alias 'Cancel' to 'Decline'
class Cancel(Decline):
    pass