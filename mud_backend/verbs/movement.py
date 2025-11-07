# mud_backend/verbs/movement.py
from mud_backend.verbs.base_verb import BaseVerb
# --- REMOVED: fetch_room_data, Room, show_room_to_player ---
from mud_backend.core.command_executor import DIRECTION_MAP
# --- REFACTORED: Removed unused game_state import ---


# --- REMOVED: _stop_player_combat helper function ---


# --- Class from enter.py ---
class Enter(BaseVerb):
    """Handles the 'enter' command to move through doors, portals, etc."""
    
    def execute(self):
        if not self.args:
            self.player.send_message("Enter what?")
            return

        target_name = " ".join(self.args).lower()
        
        # 1. Find the object the player wants to enter
        enterable_object = next((obj for obj in self.room.objects 
                                 if obj['name'].lower() == target_name and "ENTER" in obj.get("verbs", [])), None)

        if not enterable_object:
            self.player.send_message(f"You cannot enter the **{target_name}**.")
            return

        target_room_id = enterable_object.get("target_room")

        if not target_room_id:
            self.player.send_message(f"The {target_name} leads nowhere right now.")
            return

        # --- REFACTOR ---
        # 2. Call the new Player method
        self.player.move_to_room(target_room_id, f"You enter the {target_name}...")
        # --- END REFACTOR ---

# --- Class from climb.py ---
class Climb(BaseVerb):
    """Handles the 'climb' command to move between connected objects (like wells/ropes)."""
    
    def execute(self):
        if not self.args:
            self.player.send_message("Climb what? (e.g., CLIMB ROPE or CLIMB WELL)")
            return

        target_name = self.args[0].lower()
        
        # 1. Find the object
        climbable_object = next((obj for obj in self.room.objects 
                                 if obj['name'].lower() == target_name and "CLIMB" in obj.get("verbs", [])), None)

        if not climbable_object:
            self.player.send_message(f"You cannot climb the **{target_name}** here.")
            return

        target_room_id = climbable_object.get("target_room")

        if not target_room_id:
            self.player.send_message(f"The {target_name} leads nowhere right now.")
            return
            
        # --- REFACTOR ---
        # 2. Call the new Player method
        move_msg = f"You grasp the {target_name} and begin to climb...\nAfter a few moments, you arrive."
        self.player.move_to_room(target_room_id, move_msg)
        # --- END REFACTOR ---

# --- Class from move.py ---
class Move(BaseVerb):
    """
    Handles all directional movement (n, s, go north) AND
    object-based movement (go door).
    """
    
    def execute(self):
        if not self.args:
            self.player.send_message("Move where? (e.g., NORTH, SOUTH, E, W, etc.)")
            return

        target_name = " ".join(self.args).lower()
        
        # 1. Normalize the direction (e.g., "n" -> "north")
        normalized_direction = DIRECTION_MAP.get(target_name, target_name)
        
        # --- CHECK 1: Is it a cardinal exit? ---
        target_room_id = self.room.exits.get(normalized_direction)
        
        if target_room_id:
            # --- Found a cardinal exit ---
            # --- REFACTOR ---
            self.player.move_to_room(target_room_id, f"You move {normalized_direction}...")
            # --- END REFACTOR ---
            return

        # --- CHECK 2: Is it an object you can 'enter'? ---
        # (This handles 'go door', 'move door')
        enterable_object = next((obj for obj in self.room.objects 
                                 if obj['name'].lower() == target_name and "ENTER" in obj.get("verbs", [])), None)
                                 
        if enterable_object:
            # --- Found an enterable object ---
            # We can just create an instance of the Enter verb and run it
            # No import needed, class is in the same file!
            enter_verb = Enter(self.player, self.room, self.args)
            enter_verb.execute() # This will handle its own combat check
            return

        # --- If neither, fail ---
        self.player.send_message("You cannot go that way.")

# --- Class from exit.py ---
class Exit(BaseVerb):
    """
    Handles the 'exit' and 'out' commands.
    Tries to find a special "out" exit first.
    If that fails, or if args are given (e.g., "exit door"),
    it tries to find an enterable object.
    """
    
    def execute(self):
        
        if not self.args:
            # --- CHECK 1: Handle 'exit' or 'out' (no args) ---
            # Try to find the special "out" exit
            target_room_id = self.room.exits.get("out")

            if target_room_id:
                # --- Found the "out" exit ---
                # --- REFACTOR ---
                self.player.move_to_room(target_room_id, "You head out...")
                # --- END REFACTOR ---
                return
            else:
                # --- No "out" exit, try to "enter door" ---
                # This handles being in the inn and typing "exit"
                enter_verb = Enter(self.player, self.room, ["door"])
                enter_verb.execute() # This will handle its own combat check
                return

        else:
            # --- CHECK 2: Handle 'exit <object>' (e.g., "exit door") ---
            # This is the same as "enter <object>"
            enter_verb = Enter(self.player, self.room, self.args)
            enter_verb.execute() # This will handle its own combat check
            return