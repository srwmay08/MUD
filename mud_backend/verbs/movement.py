# mud_backend/verbs/movement.py
from mud_backend.verbs.base_verb import BaseVerb
# --- REMOVED: fetch_room_data, Room, show_room_to_player ---
from mud_backend.core.command_executor import DIRECTION_MAP
# --- REFACTORED: Removed unused game_state import ---
# --- NEW: Import RT helpers ---
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
import time
# --- END NEW ---


# --- REMOVED: _stop_player_combat helper function ---


# --- Class from enter.py ---
class Enter(BaseVerb):
    """Handles the 'enter' command to move through doors, portals, etc."""
    
    def execute(self):
        # --- NEW: RT Check ---
        if _check_action_roundtime(self.player):
            return
        # --- END NEW ---

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
            
        # --- NEW: Posture Check ---
        current_posture = self.player.posture
        
        if current_posture == "standing":
            move_msg = f"You enter the {target_name}..."
            rt = 3.0
        elif current_posture == "prone":
            move_msg = f"You crawl through the {target_name}..."
            rt = 8.0
        else: # sitting or kneeling
            self.player.send_message("You must stand up first.")
            return
        # --- END NEW ---

        # 2. Call the new Player method
        self.player.move_to_room(target_room_id, move_msg)
        
        # 3. Set Roundtime
        _set_action_roundtime(self.player, rt)


# --- Class from climb.py ---
class Climb(BaseVerb):
    """Handles the 'climb' command to move between connected objects (like wells/ropes)."""
    
    def execute(self):
        # --- NEW: RT Check ---
        if _check_action_roundtime(self.player):
            return
        # --- END NEW ---

        if not self.args:
            self.player.send_message("Climb what? (e.g., CLIMB ROPE or CLIMB WELL)")
            return

        target_name = " ".join(self.args).lower() # --- FIX: Allow multi-word targets like "stone well" ---
        
        # 1. Find the object
        climbable_object = None
        for obj in self.room.objects:
            if "CLIMB" in obj.get("verbs", []):
                if (target_name == obj.get("name", "").lower() or
                    target_name in obj.get("keywords", [])):
                    climbable_object = obj
                    break

        if not climbable_object:
            self.player.send_message(f"You cannot climb the **{target_name}** here.")
            return

        target_room_id = climbable_object.get("target_room")

        if not target_room_id:
            self.player.send_message(f"The {target_name} leads nowhere right now.")
            return
            
        # --- NEW: Posture Check ---
        if self.player.posture != "standing":
            self.player.send_message("You must stand up first to climb.")
            return
        # --- END NEW ---
            
        # 2. Call the new Player method
        move_msg = f"You grasp the {target_name} and begin to climb...\nAfter a few moments, you arrive."
        self.player.move_to_room(target_room_id, move_msg)
        
        # 3. Set Roundtime
        _set_action_roundtime(self.player, 5.0) # 5s RT for climbing

# --- Class from move.py ---
class Move(BaseVerb):
    """
    Handles all directional movement (n, s, go north) AND
    object-based movement (go door).
    """
    
    def execute(self):
        # --- NEW: RT Check ---
        if _check_action_roundtime(self.player):
            return
        # --- END NEW ---

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
            
            # --- NEW: Posture Check ---
            current_posture = self.player.posture
            move_msg = ""
            rt = 0.0
            
            if current_posture == "standing":
                move_msg = f"You move {normalized_direction}..."
                rt = 3.0 # 3s RT for walking
            elif current_posture == "prone":
                move_msg = f"You crawl {normalized_direction}..."
                rt = 8.0 # 8s RT for crawling
            else: # sitting or kneeling
                self.player.send_message("You must stand up first.")
                return
            # --- END NEW ---
            
            self.player.move_to_room(target_room_id, move_msg)
            _set_action_roundtime(self.player, rt)
            return

        # --- CHECK 2: Is it an object you can 'enter'? ---
        # (This handles 'go door', 'move door')
        # --- FIX: Check keywords as well ---
        enterable_object = None
        for obj in self.room.objects:
             if "ENTER" in obj.get("verbs", []):
                if (target_name == obj.get("name", "").lower() or
                    target_name in obj.get("keywords", [])):
                    enterable_object = obj
                    break
                                 
        if enterable_object:
            # --- Found an enterable object ---
            # We can just create an instance of the Enter verb and run it
            # No import needed, class is in the same file!
            # --- FIX: Pass the *actual target name* to the Enter verb ---
            enter_verb = Enter(self.world, self.player, self.room, enterable_object['name'].lower().split())
            enter_verb.execute() # This will handle its own combat/posture check
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
        # --- NEW: RT Check ---
        if _check_action_roundtime(self.player):
            return
        # --- END NEW ---
        
        if not self.args:
            # --- CHECK 1: Handle 'exit' or 'out' (no args) ---
            # Try to find the special "out" exit
            target_room_id = self.room.exits.get("out")

            if target_room_id:
                # --- Found the "out" exit ---
                # --- NEW: Posture Check ---
                current_posture = self.player.posture
                move_msg = ""
                rt = 0.0
                
                if current_posture == "standing":
                    move_msg = "You head out..."
                    rt = 3.0
                elif current_posture == "prone":
                    move_msg = "You crawl out..."
                    rt = 8.0
                else: # sitting or kneeling
                    self.player.send_message("You must stand up first.")
                    return
                # --- END NEW ---

                self.player.move_to_room(target_room_id, move_msg)
                _set_action_roundtime(self.player, rt)
                return
            else:
                # --- No "out" exit, try to "enter" the most obvious exit object ---
                # --- FIX: Find a default "door" or "out" object ---
                default_exit_obj = None
                for obj in self.room.objects:
                    if "ENTER" in obj.get("verbs", []):
                        if "door" in obj.get("keywords", []) or "out" in obj.get("keywords", []):
                            default_exit_obj = obj
                            break
                
                if default_exit_obj:
                    obj_name_args = default_exit_obj['name'].lower().split()
                    enter_verb = Enter(self.world, self.player, self.room, obj_name_args)
                    enter_verb.execute()
                else:
                    self.player.send_message("You can't seem to find an exit.")
                return

        else:
            # --- CHECK 2: Handle 'exit <object>' (e.g., "exit door") ---
            # This is the same as "enter <object>"
            enter_verb = Enter(self.world, self.player, self.room, self.args)
            enter_verb.execute() # This will handle its own combat check
            return