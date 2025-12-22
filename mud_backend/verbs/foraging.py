# mud_backend/verbs/foraging.py
import time
import random
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core.item_utils import get_item_data, find_item_in_hands, find_item_in_inventory
from mud_backend.core.utils import check_action_roundtime, set_action_roundtime

@VerbRegistry.register(["forage", "search"])
class Forage(BaseVerb):
    def execute(self):
        if check_action_roundtime(self.player, "other"): return
        
        # Check room forageable data
        room_data = self.room.data
        if not room_data.get("forageable"):
            self.player.send_message("You don't see anything worth foraging here.")
            return

        skill_level = self.player.skills.get("survival", 0)
        chance = 30 + (skill_level * 2)
        
        self.player.send_message("You begin searching the area for useful resources...")
        
        if random.randint(1, 100) <= chance:
            possible_items = room_data.get("forage_items", [])
            if not possible_items:
                self.player.send_message("You find nothing of interest.")
            else:
                item_id = random.choice(possible_items)
                item_template = self.world.game_items.get(item_id)
                if item_template:
                    import copy
                    import uuid
                    new_item = copy.deepcopy(item_template)
                    new_item["uid"] = uuid.uuid4().hex
                    
                    if not self.player.worn_items.get("mainhand"):
                        self.player.worn_items["mainhand"] = new_item
                        self.player.send_message(f"You found {new_item['name']} and picked it up.")
                    elif not self.player.worn_items.get("offhand"):
                        self.player.worn_items["offhand"] = new_item
                        self.player.send_message(f"You found {new_item['name']} and picked it up.")
                    else:
                        self.player.inventory.append(new_item)
                        self.player.send_message(f"You found {new_item['name']} and put it in your pack.")
                        
                    self.player.grant_experience(10, source="survival")
        else:
            self.player.send_message("You search fruitlessly.")
            
        set_action_roundtime(self.player, 5.0)

@VerbRegistry.register(["eat", "consume"])
class Eat(BaseVerb):
    def execute(self):
        if check_action_roundtime(self.player, "other"): return
        if not self.args:
            self.player.send_message("Eat what?")
            return
            
        target_name = " ".join(self.args).lower()
        
        # Check hands first
        item_ref, hand_slot = find_item_in_hands(self.player, self.world.game_items, target_name)
        from_inventory = False
        
        if not item_ref:
            item_ref = find_item_in_inventory(self.player, self.world.game_items, target_name)
            from_inventory = True
            
        if not item_ref:
            self.player.send_message(f"You aren't holding or carrying any '{target_name}'.")
            return
            
        item_data = get_item_data(item_ref, self.world.game_items)
        
        if not item_data.get("is_edible"):
            self.player.send_message("That doesn't look edible.")
            return
            
        self.player.send_message(f"You eat the {item_data['name']}.")
        
        # Apply effects
        if "nutrition" in item_data:
            self.player.stamina = min(self.player.max_stamina, self.player.stamina + item_data["nutrition"])
            self.player.send_message("You feel refreshed.")
            
        # Remove item
        if from_inventory:
            self.player.inventory.remove(item_ref)
        else:
            self.player.worn_items[hand_slot] = None
            
        set_action_roundtime(self.player, 2.0)

@VerbRegistry.register(["drink", "quaff"])
class Drink(BaseVerb):
    def execute(self):
        if check_action_roundtime(self.player, "other"): return
        if not self.args:
            self.player.send_message("Drink what?")
            return
            
        target_name = " ".join(self.args).lower()
        
        # Check hands first
        item_ref, hand_slot = find_item_in_hands(self.player, self.world.game_items, target_name)
        from_inventory = False
        
        if not item_ref:
            item_ref = find_item_in_inventory(self.player, self.world.game_items, target_name)
            from_inventory = True
            
        if not item_ref:
            self.player.send_message(f"You aren't holding or carrying any '{target_name}'.")
            return
            
        item_data = get_item_data(item_ref, self.world.game_items)
        
        if not item_data.get("is_drinkable"):
            self.player.send_message("You can't drink that.")
            return
            
        self.player.send_message(f"You drink from the {item_data['name']}.")
        
        # Apply effects
        if "hydration" in item_data:
            # Simple stamina restore for now
            self.player.stamina = min(self.player.max_stamina, self.player.stamina + item_data["hydration"])
            self.player.send_message("That hit the spot.")
            
        # Handle consumption (remove item or transform it)
        remaining_sips = item_data.get("sips", 1) - 1
        
        # Handle Dynamic Item Updates
        if isinstance(item_ref, dict):
            if remaining_sips > 0:
                item_ref["sips"] = remaining_sips
                self.player.send_message(f"There are {remaining_sips} sips left.")
            else:
                if from_inventory:
                    self.player.inventory.remove(item_ref)
                else:
                    self.player.worn_items[hand_slot] = None
                self.player.send_message(f"You finish the {item_data['name']}.")
        # Handle Static Item References
        else:
            if from_inventory:
                self.player.inventory.remove(item_ref)
            else:
                self.player.worn_items[hand_slot] = None
            self.player.send_message(f"You finish the {item_data['name']}.")
            
        set_action_roundtime(self.player, 2.0)