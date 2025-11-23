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

def _scan_for_player_targets(world: 'World', monster_data: Dict, room_id: str) -> bool:
    """
    Scans the room for players. If an aggressive or KOS player is found,
    starts combat and returns True.
    """
    monster_uid = monster_data.get("uid")
    if not monster_uid: return False
    
    # If already fighting, don't switch targets or spam
    if world.get_combat_state(monster_uid): return False

    is_aggressive = monster_data.get("is_aggressive", False)
    
    # Get all players in the room
    player_names = world.entity_manager.get_players_in_room(room_id)
    if not player_names: return False

    target_player = None
    
    for p_name in player_names:
        p_info = world.get_player_info(p_name)
        if not p_info: continue
        
        player_obj = p_info.get("player_obj")
        if not player_obj: continue
        
        # Ignore dead players, admins, or invisible players
        if player_obj.hp <= 0: continue
        if player_obj.flags.get("invisible", "off") == "on": continue
        
        # Check Aggression Flags
        is_kos = faction_handler.is_player_kos_to_entity(player_obj, monster_data)
        
        if is_aggressive or is_kos:
            target_player = player_obj
            break
    
    if target_player:
        current_time = time.time()
        monster_name = monster_data.get("name", "A creature")
        
        # Broadcast attack
        world.broadcast_to_room(
            room_id, 
            f"The {monster_name} attacks {target_player.name}!", 
            "combat_broadcast"
        )
        
        target_player.send_message(f"The {monster_name} attacks you!")
        
        # Calculate Reaction/Roundtime
        monster_agi = monster_data.get("stats", {}).get("AGI", 50)
        monster_rt = combat_system.calculate_roundtime(monster_agi)
        
        # Set Combat State
        world.set_combat_state(monster_uid, {
            "state_type": "combat",
            "target_id": target_player.name.lower(),
            "next_action_time": current_time + (monster_rt / 2), # Attps quickly
            "current_room_id": room_id
        })
        
        # Ensure HP is initialized
        if world.get_monster_hp(monster_uid) is None:
            world.set_monster_hp(monster_uid, monster_data.get("max_hp", 50))
            
        return True # Combat started

    return False

def _check_and_start_npc_combat(world: 'World', npc: Dict, room_id: str):
    """Checks for hostile NPCs/Monsters in the room."""
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
            if world.get_combat_state(other_uid) or world.get_defeated_monster(other_uid): continue

            current_time = time.time()
            npc_name = npc.get("name", "A creature")
            other_name = other_obj.get("name", "another creature")
            
            world.broadcast_to_room(room_id, f"The {npc_name} attacks the {other_name}!", "combat_broadcast", skip_sid=None)
            
            attacker_rt = combat_system.calculate_roundtime(npc.get("stats", {}).get("AGI", 50))
            world.set_combat_state(npc_uid, {
                "state_type": "combat", "target_id": other_uid,
                "next_action_time": current_time + attacker_rt, "current_room_id": room_id
            })
            if world.get_monster_hp(npc_uid) is None:
                world.set_monster_hp(npc_uid, npc.get("max_hp", 50))

            defender_rt = combat_system.calculate_roundtime(other_obj.get("stats", {}).get("AGI", 50))
            world.set_combat_state(other_uid, {
                "state_type": "combat", "target_id": npc_uid,
                "next_action_time": current_time + (defender_rt / 2), "current_room_id": room_id
            })
            if world.get_monster_hp(other_uid) is None:
                world.set_monster_hp(other_uid, other_obj.get("max_hp", 50))
            
            return 

def process_monster_ai(world: 'World', log_time_prefix: str, broadcast_callback: Callable):
    potential_movers: List[Tuple[Dict, str]] = []

    with world.index_lock:
        active_uids = list(world.active_mob_uids)
        
    for i, uid in enumerate(active_uids):
        if i % 50 == 0:
            world.socketio.sleep(0) # Yield to heartbeat
            
        room_id = world.mob_locations.get(uid)
        if not room_id:
            world.unregister_mob(uid)
            continue
            
        # Check if room is active (has players)
        # Note: Even if room is 'inactive' in memory, we might want to process logic 
        # if we want persistence, but for optimization we usually only process active rooms.
        with world.index_lock:
            players_in_room = world.room_players.get(room_id)
        
        # Optimization: If no players in room, skip AI processing for this mob?
        # But we need to process wandering into player rooms. 
        # Let's allow processing but use safe getters.
        
        room = world.get_active_room_safe(room_id)
        if not room:
             # If room isn't in active memory, check if players are there (via index)
             # If players are there, we must hydrate.
             if players_in_room:
                 world.get_room(room_id) # Hydrate
                 room = world.get_active_room_safe(room_id)
             else:
                 # No players, room inactive. Skip complex AI to save cycles.
                 # (You could implement 'background wander' here later)
                 continue
        
        if not room: continue

        monster_obj = None
        with room.lock:
            for obj in room.objects:
                if obj.get("uid") == uid:
                    monster_obj = obj
                    break
        
        if not monster_obj:
            world.unregister_mob(uid)
            continue

        # Hydrate template data if missing
        monster_id = monster_obj.get("monster_id")
        if monster_id and "movement_rules" not in monster_obj:
             template = world.game_monster_templates.get(monster_id)
             if template: monster_obj.update(copy.deepcopy(template))

        # --- AI PRIORITY 1: Combat Check ---
        # Scan for players to attack
        started_combat = _scan_for_player_targets(world, monster_obj, room_id)
        
        # Scan for NPC enemies (if player check didn't start combat)
        if not started_combat:
            _check_and_start_npc_combat(world, monster_obj, room_id)

        # --- AI PRIORITY 2: Movement ---
        # Only move if not in combat
        if monster_obj.get("movement_rules"):
            in_combat = False
            combat_state = world.get_combat_state(uid)
            if combat_state and combat_state.get("state_type") == "combat":
                 in_combat = True
                 
            if not in_combat:
                potential_movers.append((monster_obj, room_id))

    moved_monster_uids = set()

    # Process Movement
    for i, (monster, current_room_id) in enumerate(potential_movers):
        if i % 10 == 0:
            world.socketio.sleep(0)

        monster_uid = monster.get("uid")
        if monster_uid and monster_uid in moved_monster_uids: continue
            
        movement_rules = monster.get("movement_rules", {})
        wander_chance = movement_rules.get("wander_chance", 0.0)
        allowed_rooms = movement_rules.get("allowed_rooms", [])

        if random.random() < wander_chance:
            current_room_data = world.get_room(current_room_id)
            if not current_room_data or not current_room_data.get("exits"): continue
                
            exits = list(current_room_data["exits"].items())
            random.shuffle(exits)
            
            chosen_exit = None
            destination_room_id = None
            
            for direction, target_room_id in exits:
                if not allowed_rooms or target_room_id in allowed_rooms:
                    chosen_exit = direction
                    destination_room_id = target_room_id
                    break
            
            if chosen_exit and destination_room_id:
                success = world.move_object_between_rooms(monster, current_room_id, destination_room_id)
                if success:
                    if monster_uid:
                        moved_monster_uids.add(monster_uid)
                        world.update_mob_location(monster_uid, destination_room_id)
                    
                    monster_name = monster.get("name", "something")
                    dep_msg = monster.get("spawn_message_departure", "The {name} slinks off towards the {exit}.").format(name=monster_name, exit=chosen_exit)
                    broadcast_callback(current_room_id, dep_msg, "ambient_move")
                    arr_msg = monster.get("spawn_message_arrival", "A {name} slinks in.").format(name=monster_name)
                    broadcast_callback(destination_room_id, arr_msg, "ambient_move")
                    
                    # Re-scan for targets in new room immediately
                    if not _scan_for_player_targets(world, monster, destination_room_id):
                        _check_and_start_npc_combat(world, monster, destination_room_id)

def process_monster_ambient_messages(world: 'World', log_time_prefix: str, broadcast_callback: Callable):
    with world.index_lock:
        active_rooms = [rid for rid, players in world.room_players.items() if players]
    
    for i, room_id in enumerate(active_rooms):
        if i % 20 == 0:
            world.socketio.sleep(0)

        room_data = world.get_room(room_id)
        if not room_data: continue

        for obj in room_data.get("objects", []):
            if obj.get("is_monster"):
                monster_uid = obj.get("uid")
                if not monster_uid or world.get_combat_state(monster_uid): continue
                
                ambient_chance = obj.get("ambient_message_chance", 0.0)
                ambient_messages = obj.get("ambient_messages", [])
                
                if ambient_messages and random.random() < ambient_chance:
                    message_text = random.choice(ambient_messages)
                    monster_name = obj.get("name", "A creature")
                    broadcast_callback(room_id, f"The {monster_name} {message_text}", "ambient")
                    break