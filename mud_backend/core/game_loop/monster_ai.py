# mud_backend/core/game_loop/monster_ai.py
import random
import copy
import time # <-- NEW IMPORT
from typing import Callable, Tuple, List, Dict, TYPE_CHECKING
from mud_backend import config
# --- NEW: Import faction handler ---
from mud_backend.core import faction_handler
from mud_backend.core import combat_system
# --- END NEW ---

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

# ---
# --- NEW: Helper for NPC vs NPC combat
# ---
def _check_and_start_npc_combat(world: 'World', npc: Dict, room_id: str):
    """
    Checks if the given NPC should attack another NPC in the room
    based on KOS faction rules.
    """
    npc_faction = npc.get("faction")
    if not npc_faction:
        return # This NPC has no faction, it won't start fights

    npc_uid = npc.get("uid")
    if not npc_uid:
        return # Should not happen, but safety check

    # Check if NPC is already in combat
    if world.get_combat_state(npc_uid):
        return
        
    # Get a fresh copy of the room data
    room_data = world.get_room(room_id)
    if not room_data:
        return

    for other_obj in room_data.get("objects", []):
        if other_obj.get("uid") == npc_uid:
            continue # Don't fight self

        # --- MODIFIED: Check for monster OR npc ---
        if not (other_obj.get("is_monster") or other_obj.get("is_npc")):
            continue # Target is not an entity
        # --- END MODIFIED ---
            
        other_faction = other_obj.get("faction")
        if not other_faction:
            continue # Target has no faction

        # --- The KOS Check ---
        if faction_handler.are_factions_kos(world, npc_faction, other_faction):
            other_uid = other_obj.get("uid")
            
            # Check if target is already in combat or defeated
            if world.get_combat_state(other_uid) or world.get_defeated_monster(other_uid):
                continue

            # --- Start Combat! ---
            current_time = time.time()
            npc_name = npc.get("name", "A creature")
            other_name = other_obj.get("name", "another creature")
            
            world.broadcast_to_room(room_id, f"The {npc_name} attacks the {other_name}!", "combat_broadcast", skip_sid=None)
            
            # Set attacker's state
            attacker_rt = combat_system.calculate_roundtime(npc.get("stats", {}).get("AGI", 50))
            world.set_combat_state(npc_uid, {
                "state_type": "combat",
                "target_id": other_uid,
                "next_action_time": current_time + attacker_rt,
                "current_room_id": room_id
            })
            if world.get_monster_hp(npc_uid) is None:
                world.set_monster_hp(npc_uid, npc.get("max_hp", 50))

            # Set defender's state
            defender_rt = combat_system.calculate_roundtime(other_obj.get("stats", {}).get("AGI", 50))
            world.set_combat_state(other_uid, {
                "state_type": "combat",
                "target_id": npc_uid,
                "next_action_time": current_time + (defender_rt / 2), # Defender gets a faster first swing
                "current_room_id": room_id
            })
            if world.get_monster_hp(other_uid) is None:
                world.set_monster_hp(other_uid, other_obj.get("max_hp", 50))
            
            return # The NPC has found its target
# ---
# --- END NEW HELPER
# ---

def process_monster_ai(world: 'World', log_time_prefix: str, broadcast_callback: Callable):
    """
    Processes AI for all active monsters.
    Currently handles:
    - Passive wandering (based on 'movement_rules')
    """
    
    potential_movers: List[Tuple[Dict, str]] = []

    with world.room_lock:
        for room_id, room_data in world.game_rooms.items():
            if not room_data or "objects" not in room_data:
                continue
                
            for obj in room_data["objects"]:
                # --- MODIFIED: Include NPCs in this check ---
                if obj.get("is_monster") or obj.get("is_npc"):
                # --- END MODIFIED ---
                    monster_id = obj.get("monster_id") # This is fine, NPCs won't have it
                    
                    if monster_id and "movement_rules" not in obj:
                         template = world.game_monster_templates.get(monster_id)
                         if template:
                             obj.update(copy.deepcopy(template))

                    if obj.get("movement_rules"):
                        in_combat = False
                        monster_uid = obj.get("uid")
                        if monster_uid:
                             with world.combat_lock:
                                 if world.combat_state.get(monster_uid, {}).get("state_type") == "combat":
                                     in_combat = True
                        
                        if not in_combat:
                            potential_movers.append((obj, room_id))

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
                with world.room_lock:
                    source_room = world.game_rooms.get(current_room_id)
                    dest_room = world.game_rooms.get(destination_room_id)
                    
                    if source_room and dest_room and "objects" in source_room and monster in source_room["objects"]:
                        source_room["objects"].remove(monster)
                        if "objects" not in dest_room: 
                            dest_room["objects"] = []
                        dest_room["objects"].append(monster)
                        if monster_uid:
                            moved_monster_uids.add(monster_uid)
                        
                        monster_name = monster.get("name", "something")
                        
                        # ---
                        # --- THIS IS THE FIX ---
                        #
                        # 1. Read the custom departure message from the monster template
                        departure_msg_template = monster.get("spawn_message_departure", "The {name} slinks off towards the {exit}.")
                        # Format it, replacing {name} and {exit}
                        departure_msg = departure_msg_template.format(name=monster_name, exit=chosen_exit)
                        broadcast_callback(current_room_id, departure_msg, "ambient_move")
                        
                        # 2. Read the custom arrival message
                        arrival_msg_template = monster.get("spawn_message_arrival", "A {name} slinks in.")
                        # Format it, replacing {name}
                        arrival_msg = arrival_msg_template.format(name=monster_name)
                        broadcast_callback(destination_room_id, arrival_msg, "ambient_move")
                        #
                        # --- END FIX ---
                        
                        # ---
                        # --- NEW: Check for NPC-NPC combat on arrival
                        # ---
                        _check_and_start_npc_combat(world, monster, destination_room_id)
                        # --- END NEW ---
                        
                        if config.DEBUG_MODE:
                            print(f"{log_prefix} - MONSTER_AI: {monster_name} moved {current_room_id} -> {destination_room_id} ({chosen_exit}).")
                    elif config.DEBUG_MODE:
                        print(f"{log_prefix} - MONSTER_AI: {monster.get('name')} move failed (room state changed).")