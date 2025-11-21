# mud_backend/verbs/movement.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core.command_executor import DIRECTION_MAP
import random
# --- MODIFIED: Import _check_action_roundtime, _set_action_roundtime, time ---
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
import time
# --- END MODIFIED ---
# --- NEW: Import deque for pathfinding ---
from collections import deque
from typing import Optional, List, Dict, Set, TYPE_CHECKING
# ---
# --- THIS IS THE FIX: Import the Room class
# ---
from mud_backend.core.game_objects import Room
# ---
# --- END FIX
# ---
# --- MODIFIED: Add imports needed for background task ---
from mud_backend.core.room_handler import show_room_to_player, _get_map_data
# --- NEW: Import skill check ---
from mud_backend.core.skill_handler import attempt_skill_learning
# --- END NEW ---

if TYPE_CHECKING:
    from mud_backend.core.game_state import World
    from mud_backend.core.game_objects import Player



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

def _check_toll_gate(player, target_room_id: str) -> bool:
    """
    A helper function to check for special movement rules, like tolls.
    Returns True if movement is BLOCKED, False otherwise.
    """
    if player.current_room_id == "north_gate_outside" and target_room_id == "north_gate_inside":
        if "gate_pass" not in player.inventory:
            player.send_message("The guard blocks your way. 'You need a pass to enter the city.'")
            return True # Block movement
            
    return False # Allow movement

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

        exits = room.get("exits", {}).copy() # Use a copy
        
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
# --- MODIFIED: Group Movement Helper (Broadcast Fix)
# ---
def _handle_group_move(
    world: 'World', 
    leader_player: 'Player',
    original_room_id: str, 
    target_room_id: str,
    move_msg: str, # This is the LEADER's move message (e.g., "You move north...")
    move_verb: str, # This is the objective verb (e.g., "north", "enter", "climb")
    skill_dc: int = 0
):
    """
    Handles moving all group members who are with the leader.
    Checks for individual skill checks (climb, etc.) if a dc > 0 is provided.
    """
    group = world.get_group(leader_player.group_id)
    if not group or group["leader"] != leader_player.name.lower():
        return # Not in a group or not the leader

    leader_name = leader_player.name

    for member_key in group["members"]:
        if member_key == leader_name.lower():
            continue # Skip the leader
            
        member_info = world.get_player_info(member_key)
        if not member_info:
            continue # Follower isn't online
            
        member_obj = member_info.get("player_obj")
        sid = member_info.get("sid")
        
        # Check if member is online, has a session, and is in the leader's *original* room
        if member_obj and sid and member_obj.current_room_id == original_room_id:
            
            # --- Check if member is busy ---
            if _check_action_roundtime(member_obj, action_type="move"):
                member_obj.send_message(f"You are busy and cannot follow {leader_name}.")
                world.send_message_to_group(
                    group["id"], 
                    f"{member_obj.name} is busy and gets left behind.",
                    skip_player_key=member_key
                )
                continue # Skip this member

            member_can_move = True
            failure_message = ""

            # Re-check skill-based moves for each member
            if move_verb == "climb":
                # Using 'climbing' skill
                skill_rank = member_obj.skills.get("climbing", 0)
                roll = skill_rank + random.randint(1, 100)
                attempt_skill_learning(member_obj, "climbing")
                
                if roll < skill_dc:
                    member_can_move = False
                    failure_message = f"You try to follow {leader_name} but fail to climb!"
                
            elif move_verb == "swim":
                # Using 'swimming' skill
                skill_rank = member_obj.skills.get("swimming", 0)
                roll = skill_rank + random.randint(1, 100)
                attempt_skill_learning(member_obj, "swimming")
                
                if roll < skill_dc:
                    member_can_move = False
                    failure_message = f"You try to follow {leader_name} but fail to swim!"

            # If all checks pass, move the member
            if member_can_move:
                
                # ---
                # --- **** THIS IS THE FIX FOR FOLLOWERS ****
                # ---
                # Generate a follower-specific move message
                follower_move_msg = ""
                if move_verb == "enter":
                    follower_move_msg = f"You follow {leader_name} inside..."
                elif move_verb == "climb":
                    follower_move_msg = f"You follow {leader_name}, climbing..."
                elif move_verb == "out":
                    follower_move_msg = f"You follow {leader_name} out..."
                elif move_verb in DIRECTION_MAP.values() or move_verb in DIRECTION_MAP.keys():
                    # It's a direction
                    follower_move_msg = f"You follow {leader_name} {move_verb}..."
                else:
                    # Failsafe for things like 'goto' paths (e.g., 'door')
                    follower_move_msg = f"You follow {leader_name}..."

                member_obj.messages.clear()
                # 1. Move the player object using the *new* message
                member_obj.move_to_room(target_room_id, follower_move_msg) 
                
                # 1b. Get and show the new room to the follower
                new_room_data = world.get_room(target_room_id)
                new_room = Room(target_room_id, new_room_data.get("name", ""), new_room_data.get("description", ""), db_data=new_room_data)
                show_room_to_player(member_obj, new_room)
                # ---
                # --- **** END FIX ****
                # ---
                
                # 2. Leave old Socket.IO room
                world.socketio.server.leave_room(sid, original_room_id)
                
                # ---
                # --- **** THIS IS THE FIX FOR LEADER ****
                # ---
                # [NEW] Get leader's SID to skip them on the "leaves" broadcast
                leader_info = world.get_player_info(leader_name.lower())
                leader_sid = leader_info.get("sid") if leader_info else None
                sids_to_skip_for_leave = {sid}
                if leader_sid:
                    sids_to_skip_for_leave.add(leader_sid)

                leaves_message = f'<span class="keyword" data-name="{member_obj.name}" data-verbs="look">{member_obj.name}</span> leaves.'
                # 3. Broadcast leave message to old room (skip self AND LEADER)
                world.broadcast_to_room(original_room_id, leaves_message, "message", skip_sid=sids_to_skip_for_leave)
                # ---
                # --- **** END FIX ****
                # ---
                
                # 4. Join new Socket.IO room
                world.socketio.server.enter_room(sid, target_room_id)
                arrives_message = f'<span class="keyword" data-name="{member_obj.name}" data-verbs="look">{member_obj.name}</span> arrives.'
                # 5. Broadcast arrive message to new room (skip self)
                world.broadcast_to_room(target_room_id, arrives_message, "message", skip_sid=sid)

                # 6. Send the command_response to the follower's client
                vitals_data = member_obj.get_vitals()
                map_data = _get_map_data(member_obj, world)
                world.socketio.emit(
                    'command_response', 
                    {'messages': member_obj.messages, 'vitals': vitals_data, 'map_data': map_data}, 
                    to=sid
                )
            else:
                # Send failure to member and group
                if failure_message:
                    member_obj.send_message(failure_message)
                world.send_message_to_group(
                    group["id"], 
                    f"{member_obj.name} fails to {move_verb} and is left behind.", 
                    skip_player_key=member_key
                )
# ---
# --- END MODIFIED HELPER
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

    if not player_obj.is_goto_active:
        return # GOTO was canceled before it even started

    for move_direction in path:
        # --- Re-fetch player and check for cancellation ---
        player_obj = world.get_player_obj(player_id) 
        if not player_obj: return # Player logged out
        
        if not player_obj.is_goto_active:
            player_obj.send_message("You stop moving.")
            world.socketio.emit('command_response', 
                                 {'messages': player_obj.messages, 'vitals': player_obj.get_vitals(), 'map_data': _get_map_data(player_obj, world)}, 
                                 to=sid)
            return # GOTO was canceled

        # --- Wait for any existing RT to clear ---
        while True:
            rt_data = world.get_combat_state(player_id)
            if rt_data:
                next_action = rt_data.get("next_action_time", 0)
                if time.time() < next_action:
                    world.socketio.sleep(0.5) 
                else:
                    world.remove_combat_state(player_id)
                    break
            else:
                break
        
        # --- Re-check after RT ---
        player_obj = world.get_player_obj(player_id)
        if not player_obj: return
        if not player_obj.is_goto_active:
            player_obj.send_message("You stop moving.")
            world.socketio.emit('command_response', 
                                 {'messages': player_obj.messages, 'vitals': player_obj.get_vitals(), 'map_data': _get_map_data(player_obj, world)}, 
                                 to=sid)
            return
            
        # --- Check for combat ---
        player_state = world.get_combat_state(player_id)
        if player_state and player_state.get("state_type") == "combat":
            player_obj.send_message("You are attacked and your movement stops!")
            world.socketio.emit('command_response', 
                                 {'messages': player_obj.messages, 'vitals': player_obj.get_vitals(), 'map_data': _get_map_data(player_obj, world)}, 
                                 to=sid)
            player_obj.is_goto_active = False
            return

        original_room_id = player_obj.current_room_id
        current_room_data = world.get_room(original_room_id)
        if not current_room_data:
            player_obj.send_message("Your path seems to have vanished. Stopping.")
            world.socketio.emit('command_response', 
                                     {'messages': player_obj.messages, 'vitals': player_obj.get_vitals(), 'map_data': _get_map_data(player_obj, world)}, 
                                     to=sid)
            player_obj.is_goto_active = False
            return
        
        target_room_id_step = None
        move_msg = ""
        move_verb = move_direction # e.g., "north"
        skill_dc = 0
        
        # Is it a simple exit?
        if move_direction in current_room_data.get("exits", {}):
            target_room_id_step = current_room_data.get("exits", {}).get(move_direction)
            move_msg = f"You move {move_direction}..."
        else:
            # It must be an object
            enter_obj = next((obj for obj in current_room_data.get("objects", []) 
                              if ((move_direction in obj.get("keywords", []) or 
                                   move_direction == obj.get("name", "").lower()) and
                                  (obj.get("target_room")))
                             ), None)
            
            if enter_obj:
                target_room_id_step = enter_obj.get("target_room")
                if "CLIMB" in enter_obj.get("verbs", []):
                    move_verb = "climb"
                    skill_dc = 20 # TODO: Get DC from object
                    move_msg = f"You climb the {enter_obj.get('name')}..."
                else: # Default to ENTER
                    move_verb = "enter"
                    move_msg = f"You enter the {enter_obj.get('name')}..."
            else:
                player_obj.send_message(f"Your path is blocked at '{move_direction}'. Stopping.")
                world.socketio.emit('command_response', 
                                         {'messages': player_obj.messages, 'vitals': player_obj.get_vitals(), 'map_data': _get_map_data(player_obj, world)}, 
                                         to=sid)
                player_obj.is_goto_active = False
                return
        
        if _check_toll_gate(player_obj, target_room_id_step):
            player_obj.send_message("Your movement is blocked. Stopping.")
            world.socketio.emit('command_response', 
                                     {'messages': player_obj.messages, 'vitals': player_obj.get_vitals(), 'map_data': _get_map_data(player_obj, world)}, 
                                     to=sid)
            player_obj.is_goto_active = False
            return
        
        # ---
        # --- **** THIS IS THE FIX FOR GOTO LEADER ****
        # ---
        # Add group message *before* moving
        group = world.get_group(player_obj.group_id)
        is_leader = group and group["leader"] == player_obj.name.lower() and len(group["members"]) > 1
        if is_leader:
            move_msg = f"You move {move_direction}... and your group follows."
        # ---
        # --- **** END FIX ****
        # ---

        # --- Leader move ---
        player_obj.messages.clear()
        player_obj.move_to_room(target_room_id_step, move_msg)
        
        # ---
        # --- **** THIS IS THE FIX FOR GOTO LEADER (Followers move first) ****
        # ---
        _handle_group_move(
            world, player_obj, original_room_id, target_room_id_step,
            move_msg, move_verb, skill_dc
        )
        
        # Get and show the new room to the leader
        new_room_data = world.get_room(target_room_id_step)
        new_room = Room(target_room_id_step, new_room_data.get("name", ""), new_room_data.get("description", ""), db_data=new_room_data)
        show_room_to_player(player_obj, new_room)
        # ---
        # --- **** END FIX ****
        # ---
        
        # ---
        # --- THIS IS THE FIX: Tutorial Hook for GIVE CLERK
        # ---
        if (target_room_id_step == "town_hall" and
            "intro_give_clerk" not in player_obj.completed_quests):
            
            has_payment = "lodging_tax_payment" in player_obj.inventory or \
                          player_obj.worn_items.get("mainhand") == "lodging_tax_payment" or \
                          player_obj.worn_items.get("offhand") == "lodging_tax_payment"
            
            if has_payment:
                player_obj.send_message(
                    "\nYou have arrived at the Town Hall. You should "
                    "<span class='keyword' data-command='give clerk payment'>GIVE</span> the <span class='keyword' data-command='look at payment'>payment</span> to the <span class='keyword' data-command='look at clerk'>clerk</span>."
                )
                player_obj.completed_quests.append("intro_give_clerk")
        # ---
        # --- END FIX
        # ---

        # --- Group move (in-task) ---
        # --- (MOVED UP) ---
        
        _set_action_roundtime(player_obj, 3.0) 
        
        # --- Handle SocketIO room changes ---
        if original_room_id and target_room_id_step != original_room_id:
            world.socketio.server.leave_room(sid, original_room_id)
            leaves_message = f'<span class="keyword" data-name="{player_obj.name}" data-verbs="look">{player_obj.name}</span> leaves.'
            
            # ---
            # --- **** THIS IS THE GOTO/LEADER LEAVES FIX ****
            # ---
            sids_to_skip_leave = {sid}
            if group and is_leader:
                 for member_key in group["members"]:
                    if member_key == player_id: continue
                    member_info = world.get_player_info(member_key)
                    if member_info and member_info.get("current_room_id") == original_room_id:
                        member_sid = member_info.get("sid")
                        if member_sid:
                            sids_to_skip_leave.add(member_sid)
            world.broadcast_to_room(original_room_id, leaves_message, "message", skip_sid=sids_to_skip_leave)
            # ---
            # --- **** END FIX ****
            # ---
            
            world.socketio.server.enter_room(sid, target_room_id_step)
            arrives_message = f'<span class="keyword" data-name="{player_obj.name}" data-verbs="look">{player_obj.name}</span> arrives.'
            
            # ---
            # --- **** THIS IS THE GOTO/LEADER ARRIVES FIX ****
            # ---
            sids_to_skip_arrive = {sid}
            if group and is_leader:
                 for member_key in group["members"]:
                    if member_key == player_id: continue
                    member_info = world.get_player_info(member_key)
                    if member_info and member_info.get("current_room_id") == target_room_id_step:
                        member_sid = member_info.get("sid")
                        if member_sid:
                            sids_to_skip_arrive.add(member_sid)
            
            world.broadcast_to_room(target_room_id_step, arrives_message, "message", skip_sid=sids_to_skip_arrive)
            # ---
            # --- **** END FIX ****
            # ---
        
        world.socketio.emit('command_response', 
                                 {'messages': player_obj.messages, 'vitals': player_obj.get_vitals(), 'map_data': _get_map_data(player_obj, world)}, 
                                 to=sid)
        
        world.socketio.sleep(3.0) 

    # --- Loop finished ---
    player_obj = world.get_player_obj(player_id)
    if player_obj: 
        player_obj.is_goto_active = False 
        if player_obj.current_room_id == final_destination_room_id:
            world.remove_combat_state(player_id) # Clear final RT
            player_obj.send_message("You have arrived.")
            world.socketio.emit('command_response', 
                                     {'messages': player_obj.messages, 'vitals': player_obj.get_vitals(), 'map_data': _get_map_data(player_obj, world)}, 
                                     to=sid)


@VerbRegistry.register(["move", "go", "n", "north", "s", "south", "e", "east", "w", "west", "ne", "northeast", "nw", "northwest", "se", "southeast", "sw", "southwest"])
@VerbRegistry.register(["enter"]) 
@VerbRegistry.register(["climb"]) 
@VerbRegistry.register(["exit", "out"]) 
@VerbRegistry.register(["goto"])

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
                                 if (obj['name'].lower() == target_name or target_name in obj.get("keywords", []))
                                 and "ENTER" in obj.get("verbs", [])), None)

        if not enterable_object:
            self.player.send_message(f"You cannot enter the **{target_name}**.")
            return

        target_room_id = enterable_object.get("target_room")

        if not target_room_id:
            self.player.send_message(f"The {target_name} leads nowhere right now.")
            return
        
        if target_room_id == "inn_room":
            self.player.send_message("The door to your old room is locked. You should <span class='keyword' data-command='talk to innkeeper'>TALK TO THE INNKEEPER</span> if you wish to check in for training.")
            return
            
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
        else: # sitting or kneeling
            self.player.send_message("You must stand up first.")
            return

        if _check_toll_gate(self.player, target_room_id):
            return
        
        # ---
        # --- **** THIS IS THE FIX FOR LEADER ****
        # ---
        group = self.world.get_group(self.player.group_id)
        is_leader = group and group["leader"] == self.player.name.lower() and len(group["members"]) > 1
        if is_leader:
            move_msg = f"You enter the {enterable_object.get('name', target_name)}... and your group follows."
        # ---
        # --- **** END FIX ****
        # ---
            
        original_room_id = self.room.room_id # --- Store for group move
        self.player.move_to_room(target_room_id, move_msg)
        
        # ---
        # --- **** THIS IS THE FIX FOR LOGIC ORDER ****
        # ---
        # 1. Handle group move *before* showing room
        _handle_group_move(
            self.world, self.player, original_room_id, target_room_id,
            move_msg, "enter", skill_dc=0
        )

        # 2. Now get new room data and show it
        new_room_data = self.world.get_room(target_room_id)
        new_room = Room(target_room_id, new_room_data.get("name", ""), new_room_data.get("description", ""), db_data=new_room_data)
        show_room_to_player(self.player, new_room)
        # ---
        # --- **** END FIX ****
        # ---
        
        # --- Tutorial Hook ---
        if (target_room_id == "town_hall" and "intro_give_clerk" not in self.player.completed_quests):
            has_payment = "lodging_tax_payment" in self.player.inventory or \
                          self.player.worn_items.get("mainhand") == "lodging_tax_payment" or \
                          self.player.worn_items.get("offhand") == "lodging_tax_payment"
            if has_payment:
                self.player.send_message(
                    "\nYou have arrived at the Town Hall. You should "
                    "<span class='keyword' data-command='give clerk payment'>GIVE</span> the <span class='keyword' data-command='look at payment'>payment</span> to the <span class='keyword' data-command='look at clerk'>clerk</span>."
                )
                self.player.completed_quests.append("intro_give_clerk")
        
        if rt > 0:
            _set_action_roundtime(self.player, rt)
            
        # --- (Group move logic moved up) ---


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
            
        climbing_skill = self.player.skills.get("climbing", 0)
        dc = climbable_object.get("climb_dc", 20)
        
        # --- Skill check for leader ---
        roll = random.randint(1, 100) + climbing_skill
        attempt_skill_learning(self.player, "climbing") # LBD
        success_margin = roll - dc
        
        rt = 3.0
        move_msg = ""
        
        if success_margin < 0: # Failure
            rt = max(3.0, 10.0 - (climbing_skill / 10.0))
            self.player.send_message(f"You struggle with the {target_name} but fail to climb it.")
            _set_action_roundtime(self.player, rt)
            return # Failed, stop here
        else: # Success
            rt = max(1.0, 5.0 - (success_margin / 20.0))
            move_msg = f"You grasp the {target_name} and begin to climb...\nAfter a few moments, you arrive."
            
        if _check_toll_gate(self.player, target_room_id):
            return
        
        # ---
        # --- **** THIS IS THE FIX FOR LEADER ****
        # ---
        group = self.world.get_group(self.player.group_id)
        is_leader = group and group["leader"] == self.player.name.lower() and len(group["members"]) > 1
        if is_leader:
            move_msg = f"You grasp the {target_name} and begin to climb... and your group follows."
        # ---
        # --- **** END FIX ****
        # ---
            
        original_room_id = self.room.room_id # --- Store for group move
        self.player.move_to_room(target_room_id, move_msg)
        
        # ---
        # --- **** THIS IS THE FIX FOR LOGIC ORDER ****
        # ---
        # 1. Handle group move *before* showing room
        _handle_group_move(
            self.world, self.player, original_room_id, target_room_id,
            move_msg, "climb", skill_dc=dc
        )

        # 2. Now get new room data and show it
        new_room_data = self.world.get_room(target_room_id)
        new_room = Room(target_room_id, new_room_data.get("name", ""), new_room_data.get("description", ""), db_data=new_room_data)
        show_room_to_player(self.player, new_room)
        # ---
        # --- **** END FIX ****
        # ---
        
        _set_action_roundtime(self.player, rt)
        
        # --- (Group move logic moved up) ---


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
            current_posture = self.player.posture
            move_msg = ""
            rt = 0.0 
            
            if current_posture == "standing":
                move_msg = f"You move {normalized_direction}..."
            elif current_posture == "prone":
                move_msg = f"You crawl {normalized_direction}..."
            else: # sitting or kneeling
                self.player.send_message("You must stand up first.")
                return
            
            if _check_toll_gate(self.player, target_room_id):
                return
            
            # ---
            # --- **** THIS IS THE FIX FOR LEADER ****
            # ---
            group = self.world.get_group(self.player.group_id)
            is_leader = group and group["leader"] == self.player.name.lower() and len(group["members"]) > 1
            if is_leader:
                move_msg = f"You move {normalized_direction}... and your group follows."
            # ---
            # --- **** END FIX ****
            # ---
            
            original_room_id = self.room.room_id # --- Store for group move
            self.player.move_to_room(target_room_id, move_msg)
            
            # ---
            # --- **** THIS IS THE FIX FOR LOGIC ORDER ****
            # ---
            # 1. Handle group move *before* showing room
            _handle_group_move(
                self.world, self.player, original_room_id, target_room_id,
                move_msg, normalized_direction, skill_dc=0
            )

            # 2. Now get new room data and show it
            new_room_data = self.world.get_room(target_room_id)
            new_room = Room(target_room_id, new_room_data.get("name", ""), new_room_data.get("description", ""), db_data=new_room_data)
            show_room_to_player(self.player, new_room)
            # ---
            # --- **** END FIX ****
            # ---
            
            # --- Tutorial Hook ---
            if (target_room_id == "town_hall" and "intro_give_clerk" not in self.player.completed_quests):
                has_payment = "lodging_tax_payment" in self.player.inventory or \
                              self.player.worn_items.get("mainhand") == "lodging_tax_payment" or \
                              self.player.worn_items.get("offhand") == "lodging_tax_payment"
                if has_payment:
                    self.player.send_message(
                        "\nYou have arrived at the Town Hall. You should "
                        "<span class='keyword' data-command='give clerk payment'>GIVE</span> the <span class='keyword' data-command='look at payment'>payment</span> to the <span class='keyword' data-command='look at clerk'>clerk</span>."
                    )
                    self.player.completed_quests.append("intro_give_clerk")

            if rt > 0:
                _set_action_roundtime(self.player, rt)
            
            # --- (Group move logic moved up) ---
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
                current_posture = self.player.posture
                move_msg = ""
                rt = 0.0 
                
                if current_posture == "standing":
                    move_msg = "You head out..."
                elif current_posture == "prone":
                    move_msg = "You crawl out..."
                else: # sitting or kneeling
                    self.player.send_message("You must stand up first.")
                    return

                if _check_toll_gate(self.player, target_room_id):
                    return

                # ---
                # --- **** THIS IS THE FIX FOR LEADER ****
                # ---
                group = self.world.get_group(self.player.group_id)
                is_leader = group and group["leader"] == self.player.name.lower() and len(group["members"]) > 1
                if is_leader:
                    move_msg = "You head out... and your group follows."
                # ---
                # --- **** END FIX ****
                # ---

                original_room_id = self.room.room_id # --- Store for group move
                self.player.move_to_room(target_room_id, move_msg)
                
                # ---
                # --- **** THIS IS THE FIX FOR LOGIC ORDER ****
                # ---
                # 1. Handle group move *before* showing room
                _handle_group_move(
                    self.world, self.player, original_room_id, target_room_id,
                    move_msg, "out", skill_dc=0
                )

                # 2. Now get new room data and show it
                new_room_data = self.world.get_room(target_room_id)
                new_room = Room(target_room_id, new_room_data.get("name", ""), new_room_data.get("description", ""), db_data=new_room_data)
                show_room_to_player(self.player, new_room)
                # ---
                # --- **** END FIX ****
                # ---
                
                # --- Tutorial Hook ---
                if (original_room_id == "inn_room" and
                    target_room_id == "inn_front_desk" and
                    "intro_leave_room_tasks" in self.player.completed_quests and
                    "intro_talk_to_innkeeper" not in self.player.completed_quests):
                    
                    self.player.send_message(
                        "\nYou are now in the inn's main lobby. You should <span class='keyword' data-command='talk to innkeeper'>TALK</span> "
                        "to the innkeeper about your bill. <span class='keyword' data-command='help talk'>[Help: TALK]</span>"
                    )
                    self.player.completed_quests.append("intro_talk_to_innkeeper")
                
                if rt > 0:
                    _set_action_roundtime(self.player, rt)

                # --- (Group move logic moved up) ---
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