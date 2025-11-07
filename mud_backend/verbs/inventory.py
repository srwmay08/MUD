# mud_backend/verbs/inventory.py
from mud_backend.verbs.base_verb import BaseVerb
# --- REMOVED: from mud_backend.core import game_state ---
from mud_backend import config

class Inventory(BaseVerb):
    """
    Handles the 'inventory' (and 'inv') command.
    """
    
    def execute(self):
        # We will implement the simple "INVENTORY" command first.
        # "INVENTORY FULL" and other args are more complex.
        
        args = " ".join(self.args).lower()
        
        if "help" in args:
            self.show_help()
            return
            
        # --- 1. Get items held in hands ---
        # (GSIV shows hands first)
        right_hand_id = self.player.worn_items.get("mainhand")
        left_hand_id = self.player.worn_items.get("offhand")
        
        held_items_msg = []
        if right_hand_id:
            # --- FIX: Use self.world.game_items ---
            item_data = self.world.game_items.get(right_hand_id)
            if item_data:
                held_items_msg.append(f"holding {item_data['name']} in your right hand")
        
        if left_hand_id:
            # --- FIX: Use self.world.game_items ---
            item_data = self.world.game_items.get(left_hand_id)
            if item_data:
                held_items_msg.append(f"holding {item_data['name']} in your left hand")

        if held_items_msg:
            self.player.send_message(f"You are {', and '.join(held_items_msg)}.")
        
        # --- 2. Get all other worn items ---
        worn_items_msg = []
        total_items = 0
        
        # Iterate over the *defined slots* to maintain order
        for slot_id, slot_name in config.EQUIPMENT_SLOTS.items():
            # Skip hands, we did them already
            if slot_id in ["mainhand", "offhand"]:
                continue
                
            item_id = self.player.worn_items.get(slot_id)
            if item_id:
                # --- FIX: Use self.world.game_items ---
                item_data = self.world.game_items.get(item_id)
                if item_data:
                    worn_items_msg.append(f"{item_data['name']} (worn on {slot_name})")
                    total_items += 1

        if worn_items_msg:
            self.player.send_message(f"You are wearing: {', '.join(worn_items_msg)}.")
            
        # --- 3. Get items in inventory (pack) ---
        # This is our version of "INVENTORY FULL" for now
        pack_items_msg = []
        for item_id in self.player.inventory:
            # --- FIX: Use self.world.game_items ---
            item_data = self.world.game_items.get(item_id)
            if item_data:
                pack_items_msg.append(item_data['name'])
                total_items += 1
                
        if pack_items_msg:
            self.player.send_message(f"\nIn your pack: {', '.join(pack_items_msg)}.")
        
        total_items += len(held_items_msg)
        
        if total_items == 0:
            self.player.send_message("You are not carrying or wearing anything.")
            
        self.player.send_message(f"\n(Items: {total_items})")

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
        
        # Handle WEALTH LOUD
        if "loud" in args:
            # This requires broadcasting, which we'll add later
            # For now, just print to server console
            print(f"[Broadcast] {self.player.name} rummages around in their pockets.")