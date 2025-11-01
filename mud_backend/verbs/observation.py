# mud_backend/verbs/observation.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.db import fetch_player_data
from mud_backend.core.chargen_handler import format_player_description
from mud_backend.core.room_handler import show_room_to_player
import math
# --- NEW IMPORT ---
from mud_backend.core import game_state

# --- Class from examine.py ---
class Examine(BaseVerb):
    # ... (This class is unchanged) ...
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
            
        # 1. Find the object in the room
        found_object = next((obj for obj in self.room.objects if obj['name'].lower() == target_name), None)

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

            # A. Check if target is an object in the room
            found_object = next((obj for obj in self.room.objects if obj['name'].lower() == target_name), None)

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
            target_player_state = None
            
            # Find the player in the global active list
            # The key 'sid' is the connection ID, 'data' holds the info
            for sid, data in game_state.ACTIVE_PLAYERS.items():
                
                # --- FIX: We must check against the name *inside* the data ---
                if data["player_name"].lower() == target_name:
                    target_player_state = data
                    break
            
            # Check if they are online AND in the same room
            if target_player_state and target_player_state["current_room_id"] == self.room.room_id:
                # They are here! Now fetch their full data for description
                target_player_data = fetch_player_data(target_name)
                
                if target_player_data:
                    self.player.send_message(f"You see **{target_player_data['name']}**.")
                    description = format_player_description(target_player_data)
                    self.player.send_message(description)
                    return
            
            # --- D. Not found ---
            self.player.send_message(f"You do not see a **{target_name}** here.")

# --- Class from investigate.py ---
class Investigate(Examine):
    # ... (This class is unchanged) ...
    """
    Handles the 'investigate' command.
    This verb is an alias for 'examine' and uses the same logic.
    """
    pass