# verbs/climb.py
from mud_backend.verbs.base_verb import BaseVerb

class Climb(BaseVerb):
    """Handles the 'climb' command to move between connected objects (like wells/ropes)."""
    
    def execute(self):
        if not self.args:
            self.player.send_message("Climb what? (e.g., CLIMB ROPE or CLIMB WELL)")
            return

        target_name = self.args[0].lower()
        
        # 1. Find the object the player wants to climb
        climbable_object = next((obj for obj in self.room.objects 
                                 if obj['name'].lower() == target_name and "CLIMB" in obj.get("verbs", [])), None)

        if not climbable_object:
            self.player.send_message(f"You cannot climb the **{target_name}** here.")
            return

        target_room_id = climbable_object.get("target_room")

        if not target_room_id:
            self.player.send_message(f"The {target_name} leads nowhere right now.")
            return

        # 2. Change the player's room
        self.player.current_room_id = target_room_id
        
        # 3. Success message (and implied LOOK command)
        self.player.send_message(f"You grasp the rope and begin to climb...")
        self.player.send_message(f"After a few moments, you arrive at {target_room_id}.")

        # --- REMOVED: The old monster spawning logic is gone. ---
        # The monster is now part of the room's permanent object list
        # and will be shown by the 'look' command.
                
        # The main executor will save the player and room state after this verb runs.
