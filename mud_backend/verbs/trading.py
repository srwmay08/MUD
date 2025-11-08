# mud_backend/verbs/trading.py
import time
import re
from mud_backend.verbs.base_verb import BaseVerb
# --- REFACTORED: Removed game_state and get_player_object imports ---
from typing import Dict, Any, Tuple, Optional
# --- NEW: Import config for DEBUG_MODE ---
from mud_backend import config

# --- NEW: Helper functions copied from equipment.py ---
def _find_item_in_inventory(player, target_name: str) -> str | None:
    """Finds the first item_id in a player's inventory that matches."""
    for item_id in player.inventory:
        # --- FIX: Use player.world.game_items ---
        item_data = player.world.game_items.get(item_id)
        if item_data:
            if (target_name == item_data.get("name", "").lower() or 
                target_name in item_data.get("keywords", [])):
                return item_id
    return None

def _find_item_in_hands(player, target_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Finds the first item_id in a player's hands that matches.
    Returns (item_id, slot_name) or (None, None)
    """
    for slot in ["mainhand", "offhand"]:
        item_id = player.worn_items.get(slot)
        if item_id:
            # --- FIX: Use player.world.game_items ---
            item_data = player.world.game_items.get(item_id)
            if item_data:
                if (target_name == item_data.get("name", "").lower() or 
                    target_name in item_data.get("keywords", [])):
                    return item_id, slot
    return None, None
# --- END HELPERS ---


class Give(BaseVerb):
    """
    Handles the 'give' command.
    GIVE <player> <item> (Prompts for ACCEPT)
    GIVE <player> <amount> (Transfers silver immediately)
    """
    def execute(self):
        if len(self.args) < 2:
            self.player.send_message("Usage: GIVE <player> <item> OR GIVE <player> <amount>")
            return
            
        target_player_name = self.args[0].lower()
        
        # 1. Check if target player is real and in the same room
        target_player = self.world.get_player_obj(target_player_name)
        if not target_player or target_player.current_room_id != self.player.current_room_id:
            self.player.send_message(f"You don't see anyone named '{self.args[0]}' here.")
            return
            
        if target_player.name.lower() == self.player.name.lower():
            self.player.send_message("You can't give things to yourself.")
            return

        trade_offer = {
            "from_player_name": self.player.name,
            "offer_time": time.time()
        }
        
        silver_amount = 0
        target_item_name = " ".join(self.args[1:]).lower()

        # --- BRANCH 1: Giving Silver ---
        if len(self.args) == 2:
            try:
                silver_amount = int(self.args[1])
                if silver_amount <= 0:
                    raise ValueError("Must be positive")
            except ValueError:
                silver_amount = 0 # It's not silver, so treat as an item name
        
        if silver_amount > 0:
            # --- MODIFIED: Silver transfers are IMMEDIATE ---
            player_silver = self.player.wealth.get("silvers", 0)
            if player_silver < silver_amount:
                self.player.send_message(f"You don't have {silver_amount} silver to give.")
                return
            
            # Perform immediate transfer
            self.player.wealth["silvers"] = player_silver - silver_amount
            target_player.wealth["silvers"] = target_player.wealth.get("silvers", 0) + silver_amount
            
            # Send messages to both parties
            self.player.send_message(f"You give {silver_amount} silver to {target_player.name}.")
            # --- THIS IS THE FIX ---
            self.world.send_message_to_player(target_player.name.lower(), f"{self.player.name} gives you {silver_amount} silver.")
            # --- END FIX ---
            
            # --- NEW: Add DEBUG log ---
            if config.DEBUG_MODE:
                print(f"[TRADE DEBUG] {self.player.name} gave {silver_amount} silver to {target_player.name} (Immediate).")
            
            return # We are done.
            # --- END MODIFICATION ---

        # --- BRANCH 2: Giving an Item ---
        else:
            # --- Check for pending trade (MOVED HERE) ---
            if self.world.get_pending_trade(target_player.name.lower()):
                self.player.send_message(f"{target_player.name} already has a pending offer. Please wait.")
                return
            # --- END MOVE ---

            item_id_to_give = None
            item_source_location = None # e.g., "inventory", "mainhand"
            
            # Check hands first
            item_id_hand, hand_slot = _find_item_in_hands(self.player, target_item_name)
            if item_id_hand:
                item_id_to_give = item_id_hand
                item_source_location = hand_slot
            else:
                # Check inventory
                item_id_inv = _find_item_in_inventory(self.player, target_item_name)
                if item_id_inv:
                    item_id_to_give = item_id_inv
                    item_source_location = "inventory"
            
            if not item_id_to_give:
                self.player.send_message(f"You don't have a '{target_item_name}' in your pack or hands.")
                return
                
            item_data = self.world.game_items.get(item_id_to_give)
            
            trade_offer.update({
                "trade_type": "item",
                "item_id": item_id_to_give,
                "item_name": item_data['name'],
                "item_source_location": item_source_location, # Track where it came from
            })
            
            self.player.send_message(f"You offer {item_data['name']} to {target_player.name}.")

        # 4. Create the pending trade and notify the target player (ITEM ONLY)
        self.world.set_pending_trade(target_player.name.lower(), trade_offer)
        
        # --- NEW: Add DEBUG log ---
        if config.DEBUG_MODE:
            print(f"[TRADE DEBUG] {self.player.name} offered {trade_offer['item_name']} to {target_player.name}. Waiting for ACCEPT.")

        # --- THIS IS THE FIX ---
        self.world.send_message_to_player(
            target_player.name.lower(),
            f"{self.player.name} offers you {trade_offer['item_name']}. "
            f"Type '<span class='keyword' data-command='accept'>ACCEPT</span>' or "
            f"'<span class='keyword' data-command='decline'>DECLINE</span>'.\n"
            f"The offer will expire in 30 seconds."
        )
        # --- END FIX ---


class Accept(BaseVerb):
    """
    Handles the 'accept' command for trades and exchanges.
    """
    def execute(self):
        player_key = self.player.name.lower()
        
        # 1. Check for a pending trade
        trade_offer = self.world.get_pending_trade(player_key)
        
        if not trade_offer:
            self.player.send_message("You have not been offered anything.")
            return
            
        # 2. Check if the giver is still here
        giver_player = self.world.get_player_obj(trade_offer['from_player_name'].lower())
        if not giver_player or giver_player.current_room_id != self.player.current_room_id:
            self.player.send_message(f"{trade_offer['from_player_name']} is no longer here.")
            self.world.remove_pending_trade(player_key) # Clear the expired trade
            return
            
        trade_type = trade_offer.get("trade_type", "item")
        item_name = trade_offer.get("item_name", "the item")

        # --- BRANCH 1: Accepting a simple 'GIVE' (item) ---
        if trade_type == "item": # <-- MODIFIED (removed "or trade_type == 'silver'")
            
            # 4. Check if the giver still has the item
            item_id = trade_offer['item_id']
            item_source = trade_offer['item_source_location']
            item_is_present = False
            if item_source == "inventory":
                if item_id in giver_player.inventory:
                    item_is_present = True
            elif item_source in ["mainhand", "offhand"]:
                if giver_player.worn_items.get(item_source) == item_id:
                    item_is_present = True
            
            if not item_is_present:
                self.player.send_message(f"{giver_player.name} no longer has {item_name}.")
                self.world.remove_pending_trade(player_key)
                return
                
            # 5. Success! Transfer the item.
            if item_source == "inventory":
                giver_player.inventory.remove(item_id)
            else: # Was in a hand
                giver_player.worn_items[item_source] = None
            
            # --- NEW LOGIC: Place in hands, then pack ---
            right_hand_slot = "mainhand"
            left_hand_slot = "offhand"
            
            # --- THIS IS THE FIX ---
            giver_player_name_lower = giver_player.name.lower()
            # --- END FIX ---

            if self.player.worn_items.get(right_hand_slot) is None:
                self.player.worn_items[right_hand_slot] = item_id
                self.player.send_message(f"You accept {item_name} from {giver_player.name} and hold it in your right hand.")
                # --- THIS IS THE FIX ---
                self.world.send_message_to_player(giver_player_name_lower, f"{self.player.name} accepts your offer for {item_name}.")
            elif self.player.worn_items.get(left_hand_slot) is None:
                self.player.worn_items[left_hand_slot] = item_id
                self.player.send_message(f"You accept {item_name} from {giver_player.name} and hold it in your left hand.")
                # --- THIS IS THE FIX ---
                self.world.send_message_to_player(giver_player_name_lower, f"{self.player.name} accepts your offer for {item_name}.")
            else:
                # Both hands are full, goes to pack
                self.player.inventory.append(item_id)
                self.player.send_message(f"You accept {item_name} from {giver_player.name}. Your hands are full, so you place it in your pack.")
                # --- THIS IS THE FIX ---
                self.world.send_message_to_player(giver_player_name_lower, f"{self.player.name} accepts your offer for {item_name}.")
            # --- END NEW LOGIC ---

            # --- NEW: Add DEBUG log ---
            if config.DEBUG_MODE:
                print(f"[TRADE DEBUG] {self.player.name} ACCEPTED item {item_name} from {giver_player.name}.")

            # 6. Send confirmations and clear trade
            self.world.remove_pending_trade(player_key)

        # --- DELETED: Silver-only branch ---

        # --- BRANCH 2: Accepting an 'EXCHANGE' ---
        elif trade_type == "exchange":
            item_id = trade_offer['item_id']
            item_source = trade_offer['item_source_location']
            silver_amount = trade_offer['silver_amount']
            
            # 4. Check if buyer (self) has enough silver
            if self.player.wealth.get("silvers", 0) < silver_amount:
                self.player.send_message(f"You cannot afford this. You need {silver_amount} silver.")
                # Note: We don't cancel the trade here, they can try again.
                return

            # 5. Check if seller (giver) still has the item
            item_is_present = False
            if item_source == "inventory":
                if item_id in giver_player.inventory:
                    item_is_present = True
            elif item_source in ["mainhand", "offhand"]:
                if giver_player.worn_items.get(item_source) == item_id:
                    item_is_present = True
            
            if not item_is_present:
                self.player.send_message(f"{giver_player.name} no longer has {item_name}.")
                self.world.remove_pending_trade(player_key)
                return
            
            # 6. Success! Perform the exchange.
            # A. Silver transfer
            self.player.wealth["silvers"] = self.player.wealth.get("silvers", 0) - silver_amount
            giver_player.wealth["silvers"] = giver_player.wealth.get("silvers", 0) + silver_amount
            
            # B. Item transfer (from giver)
            if item_source == "inventory":
                giver_player.inventory.remove(item_id)
            else: # Was in a hand
                giver_player.worn_items[item_source] = None
            
            # C. Item placement (to buyer)
            # --- NEW LOGIC: Place in hands, then pack ---
            right_hand_slot = "mainhand"
            left_hand_slot = "offhand"
            
            item_received_msg = ""
            if self.player.worn_items.get(right_hand_slot) is None:
                self.player.worn_items[right_hand_slot] = item_id
                item_received_msg = f"You accept {giver_player.name}'s offer and hold {item_name} in your right hand."
            elif self.player.worn_items.get(left_hand_slot) is None:
                self.player.worn_items[left_hand_slot] = item_id
                item_received_msg = f"You accept {giver_player.name}'s offer and hold {item_name} in your left hand."
            else:
                self.player.inventory.append(item_id)
                item_received_msg = f"You accept {giver_player.name}'s offer for {item_name}. Your hands are full, so you place it in your pack."
            # --- END NEW LOGIC ---
            
            # 7. Send confirmations and clear trade
            self.player.send_message(f"You hand {giver_player.name} {silver_amount} silver.\n"
                                     f"{item_received_msg}")
            
            # --- THIS IS THE FIX ---
            self.world.send_message_to_player(
                giver_player.name.lower(),
                f"{self.player.name} hands you {silver_amount} silver.\n"
                f"{self.player.name} has accepted your offer."
            )
            # --- END FIX ---
            
            # --- NEW: Add DEBUG log ---
            if config.DEBUG_MODE:
                print(f"[TRADE DEBUG] {self.player.name} ACCEPTED exchange with {giver_player.name} (Item: {item_name}, Silver: {silver_amount}).")
            
            self.world.remove_pending_trade(player_key)

class Decline(BaseVerb):
    """
    Handles the 'decline' command for trades.
    """
    def execute(self):
        player_key = self.player.name.lower()
        
        # 1. Check for a pending trade TO this player
        trade_offer = self.world.remove_pending_trade(player_key)
        
        if not trade_offer:
            self.player.send_message("You have no offers to decline.")
            return
            
        # --- NEW: Add DEBUG log ---
        if config.DEBUG_MODE:
            item_name = trade_offer.get("item_name", "offer")
            from_name = trade_offer.get("from_player_name", "Unknown")
            print(f"[TRADE DEBUG] {self.player.name} DECLINED offer of {item_name} from {from_name}.")

        # 2. Notify players (standard decline)
        self.player.send_message(f"You decline the offer from {trade_offer['from_player_name']}.")
        
        # --- THIS IS THE FIX ---
        # Notify the giver, even if they are offline or in another room (so they don't see "offer pending")
        giver_player_name_lower = trade_offer['from_player_name'].lower()
        self.world.send_message_to_player(giver_player_name_lower, f"{self.player.name} declines your offer.")
        # --- END FIX ---

# --- NEW: Cancel verb ---
class Cancel(BaseVerb):
    """
    Handles the 'cancel' command to retract an offer.
    """
    def execute(self):
        giver_key = self.player.name.lower()
        offer_to_cancel = None
        receiver_name = None
        
        # Find an offer WHERE from_player_name is me
        with self.world.trade_lock:
            for r_name, offer in self.world.pending_trades.items():
                if offer.get("from_player_name", "").lower() == giver_key:
                    offer_to_cancel = offer
                    receiver_name = r_name
                    break
        
        if offer_to_cancel and receiver_name:
            # Found our outgoing offer, remove it
            self.world.remove_pending_trade(receiver_name)
            self.player.send_message(f"You cancel your offer to {receiver_name}.")
            
            # --- THIS IS THE FIX ---
            # Notify the person who *would* have received it
            self.world.send_message_to_player(receiver_name, f"{self.player.name} cancels their offer.")
            # --- END FIX ---
            
            if config.DEBUG_MODE:
                item_name = offer_to_cancel.get("item_name", "offer")
                print(f"[TRADE DEBUG] {self.player.name} CANCELLED offer of {item_name} to {receiver_name}.")
        else:
            self.player.send_message("You have no active offers to cancel.")


# --- NEW VERB: EXCHANGE ---
class Exchange(BaseVerb):
    """
    Handles the 'exchange' command.
    EXCHANGE {item} WITH {player} FOR {silvers} SILVER
    """
    def execute(self):
        args_str = " ".join(self.args).lower()
        
        # 1. Parse the command
        if " with " not in args_str or " for " not in args_str:
            self.player.send_message("Usage: EXCHANGE {item} WITH {player} FOR {silvers} SILVER")
            return

        try:
            parts1 = args_str.split(" with ", 1)
            target_item_name = parts1[0].strip()
            
            parts2 = parts1[1].split(" for ", 1)
            target_player_name = parts2[0].strip()
            
            parts3 = parts2[1].split(" silver", 1)
            silver_amount_str = parts3[0].strip()
            silver_amount = int(silver_amount_str)
            
            if silver_amount <= 0:
                raise ValueError("Silver must be positive")
                
        except Exception:
            self.player.send_message("Usage: EXCHANGE {item} WITH {player} FOR {silvers} SILVER")
            return

        # 2. Find target player
        target_player = self.world.get_player_obj(target_player_name)
        if not target_player or target_player.current_room_id != self.player.current_room_id:
            self.player.send_message(f"You don't see anyone named '{target_player_name}' here.")
            return
            
        if target_player.name.lower() == self.player.name.lower():
            self.player.send_message("You can't exchange things with yourself.")
            return
            
        # 3. Check for existing pending trade
        if self.world.get_pending_trade(target_player.name.lower()):
            self.player.send_message(f"{target_player.name} already has a pending offer. Please wait.")
            return

        # 4. Find the item (hands or inventory)
        item_id_to_give = None
        item_source_location = None
        
        if target_item_name == "left":
            item_id_to_give = self.player.worn_items.get("offhand")
            item_source_location = "offhand"
        elif target_item_name == "right":
            item_id_to_give = self.player.worn_items.get("mainhand")
            item_source_location = "mainhand"
        
        if not item_id_to_give:
            item_id_hand, hand_slot = _find_item_in_hands(self.player, target_item_name)
            if item_id_hand:
                item_id_to_give = item_id_hand
                item_source_location = hand_slot
            else:
                item_id_inv = _find_item_in_inventory(self.player, target_item_name)
                if item_id_inv:
                    item_id_to_give = item_id_inv
                    item_source_location = "inventory"
        
        if not item_id_to_give:
            self.player.send_message(f"You don't have a '{target_item_name}' in your pack or hands.")
            return
            
        item_data = self.world.game_items.get(item_id_to_give)
        item_name = item_data.get('name', 'an item')
        
        # 5. Create the pending trade offer
        trade_offer = {
            "from_player_name": self.player.name,
            "offer_time": time.time(),
            "trade_type": "exchange",
            "item_id": item_id_to_give,
            "item_name": item_name,
            "item_source_location": item_source_location,
            "silver_amount": silver_amount
        }
        
        self.world.set_pending_trade(target_player.name.lower(), trade_offer)

        # --- NEW: Add DEBUG log ---
        if config.DEBUG_MODE:
            print(f"[TRADE DEBUG] {self.player.name} offered {item_name} to {target_player.name} for {silver_amount} silver. Waiting for ACCEPT.")

        # 6. Send notifications
        # To Seller (self)
        self.player.send_message(
            f"You offer your {item_name} to {target_player.name} for {silver_amount} silvers. "
            f"She has 30 seconds to accept the offer. "
            f"Type '<span class='keyword' data-command='cancel'>CANCEL</span>' to prematurely cancel the offer."
        )
        
        # --- THIS IS THE FIX ---
        # To Buyer (target)
        self.world.send_message_to_player(
            target_player.name.lower(),
            f"{self.player.name} offers you {self.player.name}'s {item_name} for {silver_amount} silvers. "
            f"Type '<span class='keyword' data-command='accept'>ACCEPT</span>' to pay the silvers and accept the offer or "
            f"'<span class='keyword' data-command='decline'>DECLINE</span>' to decline it. "
            f"The offer will expire in 30 seconds."
        )
        # --- END FIX ---