# mud_backend/verbs/trading.py
import time
from mud_backend.verbs.base_verb import BaseVerb
from typing import Dict, Any, Tuple, Optional
from mud_backend.core.utils import check_action_roundtime, set_action_roundtime
from mud_backend.core.registry import VerbRegistry
from mud_backend.core.item_utils import find_item_in_inventory, find_item_in_hands

def _count_item_in_inventory(player, target_item_id: str) -> int:
    count = 0
    for item_id in player.inventory:
        if item_id == target_item_id:
            count += 1
    return count

def _find_npc_in_room(room, target_name: str) -> Optional[Dict[str, Any]]:
    for obj in room.objects:
        if obj.get("quest_giver_ids") or obj.get("is_npc"):
            if (target_name == obj.get("name", "").lower() or 
                target_name in obj.get("keywords", [])):
                return obj
    return None

@VerbRegistry.register(["give"]) 
class Give(BaseVerb):
    def execute(self):
        if check_action_roundtime(self.player, action_type="other"):
            return
        
        if len(self.args) < 2:
            self.player.send_message("Usage: GIVE <target> <item> OR GIVE <player> <amount>")
            return
            
        target_name_input = self.args[0].lower()
        
        silver_amount = 0
        target_item_name = ""

        if len(self.args) == 2:
            try:
                silver_amount = int(self.args[1])
                if silver_amount <= 0:
                    raise ValueError("Must be positive")
            except ValueError:
                silver_amount = 0 
        
        if silver_amount == 0:
            target_item_name = " ".join(self.args[1:]).lower()

        # --- ALMS GIVING LOGIC ---
        if silver_amount > 0:
            target_npc = _find_npc_in_room(self.room, target_name_input)
            if target_npc and "beggar" in target_npc.get("keywords", []):
                if self.player.wealth.get("silvers", 0) >= silver_amount:
                    self.player.wealth["silvers"] -= silver_amount
                    self.player.send_message(f"You give {silver_amount} silver to the beggar.")
                    self.player.send_message("The beggar bows their head. 'Bless you, child of light.'")
                    
                    self.player.quest_counters["alms_given"] = self.player.quest_counters.get("alms_given", 0) + silver_amount
                    set_action_roundtime(self.player, 1.0)
                    return
                else:
                    self.player.send_message("You don't have that much silver.")
                    return
        # -------------------------

        if silver_amount == 0 and target_item_name:
            target_npc = _find_npc_in_room(self.room, target_name_input)
            if target_npc:
                npc_name = target_npc.get("name", "the NPC")
                
                # Use Core functions
                item_id_to_give, item_source_location = find_item_in_hands(self.player, self.world.game_items, target_item_name)
                if not item_id_to_give:
                    item_id_to_give = find_item_in_inventory(self.player, self.world.game_items, target_item_name)
                    if item_id_to_give:
                        item_source_location = "inventory"
                
                if not item_id_to_give:
                    self.player.send_message(f"You don't have a '{target_item_name}' in your pack or hands.")
                    return
                
                item_data = self.world.game_items.get(item_id_to_give, {}) if isinstance(item_id_to_give, str) else item_id_to_give
                item_name = item_data.get("name", "that item")

                active_quest = None
                quest_id_for_item = None
                
                for quest_id, quest_data in self.world.game_quests.items():
                    if quest_data.get("item_needed") == item_id_to_give:
                        if quest_data.get("give_target_name") == npc_name.lower():
                            is_done = False
                            if quest_id in self.player.completed_quests:
                                is_done = True
                            if is_done: continue
                                
                            prereq_quest = quest_data.get("prereq_quest")
                            if prereq_quest and prereq_quest not in self.player.completed_quests:
                                continue
                                
                            active_quest = quest_data
                            quest_id_for_item = quest_id
                            break
                
                if not active_quest:
                    self.player.send_message(f"The {npc_name} does not seem interested in {item_name}.")
                    return

                item_needed = active_quest.get("item_needed")
                if item_id_to_give == item_needed:
                    quantity_needed = active_quest.get("item_quantity", 1)
                    
                    if quantity_needed == 1:
                        if item_source_location == "inventory":
                            self.player.inventory.remove(item_id_to_give)
                        else:
                            self.player.worn_items[item_source_location] = None
                    else:
                        item_count = _count_item_in_inventory(self.player, item_id_to_give)
                        if item_source_location in ["mainhand", "offhand"]:
                            item_count += 1
                            
                        if item_count < quantity_needed:
                            self.player.send_message(f"The {npc_name} looks at your {item_name}. \"This is a good start, but I need {quantity_needed} of them. You only have {item_count}.\"")
                            return
                        
                        items_removed = 0
                        if item_source_location in ["mainhand", "offhand"]:
                            self.player.worn_items[item_source_location] = None
                            items_removed += 1
                        
                        for _ in range(quantity_needed - items_removed):
                            if item_id_to_give in self.player.inventory:
                                self.player.inventory.remove(item_id_to_give)
                            else:
                                break
                    
                    quest_id = quest_id_for_item
                    reward_message = active_quest.get("reward_message", "You have completed the task!")
                    self.player.send_message(reward_message)
                    
                    reward_xp = active_quest.get("reward_xp", 0)
                    if reward_xp > 0:
                        self.player.grant_experience(reward_xp, source="quest")
                        
                    reward_silver = active_quest.get("reward_silver", 0)
                    if reward_silver > 0:
                        self.player.wealth["silvers"] = self.player.wealth.get("silvers", 0) + reward_silver
                        self.player.send_message(f"You have been given {reward_silver} silver!")

                    reward_item = active_quest.get("reward_item")
                    if reward_item:
                        self.player.inventory.append(reward_item)
                        r_item_data = self.world.game_items.get(reward_item, {})
                        self.player.send_message(f"You are given {r_item_data.get('name', 'an item')}.")
                    
                    reward_spell = active_quest.get("reward_spell")
                    if reward_spell:
                        if reward_spell not in self.player.known_spells:
                            self.player.known_spells.append(reward_spell)
                        else:
                            self.player.send_message(active_quest.get("already_learned_message", "You have already completed this task."))
                    
                    self.player.completed_quests.append(quest_id)
                    set_action_roundtime(self.player, 1.0) 
                    return 
                else:
                    self.player.send_message(f"The {npc_name} does not seem interested in that.")
                    return

        target_player = self.world.get_player_obj(target_name_input)
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
        
        if silver_amount > 0:
            player_silver = self.player.wealth.get("silvers", 0)
            if player_silver < silver_amount:
                self.player.send_message(f"You don't have {silver_amount} silver to give.")
                return
            
            self.player.wealth["silvers"] = player_silver - silver_amount
            target_player.wealth["silvers"] = target_player.wealth.get("silvers", 0) + silver_amount
            
            self.player.send_message(f"You give {silver_amount} silver to {target_player.name}.")
            self.world.send_message_to_player(target_player.name.lower(), f"{self.player.name} gives you {silver_amount} silver.")
            
            set_action_roundtime(self.player, 1.0) 
            return 

        else:
            if self.world.get_pending_trade(target_player.name.lower()):
                self.player.send_message(f"{target_player.name} already has a pending offer. Please wait.")
                return

            item_id_to_give = None
            item_source_location = None 
            
            # Use Core
            item_id_hand, hand_slot = find_item_in_hands(self.player, self.world.game_items, target_item_name)
            if item_id_hand:
                item_id_to_give = item_id_hand
                item_source_location = hand_slot
            else:
                item_id_inv = find_item_in_inventory(self.player, self.world.game_items, target_item_name)
                if item_id_inv:
                    item_id_to_give = item_id_inv
                    item_source_location = "inventory"
            
            if not item_id_to_give:
                self.player.send_message(f"You don't have a '{target_item_name}' in your pack or hands.")
                return
            
            # Handle Item Ref vs ID
            item_data = self.world.game_items.get(item_id_to_give) if isinstance(item_id_to_give, str) else item_id_to_give
            
            trade_offer.update({
                "trade_type": "item",
                "item_id": item_id_to_give,
                "item_name": item_data['name'],
                "item_source_location": item_source_location, 
            })
            
            self.player.send_message(f"You offer {item_data['name']} to {target_player.name}.")

        self.world.set_pending_trade(target_player.name.lower(), trade_offer)
        
        self.world.send_message_to_player(
            target_player.name.lower(),
            f"{self.player.name} offers you {trade_offer['item_name']}. "
            f"Type '<span class='keyword' data-command='accept'>ACCEPT</span>' or "
            f"'<span class='keyword' data-command='decline'>DECLINE</span>'.\n"
            f"The offer will expire in 30 seconds."
        )
        set_action_roundtime(self.player, 1.0) 


@VerbRegistry.register(["accept"]) 
class Accept(BaseVerb):
    """Handles the 'accept' command for trades and exchanges."""
    def execute(self):
        if check_action_roundtime(self.player, action_type="other"):
            return

        player_key = self.player.name.lower()
        trade_offer = self.world.get_pending_trade(player_key)
        
        if not trade_offer:
            self.player.send_message("You have not been offered anything.")
            return
            
        giver_player = self.world.get_player_obj(trade_offer['from_player_name'].lower())
        if not giver_player or giver_player.current_room_id != self.player.current_room_id:
            self.player.send_message(f"{trade_offer['from_player_name']} is no longer here.")
            self.world.remove_pending_trade(player_key) 
            return
            
        trade_type = trade_offer.get("trade_type", "item")
        item_name = trade_offer.get("item_name", "the item")

        if trade_type == "item": 
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
                
            if item_source == "inventory":
                giver_player.inventory.remove(item_id)
            else: 
                giver_player.worn_items[item_source] = None
            
            right_hand_slot = "mainhand"
            left_hand_slot = "offhand"
            giver_player_name_lower = giver_player.name.lower()

            if self.player.worn_items.get(right_hand_slot) is None:
                self.player.worn_items[right_hand_slot] = item_id
                self.player.send_message(f"You accept {item_name} from {giver_player.name} and hold it in your right hand.")
                self.world.send_message_to_player(giver_player_name_lower, f"{self.player.name} accepts your offer for {item_name}.")
            elif self.player.worn_items.get(left_hand_slot) is None:
                self.player.worn_items[left_hand_slot] = item_id
                self.player.send_message(f"You accept {item_name} from {giver_player.name} and hold it in your left hand.")
                self.world.send_message_to_player(giver_player_name_lower, f"{self.player.name} accepts your offer for {item_name}.")
            else:
                self.player.inventory.append(item_id)
                self.player.send_message(f"You accept {item_name} from {giver_player.name}. Your hands are full, so you place it in your pack.")
                self.world.send_message_to_player(giver_player_name_lower, f"{self.player.name} accepts your offer for {item_name}.")

            self.world.remove_pending_trade(player_key)
            set_action_roundtime(self.player, 1.0)

        elif trade_type == "exchange":
            item_id = trade_offer['item_id']
            item_source = trade_offer['item_source_location']
            silver_amount = trade_offer['silver_amount']
            
            if self.player.wealth.get("silvers", 0) < silver_amount:
                self.player.send_message(f"You cannot afford this. You need {silver_amount} silver.")
                return

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
            
            self.player.wealth["silvers"] = self.player.wealth.get("silvers", 0) - silver_amount
            giver_player.wealth["silvers"] = giver_player.wealth.get("silvers", 0) + silver_amount
            
            if item_source == "inventory":
                giver_player.inventory.remove(item_id)
            else: 
                giver_player.worn_items[item_source] = None
            
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
            
            self.player.send_message(f"You hand {giver_player.name} {silver_amount} silver.\n{item_received_msg}")
            
            self.world.send_message_to_player(
                giver_player.name.lower(),
                f"{self.player.name} hands you {silver_amount} silver.\n"
                f"{self.player.name} has accepted your offer."
            )
            
            self.world.remove_pending_trade(player_key)
            set_action_roundtime(self.player, 1.0)

@VerbRegistry.register(["decline"]) 
class Decline(BaseVerb):
    """Handles the 'decline' command for trades."""
    def execute(self):
        if check_action_roundtime(self.player, action_type="other"):
            return

        player_key = self.player.name.lower()
        trade_offer = self.world.remove_pending_trade(player_key)
        
        if not trade_offer:
            self.player.send_message("You have no offers to decline.")
            return
            
        self.player.send_message(f"You decline the offer from {trade_offer['from_player_name']}.")
        giver_player_name_lower = trade_offer['from_player_name'].lower()
        self.world.send_message_to_player(giver_player_name_lower, f"{self.player.name} declines your offer.")
        set_action_roundtime(self.player, 1.0)

@VerbRegistry.register(["cancel"]) 
class Cancel(BaseVerb):
    """Handles the 'cancel' command to retract an offer."""
    def execute(self):
        if check_action_roundtime(self.player, action_type="other"):
            return
        
        giver_key = self.player.name.lower()
        offer_to_cancel = None
        receiver_name = None
        
        with self.world.trade_lock:
            for r_name, offer in self.world.pending_trades.items():
                if offer.get("from_player_name", "").lower() == giver_key:
                    offer_to_cancel = offer
                    receiver_name = r_name
                    break
        
        if offer_to_cancel and receiver_name:
            self.world.remove_pending_trade(receiver_name)
            self.player.send_message(f"You cancel your offer to {receiver_name}.")
            self.world.send_message_to_player(receiver_name, f"{self.player.name} cancels their offer.")
        else:
            self.player.send_message("You have no active offers to cancel.")
            
        set_action_roundtime(self.player, 1.0)

@VerbRegistry.register(["exchange"]) 
class Exchange(BaseVerb):
    """
    Handles the 'exchange' command.
    EXCHANGE {item} WITH {player} FOR {silvers} SILVER
    """
    def execute(self):
        if check_action_roundtime(self.player, action_type="other"):
            return

        args_str = " ".join(self.args).lower()
        
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

        target_player = self.world.get_player_obj(target_player_name)
        if not target_player or target_player.current_room_id != self.player.current_room_id:
            self.player.send_message(f"You don't see anyone named '{target_player_name}' here.")
            return
            
        if target_player.name.lower() == self.player.name.lower():
            self.player.send_message("You can't exchange things with yourself.")
            return
            
        if self.world.get_pending_trade(target_player.name.lower()):
            self.player.send_message(f"{target_player.name} already has a pending offer. Please wait.")
            return

        item_id_to_give = None
        item_source_location = None
        
        if target_item_name == "left":
            item_id_to_give = self.player.worn_items.get("offhand")
            item_source_location = "offhand"
        elif target_item_name == "right":
            item_id_to_give = self.player.worn_items.get("mainhand")
            item_source_location = "mainhand"
        
        if not item_id_to_give:
            item_id_hand, hand_slot = find_item_in_hands(self.player, self.world.game_items, target_item_name)
            if item_id_hand:
                item_id_to_give = item_id_hand
                item_source_location = hand_slot
            else:
                item_id_inv = find_item_in_inventory(self.player, self.world.game_items, target_item_name)
                if item_id_inv:
                    item_id_to_give = item_id_inv
                    item_source_location = "inventory"
        
        if not item_id_to_give:
            self.player.send_message(f"You don't have a '{target_item_name}' in your pack or hands.")
            return
            
        item_data = self.world.game_items.get(item_id_to_give) if isinstance(item_id_to_give, str) else item_id_to_give
        item_name = item_data.get('name', 'an item')
        
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

        self.player.send_message(
            f"You offer your {item_name} to {target_player.name} for {silver_amount} silvers. "
            f"She has 30 seconds to accept the offer. "
            f"Type '<span class='keyword' data-command='cancel'>CANCEL</span>' to prematurely cancel the offer."
        )
        
        self.world.send_message_to_player(
            target_player.name.lower(),
            f"{self.player.name} offers you {self.player.name}'s {item_name} for {silver_amount} silvers. "
            f"Type '<span class='keyword' data-command='accept'>ACCEPT</span>' to pay the silvers and accept the offer or "
            f"'<span class='keyword' data-command='decline'>DECLINE</span>' to decline it. "
            f"The offer will expire in 30 seconds."
        )
        set_action_roundtime(self.player, 1.0)