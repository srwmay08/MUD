# mud_backend/verbs/movement.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.command_executor import DIRECTION_MAP
import random
# --- MODIFIED: Import _check_action_roundtime, _set_action_roundtime, time ---
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
import time
# --- END MODIFIED ---
# --- NEW: Import deque for pathfinding ---
from collections import deque
from typing import Optional, List, Dict, Set
# ---
# --- THIS IS THE FIX: Import the Room class
# ---
from mud_backend.core.game_objects import Room
# ---
# --- END FIX
# ---
# --- NEW: Add imports needed for background task ---
from mud_backend.core.room_handler import show_room_to_player
# ---
# --- THIS IS THE FIX: REMOVE join_room and leave_room (which were unused)
# ---
# from flask_socketio import join_room, leave_room # <-- REMOVED
# ---
# --- END FIX
# ---


# ---
# --- NEW: GOTO Target Map
# ---
# This maps a "goto" keyword to a room_id
GOTO_MAP = {
    "townhall": "town_hall",
    "hall": "town_hall",
    "clerk": "town_hall",
    "blacksmith": "armory_shop",
    "armory": "armory_shop",
    "armorer": "armory_shop",
    "furrier": "furrier_shop",
    "apothecary": "apothecary_shop",
    "temple": "temple_of_light",
    "priest": "temple_of_light",
    "elementalist": "elementalist_study",
    "study": "elementalist_study",
    "barracks": "barracks",
    "captain": "barracks",
    "library": "library_archives",
    "archives": "library_archives",
    "librarian": "library_archives",
    "theatre": "theatre",
    "bank": "bank_lobby",
    "banker": "bank_lobby",
    "inn": "inn_front_desk",
    "innkeeper": "inn_front_desk"
}

# ---
# --- THIS IS THE FIX
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

# ---
# --- NEW: Pathfinding Function (BFS)
# ---
def _find_path(world, start_room_id: str, end_room_id: str) -> Optional[List[str]]:
    """
    Finds the shortest path from start to end room using BFS.
    Returns a list of directions (e.g., ["north", "east"]) or None.
    """
    queue = deque([(start_room_id, [])])  # (current_room_id, path_list)
    visited: Set[str] = {start_room_id}

    while queue:
        current_room_id, path = queue.popleft()

        if current_room_id == end_room_id:
            return path  # Found the destination

        room = world.get_room(current_room_id)
        if not room:
            continue

        exits = room.get("exits", {})
        
        # ---
        # --- THIS IS THE FIX
        # ---
        # Also check 'objects' for 'ENTER' verbs
        # This allows pathing through doors, portals, etc.
        objects = room.get("objects", [])
        for obj in objects:
            if "ENTER" in obj.get("verbs", []) or "CLIMB" in obj.get("verbs", []):
                target_room = obj.get("target_room")
                if target_room:
                    # --- NEW LOGIC ---
                    # Add all keywords and the name as potential paths
                    obj_keywords = obj.get("keywords", [])
                    for keyword in obj_keywords:
                        if keyword not in exits:
                            exits[keyword] = target_room
                    
                    # Add the object's name as well, just in case
                    obj_name = obj.get("name", "").lower()
                    if obj_name and obj_name not in exits:
                         exits[obj_name] = target_room
                    # --- END NEW LOGIC ---
        # ---
        # --- END FIX
        # ---

        for direction, next_room_id in exits.items():
            if next_room_id not in visited:
                visited.add(next_room_id)
                new_path = path + [direction]
                queue.append((next_room_id, new_path))

    return None  # No path found
# ---
# --- END NEW FUNCTION
# ---

# ---
# --- NEW: GOTO Background Task
# ---
def _execute_goto_path(world, player_id: str, path: List[str], final_destination_room_id: str, sid: str):
    """
    A background task to move the player step-by-step.
    This runs in a separate thread.
    """
    
    player_obj = world.get_player_obj(player_id)
    if not player_obj:
        return # Player logged out

    # --- START FIX ---
    if not player_obj.is_goto_active:
        # GOTO was canceled before it even started
        return
    # --- END FIX ---

    for move_direction in path:
        # --- START FIX ---
        # --- Re-fetch player and check for cancellation ---
        player_obj = world.get_player_obj(player_id) 
        if not player_obj: return # Player logged out
        
        if not player_obj.is_goto_active:
            player_obj.send_message("You stop moving.")
            world.socketio.emit('command_response', 
                                 {'messages': player_obj.messages, 'vitals': player_obj.get_vitals()}, 
                                 to=sid)
            return # GOTO was canceled
        # --- END FIX ---

        # --- Wait for any existing RT to clear ---
        while True:
            rt_data = world.get_combat_state(player_id)
            if rt_data:
                next_action = rt_data.get("next_action_time", 0)
                if time.time() < next_action:
                    # We are in RT, sleep for a bit and check again
                    world.socketio.sleep(0.5) 
                else:
                    # RT is clear, clear the state
                    world.remove_combat_state(player_id)
                    break
            else:
                # No RT data
                break
        
        # --- Check if player is still connected ---
        # --- START FIX ---
        # --- Re-check after RT, just in case ---
        player_obj = world.get_player_obj(player_id)
        if not player_obj: return
        if not player_obj.is_goto_active:
            player_obj.send_message("You stop moving.")
            world.socketio.emit('command_response', 
                                 {'messages': player_obj.messages, 'vitals': player_obj.get_vitals()}, 
                                 to=sid)
            return
        # --- END FIX ---
            
        # --- Check for combat ---
        player_state = world.get_combat_state(player_id)
        if player_state and player_state.get("state_type") == "combat":
            player_obj.send_message("You are attacked and your movement stops!")
            world.socketio.emit('command_response', 
                                 {'messages': player_obj.messages, 'vitals': player_obj.get_vitals()}, 
                                 to=sid)
            player_obj.is_goto_active = False # <-- ADDED
            return

        current_room_data = world.get_room(player_obj.current_room_id)
        if not current_room_data:
            player_obj.send_message("Your path seems to have vanished. Stopping.")
            world.socketio.emit('command_response', 
                                     {'messages': player_obj.messages, 'vitals': player_obj.get_vitals()}, 
                                     to=sid)
            player_obj.is_goto_active = False # <-- ADDED
            return
        
        current_room_obj = Room(
            current_room_data.get("room_id", "void"),
            current_room_data.get("name", "The Void"),
            current_room_data.get("description", "..."),
            db_data=current_room_data
        )

        target_room_id_step = current_room_data.get("exits", {}).get(move_direction)
        move_msg = f"You move {move_direction}..."
        
        if not target_room_id_step:
            current_room_obj.objects = current_room_data.get("objects", [])
            enter_obj = next((obj for obj in current_room_obj.objects 
                              if ((move_direction in obj.get("keywords", []) or 
                                   move_direction == obj.get("name", "").lower()) and # <-- Check name too
                                  ("ENTER" in obj.get("verbs", []) or "CLIMB" in obj.get("verbs", [])))
                             ), None)
                             
            if enter_obj:
                target_room_id_step = enter_obj.get("target_room")
                move_msg = f"You enter the {enter_obj.get('name')}..."
            else:
                player_obj.send_message(f"Your path is blocked at '{move_direction}'. Stopping.")
                world.socketio.emit('command_response', 
                                         {'messages': player_obj.messages, 'vitals': player_obj.get_vitals()}, 
                                         to=sid)
                player_obj.is_goto_active = False # <-- ADDED
                return
        
        if _check_toll_gate(player_obj, target_room_id_step):
            player_obj.send_message("Your movement is blocked. Stopping.")
            world.socketio.emit('command_response', 
                                     {'messages': player_obj.messages, 'vitals': player_obj.get_vitals()}, 
                                     to=sid)
            player_obj.is_goto_active = False # <-- ADDED
            return
        
        # ---
        # --- THIS IS THE FIX: Tutorial Hook for GOTO
        # ---
        current_room_id = player_obj.current_room_id
        
        player_obj.move_to_room(target_room_id_step, move_msg)
        
        _set_action_roundtime(player_obj, 3.0) 
        
        old_room_id = current_room_id
        new_room_id = target_room_id_step
        
        # ---
        # --- THIS IS THE FIX: Tutorial Hook for GIVE CLERK
        # ---
        if (new_room_id == "town_hall" and
            "innkeeper_quest_1" in player_obj.active_quests and # This check is flawed, should check *item*
            "intro_give_clerk" not in player_obj.completed_quests):
            
             # Check if player has the payment
            has_payment = False
            if "lodging_tax_payment" in player_obj.inventory:
                has_payment = True
            for slot in ["mainhand", "offhand"]:
                if player_obj.worn_items.get(slot) == "lodging_tax_payment":
                    has_payment = True
                    break
            
            if has_payment:
                player_obj.send_message(
                    "\nYou have arrived at the Town Hall. You should "
                    "<span class='keyword' data-command='give clerk payment'>GIVE</span> the <span class='keyword' data-command='look at payment'>payment</span> to the <span class='keyword' data-command='look at clerk'>clerk</span>."
                )
                player_obj.completed_quests.append("intro_give_clerk")
        # ---
        # --- END FIX
        # ---

        if old_room_id and new_room_id != old_room_id:
            world.socketio.server.leave_room(sid, old_room_id)
            leaves_message = f'<span class="keyword" data-name="{player_obj.name}" data-verbs="look">{player_obj.name}</span> leaves.'
            world.socketio.emit("message", leaves_message, to=old_room_id)
            
            world.socketio.server.enter_room(sid, new_room_id)
            arrives_message = f'<span class="keyword" data-name="{player_obj.name}" data-verbs="look">{player_obj.name}</span> arrives.'
            world.socketio.emit("message", arrives_message, to=new_room_id, skip_sid=sid)
        
        world.socketio.emit('command_response', 
                                 {'messages': player_obj.messages, 'vitals': player_obj.get_vitals()}, 
                                 to=sid)
        
        world.socketio.sleep(3.0) 

    # --- Loop is finished ---
    player_obj = world.get_player_obj(player_id)
    if player_obj: # <-- ADDED CHECK
        player_obj.is_goto_active = False # <-- CLEAR FLAG
        if player_obj.current_room_id == final_destination_room_id:
            # Clear final RT
            world.remove_combat_state(player_id)
            player_obj.send_message("You have arrived.")
            world.socketio.emit('command_response', 
                                     {'messages': player_obj.messages, 'vitals': player_obj.get_vitals()}, 
                                     to=sid)
# ---
# --- END NEW GOTO TASK
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
            # --- NEW: Check keywords as a fallback ---
            enterable_object = next((obj for obj in self.room.objects 
                                     if target_name in obj.get("keywords", []) and "ENTER" in obj.get("verbs", [])), None)
            if not enterable_object:
                self.player.send_message(f"You cannot enter the **{target_name}**.")
                return
            # --- END NEW ---

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
            move_msg = f"You enter the {enterable_object.get('name', target_name)}..."
            # Only apply RT if it's NOT a door or gate
            if not is_door_or_gate:
                rt = 3.0
        elif current_posture == "prone":
            move_msg = f"You crawl through the {enterable_object.get('name', target_name)}..."
            if not is_door_or_gate:
                rt = 8.0
        else: # sitting or kneeling
            self.player.send_message("You must stand up first.")
            return
        # --- END MODIFIED ---

        # --- Check for toll gates before moving ---
        if _check_toll_gate(self.player, target_room_id):
            return # Movement is blocked
            
        # ---
        # --- THIS IS THE FIX: Tutorial Hook for GIVE CLERK
        # ---
        current_room_id = self.room.room_id
        self.player.move_to_room(target_room_id, move_msg)
        
        if (target_room_id == "town_hall" and
            "intro_give_clerk" not in self.player.completed_quests):
            
             # Check if player has the payment
            has_payment = False
            if "lodging_tax_payment" in self.player.inventory:
                has_payment = True
            for slot in ["mainhand", "offhand"]:
                if self.player.worn_items.get(slot) == "lodging_tax_payment":
                    has_payment = True
                    break
            
            if has_payment:
                self.player.send_message(
                    "\nYou have arrived at the Town Hall. You should "
                    "<span class='keyword' data-command='give clerk payment'>GIVE</span> the <span class='keyword' data-command='look at payment'>payment</span> to the <span class='keyword' data-command='look at clerk'>clerk</span>."
                )
                self.player.completed_quests.append("intro_give_clerk")
        # ---
        # --- END FIX
        # ---
        
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
            
            # ---
            # --- THIS IS THE FIX: Tutorial Hook for GIVE CLERK
            # ---
            self.player.move_to_room(target_room_id, move_msg)
            
            if (target_room_id == "town_hall" and
                "intro_give_clerk" not in self.player.completed_quests):
                
                 # Check if player has the payment
                has_payment = False
                if "lodging_tax_payment" in self.player.inventory:
                    has_payment = True
                for slot in ["mainhand", "offhand"]:
                    if self.player.worn_items.get(slot) == "lodging_tax_payment":
                        has_payment = True
                        break
                
                if has_payment:
                    self.player.send_message(
                        "\nYou have arrived at the Town Hall. You should "
                        "<span class='keyword' data-command='give clerk payment'>GIVE</span> the <span class='keyword' data-command='look at payment'>payment</span> to the <span class='keyword' data-command='look at clerk'>clerk</span>."
                    )
                    self.player.completed_quests.append("intro_give_clerk")
            # ---
            # --- END FIX
            # ---
            
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

                # ---
                # --- THIS IS THE FIX: Tutorial Hook for TALK
                # ---
                current_room_id = self.room.room_id
                # Call move_to_room *first* so the player.messages list is cleared
                self.player.move_to_room(target_room_id, move_msg)
                
                if (current_room_id == "inn_room" and
                    target_room_id == "inn_front_desk" and
                    "intro_leave_room_tasks" in self.player.completed_quests and
                    "intro_talk_to_innkeeper" not in self.player.completed_quests):
                    
                    self.player.send_message(
                        "\nYou are now in the inn's main lobby. You should <span class='keyword' data-command='talk to innkeeper'>TALK</span> "
                        "to the innkeeper about your bill. <span class='keyword' data-command='help talk'>[Help: TALK]</span>"
                    )
                    self.player.completed_quests.append("intro_talk_to_innkeeper")
                # ---
                # --- END FIX
                # ---
                
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

# ---
# --- MODIFIED: GOTO VERB
# ---
class GOTO(BaseVerb):
    """
    Handles the 'goto' command for fast-travel to known locations.
    Finds the shortest path and executes each step, showing the room.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="move"):
            return
            
        if self.player.posture != "standing":
            self.player.send_message("You must be standing to do that.")
            return
            
        if not self.args:
            self.player.send_message("Where do you want to go? (e.g., GOTO TOWNHALL)")
            return
            
        target_name = " ".join(self.args).lower()
        
        target_room_id = GOTO_MAP.get(target_name)
        
        if not target_room_id:
            self.player.send_message(f"You don't know how to go to '{target_name}'.")
            return
            
        if self.player.current_room_id == target_room_id:
            self.player.send_message("You are already there!")
            return
            
        target_room_data = self.world.get_room(target_room_id)
        if not target_room_data:
            self.player.send_message("You can't go there. (Room does not exist)")
            return
            
        target_room_name = target_room_data.get("name", "your destination")
        
        path = _find_path(self.world, self.player.current_room_id, target_room_id)
        
        if not path:
            self.player.send_message(f"You can't seem to find a path to {target_room_name} from here.")
            return
            
        self.player.send_message(f"You begin moving towards {target_room_name}...")
        
        # ---
        # --- THIS IS THE FIX
        # ---
        player_id = self.player.name.lower()
        player_info = self.world.get_player_info(player_id)
        if not player_info:
            self.player.send_message("Error: Could not find your session.")
            return
        
        sid = player_info.get("sid")
        if not sid:
            self.player.send_message("Error: Could not find your connection.")
            return

        self.player.is_goto_active = True # <-- SET FLAG
            
        # Start the background task
        self.world.socketio.start_background_task(
            _execute_goto_path, 
            self.world,
            player_id,
            path, 
            target_room_id,
            sid
        )
        # ---
        # --- END FIX
        # ---
