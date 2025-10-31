# verbs/look.py
from mud_backend.verbs.base_verb import BaseVerb
# --- NEW IMPORTS ---
from mud_backend.core.db import fetch_player_data
from mud_backend.core.chargen_handler import format_player_description

class Look(BaseVerb):
    """Handles the 'look' command."""
    
    def execute(self):
        if not self.args:
            # --- 1. LOOK (at room) ---
            self.player.send_message(f"**{self.room.name}**")
            self.player.send_message(self.room.description)
            
            # (We'll add 'look at other players in room' here later)
            
            if self.room.objects:
                html_objects = []
                for obj in self.room.objects:
                    obj_name = obj['name']
                    verbs = obj.get('verbs', ['look'])
                    verb_str = ','.join(verbs).lower()
                    html_objects.append(
                        f'<span class="keyword" data-name="{obj_name}" data-verbs="{verb_str}">{obj_name}</span>'
                    )
                self.player.send_message(f"\nObvious objects here: {', '.join(html_objects)}.")
                
        else:
            # --- 2. LOOK <TARGET> ---
            target_name = " ".join(self.args).lower() # Allow 'look at <name>'
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
                return # Found an object, so we are done

            # B. Check if target is a player
            # (Note: This currently lets you 'look' at any player anywhere)
            if target_name.lower() == self.player.name.lower():
                # Player is looking at themself
                self.player.send_message(f"You see **{self.player.name}** (that's you!).")
                self.player.send_message(format_player_description(self.player.to_dict()))
                return

            target_player_data = fetch_player_data(target_name)
            
            if target_player_data:
                self.player.send_message(f"You see **{target_player_data['name']}**.")
                # Use our new formatter
                description = format_player_description(target_player_data)
                self.player.send_message(description)
                return # Found a player, so we are done

            # C. Not found
            self.player.send_message(f"You do not see a **{target_name}** here.")
