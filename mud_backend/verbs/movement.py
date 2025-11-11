# mud_backend/verbs/movement.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.command_executor import DIRECTION_MAP
# --- NEW: Import random for climb roll ---
import random
# --- END NEW ---
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
import time


# ---
# --- THIS IS THE FIX ---
# ---
def _check_toll_gate(player, target_room_id: str) -> bool:
    """
    A helper function to check for special movement rules, like tolls.
    Returns True if movement is BLOCKED, False otherwise.
    """
    
    # ---
    # --- MODIFIED: Changed player.room.room_id to player.current_room_id
    # ---
    # The Player object has 'current_room_id' (a string), not 'room' (an object)
    if player.current_room_id == "north_gate_outside" and target_room_id == "north_gate_inside":
    # --- END MODIFIED ---
        
        # Check if player has the 'gate_pass' item (example)
        if "gate_pass" not in player.inventory:
            player.send_message("The guard blocks your way. 'You need a pass to enter the city.'")
            return True # Block movement
            
    return False # Allow movement
# ---
# --- END FIX
# ---


# --- Class from enter.py ---
class Enter(BaseVerb):
    """Handles the 'enter' command to move through doors, portals, etc."""
    
    def execute(self):
        if _check_action_roundtime(self.player, action_type="move"):
            return

        if not self.args:
            self.player.send_message("Enter what?")
            return

        target_name = " ".join(self.args).lower()
        
        enterable_object = next((obj for obj in self.room.objects 
                                 if obj['name'].lower() == target_name and "ENTER" in obj.get("verbs", [])), None)

        if not enterable_object:
            self.player.send_message(f"You cannot enter the **{target_name}**.")
            return

        target_room_id = enterable_object.get("target_room")

        if not target_room_id:
            self.player.send_message(f"The {target_name} leads nowhere right now.")
            return
            
        current_posture = self.player.posture
        
        # ---
        # --- MODIFIED: Variable RT for Enter
        # ---
        rt = 0.0 # Default to 0
        move_msg = ""
        
        # Check keywords for "door" or "gate"
        obj_keywords = enterable_object.get("keywords", [])
        is_door_or_gate = "door" in obj_keywords or "gate" in obj_keywords
        
        if current_posture == "standing":
            move_msg = f"You enter the {target_name}..."
            # Only apply RT if it's NOT a door or gate
            if not is_door_or_gate:
                rt = 3.0
        elif current_posture == "prone":
            move_msg = f"You crawl through the {target_name}..."
            if not is_door_or_gate:
                rt = 8.0
        else: # sitting or kneeling
            self.player.send_message("You must stand up first.")
            return
        # --- END MODIFIED ---

        # --- Check for toll gates before moving ---
        if _check_toll_gate(self.player, target_room_id):
            return # Movement is blocked

        self.player.move_to_room(target_room_id, move_msg)
        
        # --- MODIFIED: Only set RT if it's greater than 0 ---
        if rt > 0:
            _set_action_roundtime(self.player, rt)


# --- Class from climb.py ---
class Climb(BaseVerb):
    """Handles the 'climb' command to move between connected objects (like wells/ropes)."""
    
    def execute(self):
        if _check_action_roundtime(self.player, action_type="move"):
            return

        if not self.args:
            self.player.send_message("Climb what? (e.g., CLIMB ROPE or CLIMB WELL)")
            return

        target_name = " ".join(self.args).lower() 
        
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
            
        if self.player.posture != "standing":
            self.player.send_message("You must stand up first to climb.")
            return
            
        # ---
        # --- MODIFIED: Variable RT for Climb
        # ---
        climbing_skill = self.player.skills.get("climbing", 0)
        dc = climbable_object.get("climb_dc", 20) # Default DC is 20
        
        roll = random.randint(1, 100) + climbing_skill
        success_margin = roll - dc
        
        rt = 3.0 # Default RT
        
        if success_margin < 0: # Failure
            # Takes longer if you fail the roll
            rt = max(3.0, 10.0 - (climbing_skill / 10.0))
            move_msg = f"You struggle with the {target_name} but eventually make it..."
        else: # Success
            # Faster if you succeed
            rt = max(1.0, 5.0 - (success_margin / 20.0))
            move_msg = f"You grasp the {target_name} and begin to climb...\nAfter a few moments, you arrive."
        # --- END MODIFIED ---
            
        # --- Check for toll gates before moving ---
        if _check_toll_gate(self.player, target_room_id):
            return # Movement is blocked
            
        self.player.move_to_room(target_room_id, move_msg)
        
        # Set variable roundtime
        _set_action_roundtime(self.player, rt)

# --- Class from move.py ---
class Move(BaseVerb):
    """
    Handles all directional movement (n, s, go north) AND
    object-based movement (go door).
    """
    
    def execute(self):
        if _check_action_roundtime(self.player, action_type="move"):
            return

        if not self.args:
            self.player.send_message("Move where? (e.g., NORTH, SOUTH, E, W, etc.)")
            return

        target_name = " ".join(self.args).lower()
        
        normalized_direction = DIRECTION_MAP.get(target_name, target_name)
        
        target_room_id = self.room.exits.get(normalized_direction)
        
        if target_room_id:
            # ---
            # --- MODIFIED: Cardinal Movement RT
            # ---
            current_posture = self.player.posture
            move_msg = ""
            rt = 0.0 # <-- RT is now 0 for directional move
            
            if current_posture == "standing":
                move_msg = f"You move {normalized_direction}..."
                # rt = 3.0 # <-- Original
            elif current_posture == "prone":
                move_msg = f"You crawl {normalized_direction}..."
                # rt = 8.0 # <-- Original
            else: # sitting or kneeling
                self.player.send_message("You must stand up first.")
                return
            # --- END MODIFIED ---
            
            # --- Check for toll gates before moving ---
            if _check_toll_gate(self.player, target_room_id):
                return # Movement is blocked
            
            self.player.move_to_room(target_room_id, move_msg)
            
            # --- MODIFIED: Only set RT if it's greater than 0 ---
            if rt > 0:
                _set_action_roundtime(self.player, rt)
            return

        # --- CHECK 2: Is it an object you can 'enter'? ---
        enterable_object = None
        for obj in self.room.objects:
             if "ENTER" in obj.get("verbs", []):
                if (target_name == obj.get("name", "").lower() or
                    target_name in obj.get("keywords", [])):
                    enterable_object = obj
                    break
                                 
        if enterable_object:
            # Found an enterable object, run the Enter verb
            enter_verb = Enter(self.world, self.player, self.room, enterable_object['name'].lower().split())
            enter_verb.execute() # This will handle its own RT checks
            return

        self.player.send_message("You cannot go that way.")

# --- Class from exit.py ---
class Exit(BaseVerb):
    """
    Handles the 'exit' and 'out' commands.
    """
    
    def execute(self):
        if _check_action_roundtime(self.player, action_type="move"):
            return
        
        if not self.args:
            # --- CHECK 1: Handle 'exit' or 'out' (no args) ---
            target_room_id = self.room.exits.get("out")

            if target_room_id:
                # ---
                # --- MODIFIED: 'out' exit RT
                # ---
                current_posture = self.player.posture
                move_msg = ""
                rt = 0.0 # <-- RT is now 0 for 'out'
                
                if current_posture == "standing":
                    move_msg = "You head out..."
                    # rt = 3.0 # <-- Original
                elif current_posture == "prone":
                    move_msg = "You crawl out..."
                    # rt = 8.0 # <-- Original
                else: # sitting or kneeling
                    self.player.send_message("You must stand up first.")
                    return
                # --- END MODIFIED ---

                # --- Check for toll gates before moving ---
                if _check_toll_gate(self.player, target_room_id):
                    return # Movement is blocked

                self.player.move_to_room(target_room_id, move_msg)
                
                # --- MODIFIED: Only set RT if it's greater than 0 ---
                if rt > 0:
                    _set_action_roundtime(self.player, rt)
                return
            else:
                # --- No "out" exit, try to "enter" the most obvious exit object ---
                default_exit_obj = None
                for obj in self.room.objects:
                    if "ENTER" in obj.get("verbs", []):
                        if "door" in obj.get("keywords", []) or "out" in obj.get("keywords", []):
                            default_exit_obj = obj
                            break
                
                if default_exit_obj:
                    obj_name_args = default_exit_obj['name'].lower().split()
                    enter_verb = Enter(self.world, self.player, self.room, obj_name_args)
                    enter_verb.execute() # This will handle its own RT checks
                else:
                    self.player.send_message("You can't seem to find an exit.")
                return

        else:
            # --- CHECK 2: Handle 'exit <object>' (e.g., "exit door") ---
            # This is the same as "enter <object>"
            enter_verb = Enter(self.world, self.player, self.room, self.args)
            enter_verb.execute() 
            return