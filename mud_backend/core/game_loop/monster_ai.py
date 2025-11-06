# mud_backend/core/game_loop/monster_ai.py
import random
from typing import Callable, Tuple, List, Dict
from mud_backend.core import game_state
from mud_backend import config

def process_monster_ai(log_time_prefix: str, broadcast_callback: Callable):
    """
    Processes AI for all active monsters.
    Currently handles:
    - Passive wandering (based on 'movement_rules')
    """
    
    # 1. Identify all monsters that CAN move this tick.
    # We collect them first to avoid issues while iterating over the rooms dictionary if it changes.
    # We store (monster_obj, current_room_id)
    potential_movers: List[Tuple[Dict, str]] = []

    # Use a read lock if you have one, or just the room lock if that's what you use for GAME_ROOMS access.
    # Since we might modify rooms later, we'll need the lock then too.
    # For now, let's just grab a snapshot under lock.
    with game_state.ROOM_LOCK:
        for room_id, room_data in game_state.GAME_ROOMS.items():
            if not room_data or "objects" not in room_data:
                continue
                
            for obj in room_data["objects"]:
                if obj.get("is_monster") and obj.get("movement_rules"):
                    # Check if the monster is currently in combat.
                    # We can use its monster_id to check COMBAT_STATE.
                    monster_id = obj.get("monster_id")
                    in_combat = False
                    
                    # --- FIX: Use game_state.COMBAT_STATE ---
                    with game_state.COMBAT_LOCK:
                         if monster_id and game_state.COMBAT_STATE.get(monster_id, {}).get("state_type") == "combat":
                             in_combat = True
                    # ---------------------------------------

                    if not in_combat:
                        potential_movers.append((obj, room_id))

    # 2. Process moves for eligible monsters
    # We use a set of object IDs to ensure we don't move the same monster instance twice 
    # if it wanders into a room we haven't processed yet.
    moved_monster_ids = set()

    for monster, current_room_id in potential_movers:
        # Skip if this specific object instance already moved this tick
        if id(monster) in moved_monster_ids:
            continue
            
        movement_rules = monster.get("movement_rules", {})
        wander_chance = movement_rules.get("wander_chance", 0.0)
        allowed_rooms = movement_rules.get("allowed_rooms", [])

        # --- NEW: Debug Roll ---
        roll = random.random()
        should_move = roll < wander_chance

        if config.DEBUG_MODE:
             monster_name = monster.get("name", "Unknown")
             print(f"{log_time_prefix} - MONSTER_AI: {monster_name} (in {current_room_id}) rolled {roll:.2f} vs chance {wander_chance:.2f}. Moving: {should_move}")
        # -----------------------

        if should_move:
            # It wants to move! Pick a random exit.
            current_room = game_state.GAME_ROOMS.get(current_room_id)
            if not current_room or not current_room.get("exits"):
                if config.DEBUG_MODE:
                    print(f"{log_time_prefix} - MONSTER_AI: {monster_name} wanted to move, but room {current_room_id} has no exits.")
                continue
                
            exits = list(current_room["exits"].items()) # [(dir, room_id), ...]
            random.shuffle(exits)
            
            chosen_exit = None
            destination_room_id = None
            
            # Find first valid exit
            for direction, target_room_id in exits:
                if target_room_id in allowed_rooms:
                    chosen_exit = direction
                    destination_room_id = target_room_id
                    break
            
            if chosen_exit and destination_room_id:
                # Perform the move
                # We need to lock again because we are modifying room object lists
                with game_state.ROOM_LOCK:
                    # Double check it's still there (race condition paranoia)
                    source_room = game_state.GAME_ROOMS.get(current_room_id)
                    dest_room = game_state.GAME_ROOMS.get(destination_room_id)
                    
                    if source_room and dest_room and monster in source_room["objects"]:
                        # Remove from source
                        source_room["objects"].remove(monster)
                        # Add to destination
                        dest_room["objects"].append(monster)
                        # Mark as moved
                        moved_monster_ids.add(id(monster))
                        
                        # Broadcast messages
                        monster_name = monster.get("name", "something")
                        broadcast_callback(current_room_id, f"The {monster_name} wanders {chosen_exit}.", "ambient_move")
                        broadcast_callback(destination_room_id, f"A {monster_name} wanders in.", "ambient_move")
                        
                        if config.DEBUG_MODE:
                            print(f"{log_time_prefix} - MONSTER_AI: SUCCESS - {monster_name} moved from {current_room_id} to {destination_room_id}.")
            else:
                 if config.DEBUG_MODE:
                    print(f"{log_time_prefix} - MONSTER_AI: {monster_name} wanted to move, but no allowed exits were found from {current_room_id}.")