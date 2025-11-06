# mud_backend/core/game_loop/monster_ai.py
import random
import copy
from typing import Callable, Tuple, List, Dict
from mud_backend.core import game_state
from mud_backend import config

def process_monster_ai(log_time_prefix: str, broadcast_callback: Callable):
    """
    Processes AI for all active monsters.
    Currently handles:
    - Passive wandering (based on 'movement_rules')
    """
    
    potential_movers: List[Tuple[Dict, str]] = []

    # Lock rooms while we scan to prevent concurrent modification issues
    with game_state.ROOM_LOCK:
        for room_id, room_data in game_state.GAME_ROOMS.items():
            if not room_data or "objects" not in room_data:
                continue
                
            for obj in room_data["objects"]:
                if obj.get("is_monster"):
                    monster_id = obj.get("monster_id")
                    
                    # --- HYDRATION CHECK ---
                    if monster_id and "movement_rules" not in obj:
                         template = game_state.GAME_MONSTER_TEMPLATES.get(monster_id)
                         if template:
                             obj.update(copy.deepcopy(template))
                    # -----------------------

                    if obj.get("movement_rules"):
                        # Don't move if in combat
                        in_combat = False
                        # --- NEW: Use UID for combat check ---
                        monster_uid = obj.get("uid")
                        if monster_uid:
                            with game_state.COMBAT_LOCK:
                                 if game_state.COMBAT_STATE.get(monster_uid, {}).get("state_type") == "combat":
                                     in_combat = True
                        
                        if not in_combat:
                            potential_movers.append((obj, room_id))

    # Use UIDs to track who has moved to prevent double-moves
    moved_monster_uids = set()

    for monster, current_room_id in potential_movers:
        monster_uid = monster.get("uid")
        if monster_uid and monster_uid in moved_monster_uids:
            continue
            
        movement_rules = monster.get("movement_rules", {})
        wander_chance = movement_rules.get("wander_chance", 0.0)
        allowed_rooms = movement_rules.get("allowed_rooms", [])

        roll = random.random()
        should_move = roll < wander_chance

        if config.DEBUG_MODE and should_move:
             monster_name = monster.get("name", "Unknown")
             # print(f"{log_time_prefix} - MONSTER_AI: {monster_name} in {current_room_id} decided to move (Roll {roll:.2f} < {wander_chance:.2f})")

        if should_move:
            current_room = game_state.GAME_ROOMS.get(current_room_id)
            if not current_room or not current_room.get("exits"):
                continue
                
            exits = list(current_room["exits"].items())
            random.shuffle(exits)
            
            chosen_exit = None
            destination_room_id = None
            
            # Find a valid exit based on allowed_rooms
            for direction, target_room_id in exits:
                if not allowed_rooms or target_room_id in allowed_rooms:
                    chosen_exit = direction
                    destination_room_id = target_room_id
                    break
            
            if chosen_exit and destination_room_id:
                with game_state.ROOM_LOCK:
                    source_room = game_state.GAME_ROOMS.get(current_room_id)
                    dest_room = game_state.GAME_ROOMS.get(destination_room_id)
                    
                    if source_room and dest_room and monster in source_room["objects"]:
                        source_room["objects"].remove(monster)
                        dest_room["objects"].append(monster)
                        if monster_uid:
                            moved_monster_uids.add(monster_uid)
                        
                        monster_name = monster.get("name", "something")
                        
                        broadcast_callback(current_room_id, f"The {monster_name} slinks off towards the {chosen_exit}.", "ambient_move")
                        broadcast_callback(destination_room_id, f"A {monster_name} slinks in.", "ambient_move")
                        
                        if config.DEBUG_MODE:
                            print(f"{log_time_prefix} - MONSTER_AI: {monster_name} moved {current_room_id} -> {destination_room_id} ({chosen_exit}).")