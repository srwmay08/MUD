# mud_backend/verbs/inventory.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core.utils import check_action_roundtime, set_action_roundtime

@VerbRegistry.register(["inventory", "inv", "i"])
class Inventory(BaseVerb):
    def execute(self):
        self.player.send_message("You are wearing:")
        for slot, item_ref in self.player.worn_items.items():
            if item_ref:
                # FIX: Check if the item is already a dictionary (instantiated item)
                # BEFORE trying to look it up in the game_items registry.
                if isinstance(item_ref, dict):
                    item_data = item_ref
                else:
                    item_data = self.world.game_items.get(item_ref)
                
                if item_data:
                    name = item_data.get("name", "Unknown Item")
                    self.player.send_message(f"  {slot}: {name}")
        
        self.player.send_message("\nYou are carrying:")
        if not self.player.inventory:
            self.player.send_message("  Nothing.")
        else:
            for item in self.player.inventory:
                if isinstance(item, dict):
                    name = item.get("name", "Unknown Item")
                else:
                    item_data = self.world.game_items.get(item)
                    name = item_data.get("name", "Unknown Item") if item_data else item
                self.player.send_message(f"  {name}")
                
        self.player.send_message(f"\nWealth: {self.player.wealth['silvers']} silver.")