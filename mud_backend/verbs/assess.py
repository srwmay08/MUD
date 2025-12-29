# mud_backend/verbs/assess.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core.item_utils import find_item_in_hands, find_item_in_inventory, get_item_data

@VerbRegistry.register(["assess"])
class Assess(BaseVerb):
    """
    ASSESS <item|furnace>
    Gives mechanical feedback on crafting items.
    Shows detailed stats based on Mining/Smithing skill.
    """
    def execute(self):
        if not self.args:
            self.player.send_message("Assess what?")
            return
            
        target_name = " ".join(self.args).lower()
        target_obj = None
        
        # 1. Search Room
        # ID MATCHING
        if target_name.startswith("#"):
            t_uid = target_name[1:]
            for obj in self.room.objects:
                if str(obj.get("uid")) == t_uid:
                    target_obj = obj
                    break
        # NAME MATCHING
        else:
            for obj in self.room.objects:
                if target_name in obj.get("keywords", []) or target_name == obj.get("name", "").lower():
                    target_obj = obj
                    break
        
        # 2. Search Hands/Inventory if not found in room
        if not target_obj:
            item_ref = None
            if target_name.startswith("#"):
                # Check Hands
                t_uid = target_name[1:]
                for slot in ["mainhand", "offhand"]:
                    item = self.player.worn_items.get(slot)
                    if item:
                        i_uid = item.get("uid") if isinstance(item, dict) else item
                        if str(i_uid) == t_uid:
                            item_ref = item
                            break
                # Check Inventory
                if not item_ref:
                    for item in self.player.inventory:
                        i_uid = item.get("uid") if isinstance(item, dict) else item
                        if str(i_uid) == t_uid:
                            item_ref = item
                            break
            else:
                # Standard Search
                item_ref, _ = find_item_in_hands(self.player, self.world.game_items, target_name)
                if not item_ref:
                    item_ref = find_item_in_inventory(self.player, self.world.game_items, target_name)
            
            if item_ref:
                target_obj = get_item_data(item_ref, self.world.game_items)

        # --- Assess Logic ---
        if target_obj:
            # Assess Furnace
            if "state" in target_obj:
                state = target_obj["state"]
                temp = state.get("temp", 20)
                fuel = state.get("fuel", 0)
                slag = state.get("slag", 0)
                
                skill_rank = self.player.skills.get("mining", 0)
                
                self.player.send_message(f"--- Assessment: {target_obj['name']} ---")
                
                if skill_rank < 10:
                    if temp < 100: self.player.send_message("Heat: Cold")
                    elif temp < 600: self.player.send_message("Heat: Warm")
                    elif temp < 1000: self.player.send_message("Heat: Hot")
                    else: self.player.send_message("Heat: Dangerously Hot")
                else:
                    self.player.send_message(f"Temperature: {temp}°C")
                    if temp > 1085: self.player.send_message("   (Sufficient to melt copper)")
                
                if skill_rank < 5:
                    fuel_desc = "Empty" if fuel <= 0 else "Some fuel remains"
                    self.player.send_message(f"Fuel: {fuel_desc}")
                else:
                    self.player.send_message(f"Fuel Level:  {int(fuel)} units")

                self.player.send_message(f"Air Flow:    {state.get('air_flow')}%")
                
                if skill_rank >= 15 and slag > 20:
                    self.player.send_message("**WARNING**: You hear the gurgling of molten waste. The furnace needs tapping!")
                return
                
            # Assess Items (General)
            if "quality" in target_obj:
                self.player.send_message(f"You inspect the {target_obj.get('name')}.")
                self.player.send_message(f"Quality: {target_obj.get('quality', 'standard').capitalize()}")
                if "temp" in target_obj and target_obj["temp"] > 50:
                    self.player.send_message("It is hot to the touch.")
                return

        self.player.send_message("You don't see that here to assess.")