# mud_backend/verbs/movement.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.config import DIRECTION_MAP 
from mud_backend.core.registry import VerbRegistry 
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
import time
import random
import uuid
from collections import deque
from typing import Optional, List, Dict, Set, TYPE_CHECKING
from mud_backend.core.game_objects import Room
from mud_backend.core.room_handler import show_room_to_player, _get_map_data
from mud_backend.core.skill_handler import attempt_skill_learning

if TYPE_CHECKING:
    from mud_backend.core.game_state import World
    from mud_backend.core.game_objects import Player

# --- GOTO Target Map ---
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

def _clean_name(name: str) -> str:
    """Helper to strip articles for better message formatting."""
    lower_name = name.lower()
    if lower_name.startswith("a "): return name[2:]
    if lower_name.startswith("an "): return name[3:]
    if lower_name.startswith("the "): return name[4:]
    return name

def _check_toll_gate(player, target_room_id: str) -> bool:
    if player.current_room_id == "north_gate_outside" and target_room_id == "north_gate_inside":
        if "gate_pass" not in player.inventory:
            player.send_message("The guard blocks your way. 'You need a pass to enter the city.'")
            return True 
    return False

def _find_path(world, start_room_id: str, end_room_id: str) -> Optional[List[str]]:
    queue = deque([(start_room_id, [])]) 
    visited: Set[str] = {start_room_id}

    while queue:
        current_room_id, path = queue.popleft()

        if current_room_id == end_room_id:
            return path 

        room = world.get_room(current_room_id)
        if not room:
            continue

        exits = room.get("exits", {}).copy() 
        
        objects = room.get("objects", [])
        for obj in objects:
            if "ENTER" in obj.get("verbs", []) or "CLIMB" in obj.get("verbs", []):
                target_room = obj.get("target_room")
                if target_room:
                    obj_keywords = obj.get("keywords", [])
                    for keyword in obj_keywords:
                        if keyword not in exits:
                            exits[keyword] = target_room
                    
                    obj_name = obj.get("name", "").lower()
                    if obj_name and obj_name not in exits:
                         exits[obj_name] = target_room

        for direction, next_room_id in exits.items():
            if next_room_id not in visited:
                visited.add(next_room_id)
                new_path = path + [direction]
                queue.append((next_room_id, new_path))

    return None 

def _handle_group_move(
    world: 'World', 
    leader_player: 'Player',
    original_room_id: str, 
    target_room_id: str,
    move_msg: str, 
    move_verb: str, 
    skill_dc: int = 0,
    leave_msg_suffix: str = "leaves." 
):
    group = world.get_group(leader_player.group_id)
    if not group or group["leader"] != leader_player.name.lower():
        return 

    leader_name = leader_player.name

    for member_key in group["members"]:
        if member_key == leader_name.lower():
            continue 
            
        member_info = world.get_player_info(member_key)
        if not member_info:
            continue 
            
        member_obj = member_info.get("player_obj")
        sid = member_info.get("sid")
        
        if member_obj and sid and member_obj.current_room_id == original_room_id:
            
            if _check_action_roundtime(member_obj, action_type="move"):
                member_obj.send_message(f"You are busy and cannot follow {leader_name}.")
                world.send_message_to_group(
                    group["id"], 
                    f"{member_obj.name} is busy and gets left behind.",
                    skip_player_key=member_key
                )
                continue 

            member_can_move = True
            failure_message = ""

            if move_verb == "climb":
                skill_rank = member_obj.skills.get("climbing", 0)
                roll = skill_rank + random.randint(1, 100)
                attempt_skill_learning(member_obj, "climbing")
                
                if roll < skill_dc:
                    member_can_move = False
                    failure_message = f"You try to follow {leader_name} but fail to climb!"
                
            elif move_verb == "swim":
                skill_rank = member_obj.skills.get("swimming", 0)
                roll = skill_rank + random.randint(1, 100)
                attempt_skill_learning(member_obj, "swimming")
                
                if roll < skill_dc:
                    member_can_move = False
                    failure_message = f"You try to follow {leader_name} but fail to swim!"

            if member_can_move:
                follower_move_msg = ""
                if move_verb == "enter":
                    follower_move_msg = f"You follow {leader_name} inside..."
                elif move_verb == "climb":
                    follower_move_msg = f"You follow {leader_name}, climbing..."
                elif move_verb == "out":
                    follower_move_msg = f"You follow {leader_name} out..."
                elif move_verb in DIRECTION_MAP.values() or move_verb in DIRECTION_MAP.keys():
                    follower_move_msg = f"You follow {leader_name} {move_verb}..."
                else:
                    follower_move_msg = f"You follow {leader_name}..."

                member_obj.messages.clear()
                member_obj.move_to_room(target_room_id, follower_move_msg) 
                
                new_room_data = world.get_room(target_room_id)
                # --- SAFETY CHECK ---
                if not new_room_data:
                    member_obj.send_message("You cannot follow, the path leads to void.")
                    continue
                # --------------------

                new_room = Room(target_room_id, new_room_data.get("name", ""), new_room_data.get("description", ""), db_data=new_room_data)
                show_room_to_player(member_obj, new_room)
                
                world.socketio.server.leave_room(sid, original_room_id)
                
                leader_info = world.get_player_info(leader_name.lower())
                leader_sid = leader_info.get("sid") if leader_info else None
                sids_to_skip_for_leave = {sid}
                if leader_sid:
                    sids_to_skip_for_leave.add(leader_sid)

                leaves_message = f'<span class="keyword" data-name="{member_obj.name}" data-verbs="look">{member_obj.name}</span> {leave_msg_suffix}'
                
                world.broadcast_to_room(original_room_id, leaves_message, "message", skip_sid=sids_to_skip_for_leave)
                
                world.socketio.server.enter_room(sid, target_room_id)
                arrives_message = f'<span class="keyword" data-name="{member_obj.name}" data-verbs="look">{member_obj.name}</span> arrives.'
                world.broadcast_to_room(target_room_id, arrives_message, "message", skip_sid=sid)

                vitals_data = member_obj.get_vitals()
                map_data = _get_map_data(member_obj, world)
                world.socketio.emit(
                    'command_response', 
                    {'messages': member_obj.messages, 'vitals': vitals_data, 'map_data': map_data}, 
                    to=sid
                )
            else:
                if failure_message:
                    member_obj.send_message(failure_message)
                world.send_message_to_group(
                    group["id"], 
                    f"{member_obj.name} fails to {move_verb} and is left behind.", 
                    skip_player_key=member_key
                )

def _execute_goto_path(world, player_id: str, path: List[str], final_destination_room_id: str, sid: str, goto_id: str):
    player_obj = world.get_player_obj(player_id)
    if not player_obj: return 

    if not player_obj.is_goto_active or player_obj.goto_id != goto_id: return 

    for move_direction in path:
        player_obj = world.get_player_obj(player_id) 
        if not player_obj: return 
        
        if not player_obj.is_goto_active or player_obj.goto_id != goto_id:
            player_obj.send_message("You stop moving.")
            world.socketio.emit('command_response', 
                                 {'messages': player_obj.messages, 'vitals': player_obj.get_vitals(), 'map_data': _get_map_data(player_obj, world)}, 
                                 to=sid)
            return 

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
        
        player_obj = world.get_player_obj(player_id)
        if not player_obj: return
        if not player_obj.is_goto_active or player_obj.goto_id != goto_id:
            player_obj.send_message("You stop moving.")
            world.socketio.emit('command_response', 
                                 {'messages': player_obj.messages, 'vitals': player_obj.get_vitals(), 'map_data': _get_map_data(player_obj, world)}, 
                                 to=sid)
            return
            
        player_state = world.get_combat_state(player_id)
        if player_state and player_state.get("state_type") == "combat":
            player_obj.send_message("You are attacked and your movement stops!")
            world.socketio.emit('command_response', 
                                 {'messages': player_obj.messages, 'vitals': player_obj.get_vitals(), 'map_data': _get_map_data(player_obj, world)}, 
                                 to=sid)
            player_obj.is_goto_active = False
            player_obj.goto_id = None
            return

        original_room_id = player_obj.current_room_id
        current_room_data = world.get_room(original_room_id)
        if not current_room_data:
            player_obj.send_message("Your path seems to have vanished. Stopping.")
            world.socketio.emit('command_response', 
                                     {'messages': player_obj.messages, 'vitals': player_obj.get_vitals(), 'map_data': _get_map_data(player_obj, world)}, 
                                     to=sid)
            player_obj.is_goto_active = False
            player_obj.goto_id = None
            return
        
        target_room_id_step = None
        move_msg = ""
        move_verb = move_direction
        skill_dc = 0
        
        leave_msg_suffix = "leaves." 
        
        if move_direction in current_room_data.get("exits", {}):
            target_room_id_step = current_room_data.get("exits", {}).get(move_direction)
            move_msg = f"You move {move_direction}..."
            leave_msg_suffix = f"heads {move_direction}."
        else:
            enter_obj = next((obj for obj in current_room_data.get("objects", []) 
                              if ((move_direction in obj.get("keywords", []) or 
                                   move_direction == obj.get("name", "").lower()) and
                                  (obj.get("target_room")))
                             ), None)
            
            if enter_obj:
                target_room_id_step = enter_obj.get("target_room")
                clean_obj_name = _clean_name(enter_obj.get('name', 'something'))
                if "CLIMB" in enter_obj.get("verbs", []):
                    move_verb = "climb"
                    skill_dc = 20 
                    move_msg = f"You climb the {enter_obj.get('name')}..."
                    leave_msg_suffix = f"climbs the {clean_obj_name}."
                else: 
                    move_verb = "enter"
                    move_msg = f"You enter the {enter_obj.get('name')}..."
                    leave_msg_suffix = f"enters the {clean_obj_name}."
            else:
                player_obj.send_message(f"Your path is blocked at '{move_direction}'. Stopping.")
                world.socketio.emit('command_response', 
                                         {'messages': player_obj.messages, 'vitals': player_obj.get_vitals(), 'map_data': _get_map_data(player_obj, world)}, 
                                         to=sid)
                player_obj.is_goto_active = False
                player_obj.goto_id = None
                return
        
        if _check_toll_gate(player_obj, target_room_id_step):
            player_obj.send_message("Your movement is blocked. Stopping.")
            world.socketio.emit('command_response', 
                                     {'messages': player_obj.messages, 'vitals': player_obj.get_vitals(), 'map_data': _get_map_data(player_obj, world)}, 
                                     to=sid)
            player_obj.is_goto_active = False
            player_obj.goto_id = None
            return
        
        group = world.get_group(player_obj.group_id)
        is_leader = group and group["leader"] == player_obj.name.lower() and len(group["members"]) > 1
        if is_leader:
            move_msg = f"You move {move_direction}... and your group follows."

        player_obj.messages.clear()
        player_obj.move_to_room(target_room_id_step, move_msg)
        
        _handle_group_move(
            world, player_obj, original_room_id, target_room_id_step,
            move_msg, move_verb, skill_dc, leave_msg_suffix
        )
        
        new_room_data = world.get_room(target_room_id_step)
        
        # --- SAFETY CHECK ---
        if not new_room_data:
             player_obj.send_message("Error: The next room in the path is missing (Void).")
             player_obj.is_goto_active = False
             return
        # --------------------
        
        new_room = Room(target_room_id_step, new_room_data.get("name", ""), new_room_data.get("description", ""), db_data=new_room_data)
        show_room_to_player(player_obj, new_room)
        
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

        _set_action_roundtime(player_obj, 3.0) 
        
        if original_room_id and target_room_id_step != original_room_id:
            world.socketio.server.leave_room(sid, original_room_id)
            
            leaves_message = f'<span class="keyword" data-name="{player_obj.name}" data-verbs="look">{player_obj.name}</span> {leave_msg_suffix}'
            
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
            
            world.socketio.server.enter_room(sid, target_room_id_step)
            arrives_message = f'<span class="keyword" data-name="{player_obj.name}" data-verbs="look">{player_obj.name}</span> arrives.'
            
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
        
        world.socketio.emit('command_response', 
                                 {'messages': player_obj.messages, 'vitals': player_obj.get_vitals(), 'map_data': _get_map_data(player_obj, world)}, 
                                 to=sid)
        
        world.socketio.sleep(3.0) 

    player_obj = world.get_player_obj(player_id)
    if player_obj: 
        player_obj.is_goto_active = False 
        player_obj.goto_id = None
        if player_obj.current_room_id == final_destination_room_id:
            world.remove_combat_state(player_id) 
            player_obj.send_message("You have arrived.")
            world.socketio.emit('command_response', 
                                     {'messages': player_obj.messages, 'vitals': player_obj.get_vitals(), 'map_data': _get_map_data(player_obj, world)}, 
                                     to=sid)

@VerbRegistry.register(["enter"]) 
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

        # --- TABLE LOGIC START ---
        # If there are people inside, the room must be active in memory.
        players_inside = self.world.room_players.get(target_room_id, set())
        if players_inside:
            target_room_obj = self.world.get_active_room_safe(target_room_id)
            if target_room_obj and getattr(target_room_obj, "is_table", False):
                # Check Invite
                if self.player.name.lower() not in [g.lower() for g in target_room_obj.invited_guests]:
                    # Check Friends
                    friend_found = False
                    for name in players_inside:
                        p_obj = self.world.get_player_obj(name)
                        if p_obj and p_obj.is_friend(self.player.name):
                            friend_found = True
                            target_room_obj.invited_guests.append(self.player.name.lower())
                            
                            # Messages
                            self.player.send_message(f"{p_obj.name} waves to you, inviting you to join them.")
                            p_obj.send_message(f"You see {self.player.name} waving at your table. Recognizing your friend, you immediately wave for them to join you.")
                            self.world.broadcast_to_room(target_room_id, f"{p_obj.name} waves {self.player.name} over to the table.", "message", skip_sid=None)
                            break
                    
                    if not friend_found:
                        # Deny Entry
                        self.player.send_message(f"You wave to the people seated at the {enterable_object.get('name', 'table')}, hoping they will invite you to sit with them.")
                        
                        inside_msg = (
                            f"You see {self.player.name} waving at your table, clearly hoping that you will invite them to sit with you. "
                            f"If you would like, you may <span class='keyword' data-command='invite {self.player.name}'>INVITE {self.player.name}</span> to allow them to join you."
                        )
                        self.world.broadcast_to_room(target_room_id, inside_msg, "message")
                        return
        # --- TABLE LOGIC END ---
        
        if target_room_id == "inn_room":
            self.player.send_message("The door to your old room is locked. You should <span class='keyword' data-command='talk to innkeeper'>TALK TO THE INNKEEPER</span> if you wish to check in for training.")
            return
            
        current_posture = self.player.posture
        rt = 0.0
        move_msg = ""
        
        obj_keywords = enterable_object.get("keywords", [])
        is_door_or_gate = "door" in obj_keywords or "gate" in obj_keywords
        
        obj_clean_name = _clean_name(enterable_object.get('name', target_name))
        leave_suffix = ""

        if current_posture == "standing":
            move_msg = f"You enter the {enterable_object.get('name', target_name)}..."
            leave_suffix = f"enters the {obj_clean_name}."
            self.player.temp_leave_message = leave_suffix
            if not is_door_or_gate:
                rt = 3.0
        elif current_posture == "prone":
            move_msg = f"You crawl through the {enterable_object.get('name', target_name)}..."
            leave_suffix = f"crawls through the {obj_clean_name}."
            self.player.temp_leave_message = leave_suffix
            if not is_door_or_gate:
                rt = 8.0
        else: 
            self.player.send_message("You must stand up first.")
            return

        if _check_toll_gate(self.player, target_room_id):
            return
        
        group = self.world.get_group(self.player.group_id)
        is_leader = group and group["leader"] == self.player.name.lower() and len(group["members"]) > 1
        if is_leader:
            move_msg = f"You enter the {enterable_object.get('name', target_name)}... and your group follows."
            
        original_room_id = self.room.room_id
        self.player.move_to_room(target_room_id, move_msg)
        
        _handle_group_move(
            self.world, self.player, original_room_id, target_room_id,
            move_msg, "enter", skill_dc=0, leave_msg_suffix=leave_suffix
        )

        new_room_data = self.world.get_room(target_room_id)
        
        if not new_room_data:
             self.player.send_message("You cannot seem to go that way (Target room is Void).")
             return

        new_room = Room(target_room_id, new_room_data.get("name", ""), new_room_data.get("description", ""), db_data=new_room_data)
        show_room_to_player(self.player, new_room)
        
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

@VerbRegistry.register(["climb"]) 
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
        attempt_skill_learning(self.player, "climbing") 
        success_margin = roll - dc
        
        rt = 3.0
        move_msg = ""
        leave_suffix = ""
        
        if success_margin < 0:
            rt = max(3.0, 10.0 - (climbing_skill / 10.0))
            self.player.send_message(f"You struggle with the {target_name} but fail to climb it.")
            _set_action_roundtime(self.player, rt)
            return
        else:
            rt = max(1.0, 5.0 - (success_margin / 20.0))
            move_msg = f"You grasp the {target_name} and begin to climb...\nAfter a few moments, you arrive."
            
            obj_clean_name = _clean_name(climbable_object.get('name', target_name))
            leave_suffix = f"climbs the {obj_clean_name}."
            self.player.temp_leave_message = leave_suffix
            
        if _check_toll_gate(self.player, target_room_id):
            return
        
        group = self.world.get_group(self.player.group_id)
        is_leader = group and group["leader"] == self.player.name.lower() and len(group["members"]) > 1
        if is_leader:
            move_msg = f"You grasp the {target_name} and begin to climb... and your group follows."
            
        original_room_id = self.room.room_id
        self.player.move_to_room(target_room_id, move_msg)
        
        _handle_group_move(
            self.world, self.player, original_room_id, target_room_id,
            move_msg, "climb", skill_dc=dc, leave_msg_suffix=leave_suffix
        )

        new_room_data = self.world.get_room(target_room_id)
        if not new_room_data:
             self.player.send_message("You climb into... nothingness. (Void Error)")
             return
        
        new_room = Room(target_room_id, new_room_data.get("name", ""), new_room_data.get("description", ""), db_data=new_room_data)
        show_room_to_player(self.player, new_room)
        
        _set_action_roundtime(self.player, rt)

@VerbRegistry.register([
    "move", "go", 
    "n", "north", "s", "south", "e", "east", "w", "west", 
    "ne", "northeast", "nw", "northwest", "se", "southeast", "sw", "southwest",
    "u", "up", "d", "down"
])
class Move(BaseVerb):
    """
    Handles all directional movement with 'Burden' checks and Event Emission.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="move"):
            return

        target_name = None

        # Check if the command itself is a direction (e.g. "n", "north")
        if self.command.lower() in DIRECTION_MAP:
            target_name = self.command.lower()
        # Otherwise, check arguments (e.g., "move north")
        elif self.args:
            target_name = " ".join(self.args).lower()
        
        if not target_name:
            self.player.send_message("Move where? (e.g., NORTH, SOUTH, E, W, etc.)")
            return

        normalized_direction = DIRECTION_MAP.get(target_name, target_name)
        target_room_id = self.room.exits.get(normalized_direction)
        
        if target_room_id:
            # --- NEW: THE BURDEN CHECK ---
            burden_level = 0
            for item_ref in self.player.inventory:
                item = None
                if isinstance(item_ref, dict):
                    item = item_ref
                else:
                    item = self.world.game_items.get(item_ref)
                
                if item and "HEAVY" in item.get("flags", []):
                    burden_level += 1
            
            # Check worn/hands too
            for slot, item_ref in self.player.worn_items.items():
                if item_ref:
                    item = None
                    if isinstance(item_ref, dict):
                        item = item_ref
                    else:
                        item = self.world.game_items.get(item_ref)

                    if item and "HEAVY" in item.get("flags", []):
                        burden_level += 1

            # Apply Burden Penalty
            base_rt = 0.0
            if burden_level > 0:
                self.player.send_message(f"The heavy burden slows you down... (Burden Level: {burden_level})")
                base_rt = 2.0 * burden_level
            # -----------------------------

            current_posture = self.player.posture
            move_msg = ""
            leave_suffix = ""
            
            if current_posture == "standing":
                move_msg = f"You move {normalized_direction}..."
                leave_suffix = f"heads {normalized_direction}."
                self.player.temp_leave_message = leave_suffix
            elif current_posture == "prone":
                move_msg = f"You crawl {normalized_direction}..."
                leave_suffix = f"crawls {normalized_direction}."
                self.player.temp_leave_message = leave_suffix
            else:
                self.player.send_message("You must stand up first.")
                return
            
            if _check_toll_gate(self.player, target_room_id):
                return
            
            group = self.world.get_group(self.player.group_id)
            is_leader = group and group["leader"] == self.player.name.lower() and len(group["members"]) > 1
            if is_leader:
                move_msg = f"You move {normalized_direction}... and your group follows."
            
            original_room_id = self.room.room_id
            self.player.move_to_room(target_room_id, move_msg)
            
            # --- NEW: EMIT ROOM ENTER EVENT ---
            self.world.event_bus.emit("room_enter", player=self.player, room_id=target_room_id)
            # ----------------------------------
            
            _handle_group_move(
                self.world, self.player, original_room_id, target_room_id,
                move_msg, normalized_direction, skill_dc=0, leave_msg_suffix=leave_suffix
            )

            new_room_data = self.world.get_room(target_room_id)
            
            if not new_room_data:
                 self.player.send_message("You cannot go that way. (Void Error)")
                 return
            
            new_room = Room(target_room_id, new_room_data.get("name", ""), new_room_data.get("description", ""), db_data=new_room_data)
            show_room_to_player(self.player, new_room)
            
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

            if base_rt > 0:
                _set_action_roundtime(self.player, base_rt, rt_type="hard")
            return

        enterable_object = None
        for obj in self.room.objects:
             if "ENTER" in obj.get("verbs", []):
                if (target_name == obj.get("name", "").lower() or
                    target_name in obj.get("keywords", [])):
                    enterable_object = obj
                    break
                                 
        if enterable_object:
            enter_verb = Enter(self.world, self.player, self.room, enterable_object['name'].lower().split())
            enter_verb.execute() 
            return

        self.player.send_message("You cannot go that way.")

@VerbRegistry.register(["exit", "out"]) 
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
                current_posture = self.player.posture
                move_msg = ""
                leave_suffix = ""
                rt = 0.0 
                
                if current_posture == "standing":
                    move_msg = "You head out..."
                    leave_suffix = "heads out."
                    self.player.temp_leave_message = leave_suffix
                elif current_posture == "prone":
                    move_msg = "You crawl out..."
                    leave_suffix = "crawls out."
                    self.player.temp_leave_message = leave_suffix
                else: 
                    self.player.send_message("You must stand up first.")
                    return

                if _check_toll_gate(self.player, target_room_id):
                    return

                group = self.world.get_group(self.player.group_id)
                is_leader = group and group["leader"] == self.player.name.lower() and len(group["members"]) > 1
                if is_leader:
                    move_msg = "You head out... and your group follows."

                original_room_id = self.room.room_id 
                self.player.move_to_room(target_room_id, move_msg)
                
                _handle_group_move(
                    self.world, self.player, original_room_id, target_room_id,
                    move_msg, "out", skill_dc=0, leave_msg_suffix=leave_suffix
                )

                new_room_data = self.world.get_room(target_room_id)
                
                if not new_room_data:
                     self.player.send_message("You cannot go out. (Void Error)")
                     return
                
                new_room = Room(target_room_id, new_room_data.get("name", ""), new_room_data.get("description", ""), db_data=new_room_data)
                show_room_to_player(self.player, new_room)
                
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
            enter_verb = Enter(self.world, self.player, self.room, self.args)
            enter_verb.execute() 
            return

@VerbRegistry.register(["goto"]) 
class GOTO(BaseVerb):
    """
    Handles the 'goto' command for fast-travel to known locations.
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

        self.player.is_goto_active = True
        
        goto_id = uuid.uuid4().hex
        self.player.goto_id = goto_id
            
        self.world.socketio.start_background_task(
            _execute_goto_path, 
            self.world,
            player_id,
            path, 
            target_room_id,
            sid,
            goto_id
        )