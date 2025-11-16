# mud_backend/verbs/inventory.py
from mud_backend.verbs.base_verb import BaseVerb
# --- REMOVED: from mud_backend.core import game_state ---
from mud_backend import config
# ---
# --- NEW: Import RT helpers ---
# ---
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
# ---
# --- END NEW ---


class Inventory(BaseVerb):
    """
    Handles the 'inventory' (and 'inv') command.
    """
    
    def execute(self):
        args = " ".join(self.args).lower()
        
        if "help" in args:
            self.show_help()
            return
            
        # --- 1. Get items held in hands ---
        right_hand_id = self.player.worn_items.get("mainhand")
        left_hand_id = self.player.worn_items.get("offhand")
        
        held_items_msg = []
        if right_hand_id:
            item_data = self.world.game_items.get(right_hand_id)
            if item_data:
                held_items_msg.append(f"holding {item_data['name']} in your right hand")
        
        if left_hand_id:
            item_data = self.world.game_items.get(left_hand_id)
            if item_data:
                held_items_msg.append(f"holding {item_data['name']} in your left hand")

        if held_items_msg:
            self.player.send_message(f"You are {', and '.join(held_items_msg)}.")
        
        # --- 2. Get all other worn items ---
        worn_items_msg = []
        total_items = 0
        
        for slot_id, slot_name in config.EQUIPMENT_SLOTS.items():
            if slot_id in ["mainhand", "offhand"]:
                continue
                
            item_id = self.player.worn_items.get(slot_id)
            if item_id:
                item_data = self.world.game_items.get(item_id)
                if item_data:
                    worn_items_msg.append(f"{item_data['name']} (worn on {slot_name})")
                    total_items += 1

        if worn_items_msg:
            self.player.send_message(f"You are wearing: {', '.join(worn_items_msg)}.")
            
        total_items += len(held_items_msg)
        
        if total_items == 0:
            self.player.send_message("You are not carrying or wearing anything.")
            
        self.player.send_message(f"\n(Items: {total_items})")

        # ---
        # --- THIS IS THE FIX ---
        # ---
        # This hook triggers if 'look at note' (intro_leave_room_tasks) was done
        if ("intro_leave_room_tasks" in self.player.completed_quests and
            "intro_lookinpack" not in self.player.completed_quests):
            
            self.player.send_message(
                "\n<span class='keyword' data-command='help look'>[Help: LOOK]</span> - To see what is in your backpack, you must "
                "<span class='keyword' data-command='look in pack'>LOOK IN PACK</span>."
            )
            self.player.completed_quests.append("intro_lookinpack")
            
            # Also set the 'wealth_checked' flag, since INVENTORY implies checking your belongings
            if "intro_wealth_checked" not in self.player.completed_quests:
                self.player.completed_quests.append("intro_wealth_checked")
        # ---
        # --- END FIX
        # ---

    def show_help(self):
        self.player.send_message("Usage:")
        self.player.send_message("  INVENTORY - List your held and worn items.")
        self.player.send_message("  (More inventory commands are coming soon!)")


class Wealth(BaseVerb):
    """
    Handles the 'wealth' command.
    """
    
    def execute(self):
        args = " ".join(self.args).lower()
        silvers = self.player.wealth.get("silvers", 0)
        
        msg = ""
        if silvers == 0:
            msg = "You have no silver with you."
        elif silvers == 1:
            msg = "You have but one coin with you."
        else:
            msg = f"You have {silvers:,} coins with you."
            
        self.player.send_message(msg)
        
        if "loud" in args:
            print(f"[Broadcast] {self.player.name} rummages around in their pockets.")

        # ---
        # --- THIS IS THE FIX ---
        # ---
        # This hook triggers if 'look at note' (intro_leave_room_tasks) was done
        if ("intro_leave_room_tasks" in self.player.completed_quests and
            "intro_wealth_checked" not in self.player.completed_quests):
            
            self.player.send_message(
                "\n<span class='keyword' data-command='help inventory'>[Help: INVENTORY]</span> - Now check your "
                "<span class='keyword' data-command='inventory'>INVENTORY</span> to see what you're carrying."
            )
            self.player.completed_quests.append("intro_wealth_checked")
        # ---
        # --- END FIX
        # ---

# ---
# --- NEW: SWAP VERB
# ---
class Swap(BaseVerb):
    """
    Handles the 'swap' command.
    Swaps the items in the player's main hand and off hand.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"):
            return

        mainhand_item_id = self.player.worn_items.get("mainhand")
        offhand_item_id = self.player.worn_items.get("offhand")

        if not mainhand_item_id and not offhand_item_id:
            self.player.send_message("Your hands are empty.")
            return

        # Swap the item IDs
        self.player.worn_items["mainhand"] = offhand_item_id
        self.player.worn_items["offhand"] = mainhand_item_id

        # Build the message
        if mainhand_item_id and offhand_item_id:
            mainhand_name = self.world.game_items.get(mainhand_item_id, {}).get("name", "an item")
            offhand_name = self.world.game_items.get(offhand_item_id, {}).get("name", "an item")
            self.player.send_message(f"You swap {mainhand_name} to your left hand and {offhand_name} to your right hand.")
        elif mainhand_item_id: # Was in mainhand, now in offhand
            mainhand_name = self.world.game_items.get(mainhand_item_id, {}).get("name", "an item")
            self.player.send_message(f"You swap {mainhand_name} to your left hand.")
        elif offhand_item_id: # Was in offhand, now in mainhand
            offhand_name = self.world.game_items.get(offhand_item_id, {}).get("name", "an item")
            self.player.send_message(f"You swap {offhand_name} to your right hand.")

        _set_action_roundtime(self.player, 1.0)
# ---
# --- END NEW VERB
# ---