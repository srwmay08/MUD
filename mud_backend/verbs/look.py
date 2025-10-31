# verbs/look.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.db import fetch_player_data
from mud_backend.core.chargen_handler import format_player_description
# --- NEW IMPORT ---
from mud_backend.core.room_handler import show_room_to_player

class Look(BaseVerb):
    """Handles the 'look' command."""
    
    def execute(self):
        if not self.args:
            # --- 1. LOOK (at room) ---
            # This is now handled by the central room_handler
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

            # B. Check if target is a player
            if target_name.lower() == self.player.name.lower():
                self.player.send_message(f"You see **{self.player.name}** (that's you!).")
                self.player.send_message(format_player_description(self.player.to_dict()))
                return

            target_player_data = fetch_player_data(target_name)
            
            if target_player_data:
                self.player.send_message(f"You see **{target_player_data['name']}**.")
                description = format_player_description(target_player_data)
                self.player.send_message(description)
                return

            # C. Not found
            self.player.send_message(f"You do not see a **{target_name}** here.")