# mud_backend/core/game_loop/monster_ai.py
import random
import copy
import time 
from typing import Callable, Tuple, List, Dict, TYPE_CHECKING
from mud_backend import config
from mud_backend.core import faction_handler
from mud_backend.core import combat_system

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

def _check_and_start_npc_combat(world: 'World', npc: Dict, room_id: str):
    """
    Checks if the given NPC should attack another NPC in the room
    based on KOS faction rules.
    """
    npc_faction = npc.get("faction")
    if not npc_faction: return 

    npc_uid = npc.get("uid")
    if not npc_uid: return 

    if world.get_combat_state(npc_uid): return
        
    room_data = world.get_room(room_id)
    if not room_data: return

    for other_obj in room_data.get("objects", []):
        if other_obj.get("uid") == npc_uid: continue 
        if not (other_obj.get("is_monster") or other_obj.get("is_npc")): continue 
            
        other_faction = other_obj.get("faction")
        if not other_faction: continue 

        if faction_handler.are_factions_kos(world, npc_faction, other_faction):
            other_uid = other_obj.get("uid")
            
            if world.get_combat_state(other_uid) or world.get_defeated_monster(other_uid):
                continue

            current_time = time.time()
            npc_name = npc.get("name", "A creature")
            other_name = other_obj.get("name", "another creature")
            
            world.broadcast_to_room(room_id, f"The {npc_name} attacks the {other_name}!", "combat_broadcast", skip_sid=None)
            
            attacker_rt = combat_system.calculate_roundtime(npc.get("stats", {}).get("AGI", 50))
            world.set_combat_state(npc_uid, {
                "state_type": "combat",
                "target_id": other_uid,
                "next_action_time": current_time + attacker_rt,
                "current_room_id": room_id
            })
            if world.get_monster_hp(npc_uid) is None:
                world.set_monster_hp(npc_uid, npc.get("max_hp", 50))

            defender_rt = combat_system.calculate_roundtime(other_obj.get("stats", {}).get("AGI", 50))
            world.set_combat_state(other_uid, {
                "state_type": "combat",
                "target_id": npc_uid,
                "next_action_time": current_time + (defender_rt / 2), 
                "current_room_id": room_id
            })
            if world.get_monster_hp(other_uid) is None:
                world.set_monster_hp(other_uid, other_obj.get("max_hp", 50))
            
            return 

def process_monster_ai(world: 'World', log_time_prefix: str, broadcast_callback: Callable):
    """
    Processes AI for all active monsters.
    Refactored to use active_mob_uids and sleep logic.
    """
    
    potential_movers: List[Tuple[Dict, str]] = []

    # --- NEW: Iterate Active UIDs instead of Rooms (O(1) efficiency) ---
    # Make a copy of UIDs to safely iterate
    with world.index_lock:
        active_uids = list(world.active_mob_uids)
        
    for uid in active_uids:
        # 1. Get Location from Index
        room_id = world.mob_locations.get(uid)
        if not room_id:
            # Orphaned UID? Cleanup
            world.unregister_mob(uid)
            continue
            
        # 2. Sleep Check (Spatial Index)
        # Check if any players are in this room. If not, skip AI to save CPU.
        with world.index_lock:
            players_in_room = world.room_players.get(room_id)
            
        if not players_in_room:
            continue # Sleep mode: Do nothing for mobs in empty rooms
            
        # 3. Get Mob Data
        # We have to fetch the room to get the mob object
        with world.room_lock:
            room_data = world.game_rooms.get(room_id)
            if not room_data or "objects" not in room_data:
                continue
            
            # Find the specific mob object in the room list
            monster_obj = None
            for obj in room_data["objects"]:
                if obj.get("uid") == uid:
                    monster_obj = obj
                    break
            
            if not monster_obj:
                # Mob listed in index but not in room? Desync. Cleanup.
                world.unregister_mob(uid)
                continue

            # 4. Hydrate if needed (Phase 2 fixes this properly)
            monster_id = monster_obj.get("monster_id")
            if monster_id and "movement_rules" not in monster_obj:
                 template = world.game_monster_templates.get(monster_id)
                 if template:
                     monster_obj.update(copy.deepcopy(template))

            # 5. AI Logic (Movement Decision)
            if monster_obj.get("movement_rules"):
                in_combat = False
                with world.combat_lock:
                     if world.combat_state.get(uid, {}).get("state_type") == "combat":
                         in_combat = True
                
                if not in_combat:
                    potential_movers.append((monster_obj, room_id))

    # Process moves
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

        if should_move:
            current_room = world.game_rooms.get(current_room_id)
            if not current_room or not current_room.get("exits"):
                continue
                
            exits = list(current_room["exits"].items())
            random.shuffle(exits)
            
            chosen_exit = None
            destination_room_id = None
            
            for direction, target_room_id in exits:
                if not allowed_rooms or target_room_id in allowed_rooms:
                    chosen_exit = direction
                    destination_room_id = target_room_id
                    break
            
            if chosen_exit and destination_room_id:
                # Perform Move
                with world.room_lock:
                    success = world.move_object_between_rooms(monster, current_room_id, destination_room_id)
                    
                    if success:
                        if monster_uid:
                            moved_monster_uids.add(monster_uid)
                            # --- NEW: Update Location Index ---
                            world.update_mob_location(monster_uid, destination_room_id)
                            # ----------------------------------
                        
                        monster_name = monster.get("name", "something")
                        
                        departure_msg = monster.get("spawn_message_departure", "The {name} slinks off towards the {exit}.").format(name=monster_name, exit=chosen_exit)
                        broadcast_callback(current_room_id, departure_msg, "ambient_move")
                        
                        arrival_msg = monster.get("spawn_message_arrival", "A {name} slinks in.").format(name=monster_name)
                        broadcast_callback(destination_room_id, arrival_msg, "ambient_move")
                        
                        _check_and_start_npc_combat(world, monster, destination_room_id)
                        
                        if config.DEBUG_MODE:
                            print(f"{log_time_prefix} - MONSTER_AI: {monster_name} moved {current_room_id} -> {destination_room_id} ({chosen_exit}).")


def process_monster_ambient_messages(world: 'World', log_time_prefix: str, broadcast_callback: Callable):
    """
    Processes ambient, non-combat messages for active monsters.
    Optimization: Only checks rooms that currently contain players.
    """
    
    # --- NEW: Iterate ONLY active rooms via Spatial Index ---
    with world.index_lock:
        # Get list of room_ids that have at least 1 player
        active_rooms = [rid for rid, players in world.room_players.items() if players]
    
    for room_id in active_rooms:
        with world.room_lock:
            room_data = world.game_rooms.get(room_id)
            if not room_data or "objects" not in room_data:
                continue

            # Check monsters in this active room
            for obj in room_data["objects"]:
                if obj.get("is_monster"):
                    monster_uid = obj.get("uid")
                    
                    if not monster_uid or world.get_combat_state(monster_uid):
                        continue
                    
                    ambient_chance = obj.get("ambient_message_chance", 0.0)
                    ambient_messages = obj.get("ambient_messages", [])
                    
                    if ambient_messages and random.random() < ambient_chance:
                        message_text = random.choice(ambient_messages)
                        monster_name = obj.get("name", "A creature")
                        broadcast_msg = f"The {monster_name} {message_text}"
                        
                        broadcast_callback(room_id, broadcast_msg, "ambient")
                        break