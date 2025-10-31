# verbs/look.py
from mud_backend.verbs.base_verb import BaseVerb

class Look(BaseVerb):
    """Handles the 'look' command."""
    
    def execute(self):
        # The 'look' verb logic
        if not self.args:
            # Player is looking at the current room
            self.player.send_message(f"**{self.room.name}**")
            self.player.send_message(self.room.description)
            self.player.send_message("You see a few other people standing around.")
            
            # NEW: List objects in the room
            if self.room.objects:
                object_names = [obj['name'] for obj in self.room.objects]
                self.player.send_message(f"\nObvious objects here: {', '.join(object_names)}.")
                
        else:
            # Player is trying to look at something specific (e.g., 'look well')
            target = self.args[0].lower()
            
            # Check room objects for the target
            found_object = next((obj for obj in self.room.objects if obj['name'] == target), None)

            if found_object:
                self.player.send_message(f"You examine the **{found_object['name']}**.")
                self.player.send_message(found_object.get('description', 'It is a nondescript object.'))
                
                # List available actions
                if 'verbs' in found_object:
                    verb_list = ", ".join(found_object['verbs'])
                    self.player.send_message(f"You could try: {verb_list}")
            else:
                self.player.send_message(f"You do not see a **{target}** here.")