# mud_backend/verbs/movement.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.command_executor import DIRECTION_MAP
import random
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
import time
# --- NEW: Import faction handler ---
from mud_backend.core import faction_handler
# --- END NEW ---


# ---
# --- NEW: Toll Gate Helper Function
# ---
def _check_toll_gate(player, target_room_id: str) -> bool:
    """
    Checks for the North Gate toll.
    Returns True if the player can pass, False if they are blocked.
    """
    # Check if this is the specific gate we care about
    if player.room.room_id == "north_gate_outside" and target_room_id == "north_gate_inside":
        
        # Check player's faction
        player_faction_con = faction_handler.get_player_faction_con(player, "Townsfolk")
        
        # --- Check 1: Faction is high enough ---
        if player_faction_con in ["Amiable", "Kindly", "Warmly", "Ally"]:
            player.send_message("The guardsman recognizes you and waves you through the gate.")
            return True # Allow passage
            
        # --- Check 2: Faction is too low, check for toll ---
        else:
            toll = 10 # Define the toll amount
            if player.wealth.get("silvers", 0) >= toll:
                player.wealth["silvers"] -= toll
                player.send_message(f"You pay the {toll} silver toll to the guardsman and enter the gate.")
                return True # Allow passage
            else:
                player.send_message(f"The guardsman blocks your path. 'You'll need to pay the {toll} silver toll to enter, citizen.'")
                return False # Block passage
                
    # If it's not the toll gate, always allow passage
    return True
# ---
# --- END NEW HELPER
# ---


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
            # --- MODIFIED: Check for gate alias ---
            if target_name in ["gate", "wooden gate", "north gate", "south gate"]:
                 # Try to find *any* object with "gate" in keywords
                 gate_obj = next((obj for obj in self.room.objects if "gate" in obj.get("keywords", []) and "ENTER" in obj.get("verbs", [])), None)
                 if gate_obj:
                     enterable_object = gate_obj
                 else:
                    self.player.send_message(f"You cannot enter the **{target_name}**.")
                    return
            else:
                self.player.send_message(f"You cannot enter the **{target_name}**.")
                return
            # --- END MODIFIED ---

        target_room_id = enterable_object.get("target_room")

        if not target_room_id:
            self.player.send_message(f"The {target_name} leads nowhere right now.")
            return
            
        # ---
        # --- NEW: Toll Gate Check
        # ---
        if not _check_toll_gate(self.player, target_room_id):
            return # Player was blocked by the toll
        # --- END NEW ---
            
        current_posture = self.player.posture
        
        rt = 0.0 
        move_msg = ""
        
        obj_keywords = enterable_object.get("keywords", [])
        is_door_or_gate = "door" in obj_keywords or "gate" in obj_keywords
        
        if current_posture == "standing":
            move_msg = f"You enter the {enterable_object.get('name', target_name)}..."
            if not is_door_or_gate:
                rt = 3.0
        elif current_posture == "prone":
            move_msg = f"You crawl through the {enterable_object.get('name', target_name)}..."
            if not is_door_or_gate:
                rt = 8.0
        else: 
            self.player.send_message("You must stand up first.")
            return

        self.player.move_to_room(target_room_id, move_msg)
        
        if rt > 0:
            _set_action_roundtime(self.player, rt)


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
            
        climbing_skill = self.player.skills.get("climbing", 0)
        dc = climbable_object.get("climb_dc", 20) 
        
        roll = random.randint(1, 100) + climbing_skill
        success_margin = roll - dc
        
        rt = 3.0 
        
        if success_margin < 0: 
            rt = max(3.0, 10.0 - (climbing_skill / 10.0))
            move_msg = f"You struggle with the {target_name} but eventually make it..."
        else: 
            rt = max(1.0, 5.0 - (success_margin / 20.0))
            move_msg = f"You grasp the {target_name} and begin to climb...\nAfter a few moments, you arrive."
            
        self.player.move_to_room(target_room_id, move_msg)
        _set_action_roundtime(self.player, rt)

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
            # --- NEW: Toll Gate Check
            # ---
            if not _check_toll_gate(self.player, target_room_id):
                return # Player was blocked by the toll
            # --- END NEW ---
            
            current_posture = self.player.posture
            move_msg = ""
            rt = 0.0 
            
            if current_posture == "standing":
                move_msg = f"You move {normalized_direction}..."
            elif current_posture == "prone":
                move_msg = f"You crawl {normalized_direction}..."
            else: 
                self.player.send_message("You must stand up first.")
                return
            
            self.player.move_to_room(target_room_id, move_msg)
            
            if rt > 0:
                _set_action_roundtime(self.player, rt)
            return

        # --- CHECK 2: Is it an object you can 'enter'? (e.g., "go gate") ---
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
            enter_verb.execute() 
            return

        self.player.send_message("You cannot go that way.")

class Exit(BaseVerb):
    """
    Handles the 'exit' and 'out' commands.
    """
    
    def execute(self):
        if _check_action_roundtime(self.player, action_type="move"):
            return
        
        if not self.args:
            target_room_id = self.room.exits.get("out")

            if target_room_id:
                # ---
                # --- NEW: Toll Gate Check
                # ---
                if not _check_toll_gate(self.player, target_room_id):
                    return # Player was blocked by the toll
                # --- END NEW ---

                current_posture = self.player.posture
                move_msg = ""
                rt = 0.0 
                
                if current_posture == "standing":
                    move_msg = "You head out..."
                elif current_posture == "prone":
                    move_msg = "You crawl out..."
                else: 
                    self.player.send_message("You must stand up first.")
                    return

                self.player.move_to_room(target_room_id, move_msg)
                
                if rt > 0:
                    _set_action_roundtime(self.player, rt)
                return
            else:
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
            # Handle 'exit <object>' (e.g., "exit door")
            enter_verb = Enter(self.world, self.player, self.room, self.args)
            enter_verb.execute() 
            return