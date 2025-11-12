# mud_backend/verbs/observation.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.db import fetch_player_data
from mud_backend.core.chargen_handler import format_player_description
from mud_backend.core.room_handler import show_room_to_player
import math
import random # <-- NEW
# --- NEW: Import LBD and RT helpers ---
from mud_backend.core.skill_handler import attempt_skill_learning
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.utils import calculate_skill_bonus
# --- END NEW ---


class Examine(BaseVerb):
    """
    Handles the 'examine' command.
    Checks a player's Investigation (LOG) skill against hidden object details.
    """
    
    def execute(self):
        # --- NEW: Add LBD hook ---
        # We grant a chance to learn even on a simple EXAMINE
        attempt_skill_learning(self.player, "investigation")
        # --- END NEW ---

        if not self.args:
            self.player.send_message("Examine what?")
            return

        target_name = " ".join(self.args).lower()
        if target_name.startswith("at "):
            target_name = target_name[3:]
            
        found_object = None
        for obj in self.room.objects:
            if (target_name == obj.get("name", "").lower() or 
                target_name in obj.get("keywords", [])):
                found_object = obj
                break

        if not found_object:
            self.player.send_message(f"You do not see a **{target_name}** here.")
            return

        # 2. Show the base description
        self.player.send_message(f"You examine the **{found_object['name']}**.")
        self.player.send_message(found_object.get('description', 'It is a nondescript object.'))

        # 3. Check for hidden details (LOG stat check, per your original file)
        player_log_stat = self.player.stats.get("LOG", 0)
        hidden_details = found_object.get("details", [])
        
        if not hidden_details:
            self.player.send_message("You don't notice anything else unusual about it.")
            return
            
        found_something = False
        for detail in hidden_details:
            dc = detail.get("dc", 100) # Default to a high DC
            
            # 4. Compare player LOG stat to the detail's Difficulty Class (DC)
            if player_log_stat >= dc:
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
            # --- NEW: Tutorial Hook ---
            if (self.player.current_room_id == "inn_room" and
                "intro_examine" not in self.player.completed_quests):
                self.player.send_message(
                    "\n<span class='keyword' data-command='help examine'>[Help: EXAMINE]</span> - You can look *at* specific things. "
                    "Try <span class='keyword' data-command='examine table'>EXAMINE TABLE</span> to see more detail."
                )
                self.player.completed_quests.append("intro_examine")
            # --- END NEW ---
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
            if (target_name == obj.get("name", "").lower() or 
                target_name in obj.get("keywords", [])):
            # --- END FIX ---
                self.player.send_message(f"You examine the **{obj['name']}**.")
                self.player.send_message(obj.get('description', 'It is a nondescript object.'))
                if 'verbs' in obj:
                    verb_list = ", ".join([f'<span class="keyword">{v}</span>' for v in obj['verbs']])
                    self.player.send_message(f"You could try: {verb_list}")
                
                # --- NEW: Tutorial Hook ---
                if (self.player.current_room_id == "inn_room" and
                    target_name == "table" and
                    "intro_investigate" not in self.player.completed_quests):
                    self.player.send_message(
                        "\n<span class='keyword' data-command='help investigate'>[Help: INVESTIGATE]</span> - Things are not always as they seem. "
                        "LOOK gives you a basic view, but you should "
                        "<span class='keyword' data-command='investigate'>INVESTIGATE</span> if you think there is more to be found."
                    )
                    self.player.completed_quests.append("intro_investigate")
                # --- END NEW ---
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
        target_player_obj = self.world.get_player_obj(target_name)
        
        if target_player_obj and target_player_obj.current_room_id == self.room.room_id:
            target_player_data = target_player_obj.to_dict() 
            self.player.send_message(f"You see **{target_player_data['name']}**.")
            description = format_player_description(target_player_data)
            self.player.send_message(description)
            return
            
        # --- E. Not found ---
        self.player.send_message(f"You do not see a **{target_name}** here.")

# ---
# --- NEW: Investigate class
# ---
class Investigate(BaseVerb):
    """
    Handles the 'investigate' command.
    Calls LBD for 'investigation'.
    If no args, searches for hidden objects.
    If args, performs an 'examine'.
    """
    
    def execute(self):
        # 1. Always attempt to learn by doing
        attempt_skill_learning(self.player, "investigation")
        
        # 2. Check for roundtime
        if _check_action_roundtime(self.player, action_type="other"):
            return
            
        # 3. Set roundtime for this action
        _set_action_roundtime(self.player, 3.0) # 3 second RT

        # 4. If args (e.g., INVESTIGATE TABLE), just run Examine
        if self.args:
            examine_verb = Examine(self.world, self.player, self.room, self.args)
            examine_verb.execute()
            return

        # 5. If no args, search the room for hidden objects
        self.player.send_message("You investigate the room...")
        
        hidden_objects = self.room.db_data.get("hidden_objects", [])
        if not hidden_objects:
            self.player.send_message("...but you don't find anything unusual.")
            return
            
        found_something = False
        # Iterate backwards so we can .pop() items safely
        for i in range(len(hidden_objects) - 1, -1, -1):
            obj = hidden_objects[i]
            dc = obj.get("perception_dc", 100)
            
            # Roll = d100 + Investigation Skill Bonus
            skill_rank = self.player.skills.get("investigation", 0)
            skill_bonus = calculate_skill_bonus(skill_rank)
            roll = random.randint(1, 100) + skill_bonus
            
            if roll >= dc:
                # Found it!
                found_obj = self.room.db_data["hidden_objects"].pop(i)
                self.room.objects.append(found_obj)
                found_something = True
                
                self.player.send_message(f"Your investigation reveals: **{found_obj.get('name', 'an item')}**!")
                
                # --- Special Tutorial Hook ---
                if (found_obj.get("item_id") == "inn_note" and
                    "intro_get" not in self.player.completed_quests):
                    self.player.send_message(
                         "\n<span class='keyword' data-command='help get'>[Help: GET]</span> - You found a note! "
                         "To pick it up, you can <span class='keyword' data-command='get note'>GET NOTE</span>."
                    )
                    self.player.completed_quests.append("intro_get")
        
        if found_something:
            # We modified the room, so save it
            self.world.save_room(self.room)
        else:
            self.player.send_message("...but you don't find anything new.")