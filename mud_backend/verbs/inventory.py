# mud_backend/verbs/inventory.py
from mud_backend.verbs.base_verb import BaseVerb
# --- REMOVED: from mud_backend.core import game_state ---
from mud_backend import config

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
            
        # ---
        # --- MODIFICATION: Removed section 3 (Pack items)
        # ---
        
        total_items += len(held_items_msg)
        
        if total_items == 0:
            self.player.send_message("You are not carrying or wearing anything.")
            
        self.player.send_message(f"\n(Items: {total_items})")

        # ---
        # --- NEW: Tutorial Hook for LOOK IN PACK
        # ---
        if ("intro_inventory" in self.player.completed_quests and
            "intro_lookinpack" not in self.player.completed_quests):
            
            self.player.send_message(
                "\n<span class='keyword' data-command='help look'>[Help: LOOK]</span> - To see what is in your backpack, you must "
                "<span class='keyword' data-command='look in pack'>LOOK IN PACK</span>."
            )
            self.player.completed_quests.append("intro_lookinpack")
        # ---
        # --- END NEW
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