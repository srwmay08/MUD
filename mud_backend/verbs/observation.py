# mud_backend/verbs/observation.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.db import fetch_player_data
from mud_backend.core.chargen_handler import format_player_description
from mud_backend.core.room_handler import show_room_to_player
import math
# --- REMOVED: from mud_backend.core import game_state ---

# --- Class from examine.py ---
class Examine(BaseVerb):
    """
    Handles the 'examine' command.
    Checks a player's Investigation (LOG) skill against hidden object details.
    """
    
    def execute(self):
        if not self.args:
            self.player.send_message("Examine what?")
            return

        target_name = " ".join(self.args).lower()
        if target_name.startswith("at "):
            target_name = target_name[3:]
            
        # --- UPDATED: Find target by name OR keyword ---
        found_object = None
        for obj in self.room.objects:
            if (target_name == obj.get("name", "").lower() or 
                target_name in obj.get("keywords", [])):
                found_object = obj
                break
        # --- END UPDATED ---

        if not found_object:
            self.player.send_message(f"You do not see a **{target_name}** here.")
            return

        # 2. Show the base description
        self.player.send_message(f"You examine the **{found_object['name']}**.")
        self.player.send_message(found_object.get('description', 'It is a nondescript object.'))

        # 3. Check for hidden details (Investigation Skill Check)
        player_investigation = self.player.stats.get("LOG", 0)
        hidden_details = found_object.get("details", [])
        
        if not hidden_details:
            self.player.send_message("You don't notice anything else unusual about it.")
            return
            
        found_something = False
        for detail in hidden_details:
            dc = detail.get("dc", 100) # Default to a high DC
            
            # 4. Compare player skill to the detail's Difficulty Class (DC)
            if player_investigation >= dc:
                self.player.send_message(detail.get("description", "You notice a hidden detail."))
                found_something = True
        
        if not found_something:
            # Player failed all checks
            self.player.send_message("You don't notice anything else unusual about it.")

# ---
# --- NEW: Helper function to find items on player
# ---
def _find_item_on_player(player, target_name):
    """Checks worn items and inventory for a match."""
    # Check worn items
    for slot, item_id in player.worn_items.items():
        if item_id:
            # --- FIX: Use player.world ---
            item_data = player.world.game_items.get(item_id)
            if item_data:
                # Check keywords first, then the item's name
                if target_name in item_data.get("keywords", []) or target_name == item_data['name'].lower():
                    return item_data, "worn"
                    
    # Check inventory (pack)
    for item_id in player.inventory:
        # --- FIX: Use player.world ---
        item_data = player.world.game_items.get(item_id)
        if item_data:
            if target_name in item_data.get("keywords", []) or target_name == item_data['name'].lower():
                return item_data, "inventory"
                
    return None, None

# ---
# --- MODIFIED: Look verb
# ---
class Look(BaseVerb):
    """Handles the 'look' command."""
    
    def execute(self):
        
        # --- 1. LOOK (no args) ---
        if not self.args:
            show_room_to_player(self.player, self.room)
            return

        full_command = " ".join(self.args).lower()

        # --- 2. LOOK IN <CONTAINER> ---
        if full_command.startswith("in "):
            container_name = full_command[3:].strip()
            
            # Find the container (on player or in room)
            container_data, location = _find_item_on_player(self.player, container_name)
            
            # TODO: Add logic to find container in room
            
            if not container_data or not container_data.get("is_container"):
                self.player.send_message(f"You don't see a container called '{container_name}' here.")
                return

            # Special case: 'backpack' is the player's main inventory
            # We treat the "back" slot as the main inventory container
            if container_data.get("wearable_slot") == "back":
                if not self.player.inventory:
                    self.player.send_message(f"Your {container_data['name']} is empty.")
                    return
                
                self.player.send_message(f"You look in your {container_data['name']}:")
                for item_id in self.player.inventory:
                    # --- FIX: Use self.world ---
                    item_data = self.world.game_items.get(item_id)
                    self.player.send_message(f"- {item_data.get('name', 'an item')}")
                return
            else:
                # Logic for other containers (e.g., a pouch)
                self.player.send_message(f"You look in {container_data['name']}.")
                # (We would add logic here to list items *inside* that item)
                self.player.send_message("It is empty.")
                return
                
        # --- 3. LOOK <TARGET> ---
        target_name = full_command
        if target_name.startswith("at "):
            target_name = target_name[3:]

        # A. Check room objects
        for obj in self.room.objects:
            # --- THIS IS THE FIX ---
            # Check if the target name matches the object's name OR is in its keywords
            if (target_name == obj.get("name", "").lower() or 
                target_name in obj.get("keywords", [])):
            # --- END FIX ---
                self.player.send_message(f"You examine the **{obj['name']}**.")
                self.player.send_message(obj.get('description', 'It is a nondescript object.'))
                if 'verbs' in obj:
                    verb_list = ", ".join([f'<span class="keyword">{v}</span>' for v in obj['verbs']])
                    self.player.send_message(f"You could try: {verb_list}")
                return 

        # B. Check player's own items (worn or inventory)
        item_data, location = _find_item_on_player(self.player, target_name)
        if item_data:
            self.player.send_message(f"You look at your **{item_data['name']}**.")
            self.player.send_message(item_data.get('description', 'It is a nondescript object.'))
            return

        # C. Check if target is 'self'
        if target_name == self.player.name.lower() or target_name == "self":
            self.player.send_message(f"You see **{self.player.name}** (that's you!).")
            self.player.send_message(format_player_description(self.player.to_dict()))
            return
                
        # D. Check if target is another player
        # --- REFACTORED: Use self.world to get player object ---
        target_player_obj = self.world.get_player_obj(target_name)
        
        if target_player_obj and target_player_obj.current_room_id == self.room.room_id:
            # We can use the object directly
            target_player_data = target_player_obj.to_dict() 
            self.player.send_message(f"You see **{target_player_data['name']}**.")
            description = format_player_description(target_player_data)
            self.player.send_message(description)
            return
        # --- END REFACTORED ---
            
        # --- E. Not found ---
        self.player.send_message(f"You do not see a **{target_name}** here.")

# --- Class from investigate.py ---
class Investigate(Examine):
    """
    Handles the 'investigate' command.
    This verb is an alias for 'examine' and uses the same logic.
    """
    pass