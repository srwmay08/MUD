# mud_backend/verbs/observation.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.db import fetch_player_data
from mud_backend.core.chargen_handler import format_player_description
from mud_backend.core.room_handler import show_room_to_player
import math
from mud_backend.core import game_state

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
            
        # --- UPDATED: Find target by keyword ---
        found_object = None
        for obj in self.room.objects:
            # Check keywords if they exist, fall back to name
            if target_name in obj.get("keywords", [obj.get("name", "").lower()]):
                found_object = obj
                break
        # ---

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

# --- Class from look.py ---
class Look(BaseVerb):
    """Handles the 'look' command."""
    
    def execute(self):
        if not self.args:
            # --- 1. LOOK (at room) ---
            show_room_to_player(self.player, self.room)
                
        else:
            # --- 2. LOOK <TARGET> ---
            target_name = " ".join(self.args).lower() 
            if target_name.startswith("at "):
                target_name = target_name[3:]

            # --- UPDATED: Find target by keyword ---
            found_object = None
            for obj in self.room.objects:
                # Check keywords if they exist, fall back to name
                if target_name in obj.get("keywords", [obj.get("name", "").lower()]):
                    found_object = obj
                    break
            # ---

            if found_object:
                self.player.send_message(f"You examine the **{found_object['name']}**.")
                self.player.send_message(found_object.get('description', 'It is a nondescript object.'))
                
                if 'verbs' in found_object:
                    verb_list = ", ".join([f'<span class="keyword">{v}</span>' for v in found_object['verbs']])
                    self.player.send_message(f"You could try: {verb_list}")
                return 

            # B. Check if target is 'self'
            if target_name == self.player.name.lower():
                self.player.send_message(f"You see **{self.player.name}** (that's you!).")
                self.player.send_message(format_player_description(self.player.to_dict()))
                return
                
            # --- C. (REVISED) Check if target is another player *in the room* ---
            
            # Find the player in the global active list by lowercase name
            target_player_state = game_state.ACTIVE_PLAYERS.get(target_name)
            
            # Check if they are online AND in the same room
            if target_player_state and target_player_state["current_room_id"] == self.room.room_id:
                # They are here! Get their case-correct name
                target_case_correct_name = target_player_state["player_name"]
                
                # Fetch their full data for description
                target_player_data = fetch_player_data(target_case_correct_name)
                
                if target_player_data:
                    self.player.send_message(f"You see **{target_player_data['name']}**.")
                    description = format_player_description(target_player_data)
                    self.player.send_message(description)
                    return
            
            # --- D. Not found ---
            self.player.send_message(f"You do not see a **{target_name}** here.")

# --- Class from investigate.py ---
class Investigate(Examine):
    """
    Handles the 'investigate' command.
    This verb is an alias for 'examine' and uses the same logic.
    """
    pass