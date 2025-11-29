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

# --- AI BEHAVIOR LOGIC ---

def _evaluate_conditions(world: 'World', monster: Dict, target: 'Player', conditions: List[Dict]) -> bool:
    """Returns True if ALL conditions in the block are met."""
    for cond in conditions:
        c_type = cond.get("type")
        c_val = cond.get("value")
        
        if c_type == "health_below_percent":
            hp_pct = (monster.get("hp", 0) / monster.get("max_hp", 1)) * 100
            if hp_pct >= int(c_val): return False
            
        elif c_type == "target_health_below_percent":
            if not target: return False
            t_hp_pct = (target.hp / target.max_hp) * 100
            if t_hp_pct >= int(c_val): return False

        elif c_type == "target_status":
            if not target or c_val not in target.status_effects: return False
            if c_val == "prone" and target.posture != "prone": return False

        elif c_type == "self_status":
            if c_val not in monster.get("status_effects", []): return False

        elif c_type == "has_ally_low_hp":
            # Scan room for injured faction members
            room_id = world.mob_locations.get(monster.get("uid"))
            if not room_id: return False
            room = world.get_active_room_safe(room_id)
            found = False
            if room:
                with room.lock:
                    for obj in room.objects:
                        if obj.get("uid") == monster.get("uid"): continue
                        if obj.get("faction") == monster.get("faction"):
                            hp_pct = (obj.get("hp", 0) / obj.get("max_hp", 1)) * 100
                            if hp_pct < int(c_val):
                                found = True
                                break
            if not found: return False

    return True

def _execute_behavior_tree(world: 'World', monster: Dict, current_target_id: str, room_id: str, broadcast_callback) -> Dict:
    """
    Evaluates the 'ai_script' list. Returns an Action Dict if one triggers.
    Structure of ai_script: [ { "conditions": [...], "action": {...} }, ... ]
    """
    script = monster.get("ai_script", [])
    if not script: return None

    target_player = None
    if current_target_id:
        player_info = world.get_player_info(current_target_id)
        if player_info: target_player = player_info.get("player_obj")

    for block in script:
        conditions = block.get("conditions", [])
        if _evaluate_conditions(world, monster, target_player, conditions):
            return block.get("action")
            
    return None

def _perform_ai_action(world: 'World', monster: Dict, action: Dict, current_target_id: str, room_id: str, broadcast_callback):
    """Executes the chosen action."""
    act_type = action.get("type")
    act_val = action.get("value")
    monster_name = monster.get("name", "The creature")
    monster_uid = monster.get("uid")

    if act_type == "cast":
        # Check mana
        spell_id = act_val
        spell = world.game_spells.get(spell_id)
        if not spell: return
        
        # Simple mana check (monsters usually have infinite mana, but we can check if needed)
        
        # Handle Healing Ally logic specially
        if spell.get("effect") == "heal":
            # Find the injured ally again
            room = world.get_active_room_safe(room_id)
            target_ally = None
            if room:
                for obj in room.objects:
                    if obj.get("faction") == monster.get("faction") and obj.get("hp", 100) < obj.get("max_hp", 100):
                        target_ally = obj
                        break
            
            if target_ally:
                heal_amt = spell.get("base_power", 10)
                world.modify_monster_hp(target_ally["uid"], target_ally.get("max_hp"), -heal_amt) # Negative damage = heal
                broadcast_callback(room_id, f"{monster_name} casts {spell['name']} on {target_ally['name']}, healing them!", "combat_broadcast")
                
                # Apply RT
                _apply_monster_rt(world, monster, 3.0)
                return

        # Offensive Cast
        if current_target_id:
            broadcast_callback(room_id, f"{monster_name} casts {spell['name']} at the target!", "combat_broadcast")
            # We don't have a full 'cast' resolution for mobs yet in this snippet, 
            # but we can hook into resolve_attack if we treat it as a 'magic' weapon type later.
            # For now, simpler implementation:
            player_info = world.get_player_info(current_target_id)
            if player_info and player_info.get("player_obj"):
                target = player_info["player_obj"]
                # Calculate damage simply for BCS demo
                damage = spell.get("base_power", 10)
                target.hp -= damage
                target.send_message(f"You are hit by the spell for {damage} damage!")
                _apply_monster_rt(world, monster, 3.0)

    elif act_type == "flee":
        broadcast_callback(room_id, f"{monster_name} panics and flees!", "combat_broadcast")
        world.remove_combat_state(monster_uid)
        
        # Move to random exit
        room = world.get_room(room_id)
        if room and room.get("exits"):
            exit_dir, target_room = random.choice(list(room["exits"].items()))
            world.move_object_between_rooms(monster, room_id, target_room)
            world.update_mob_location(monster_uid, target_room)
            broadcast_callback(target_room, f"{monster_name} rushes in, looking panicked.", "ambient")

    elif act_type == "switch_target":
        # Find new target
        players = world.entity_manager.get_players_in_room(room_id)
        candidates = []
        for pname in players:
            pinfo = world.get_player_info(pname)
            if pinfo and pinfo.get("player_obj"):
                p = pinfo["player_obj"]
                if p.name.lower() != current_target_id:
                    candidates.append(p)
        
        if candidates:
            # Logic: Weakest?
            candidates.sort(key=lambda p: p.hp)
            new_target = candidates[0]
            
            # Update combat state
            c_state = world.get_combat_state(monster_uid)
            if c_state:
                c_state["target_id"] = new_target.name.lower()
                world.set_combat_state(monster_uid, c_state)
                
            broadcast_callback(room_id, f"{monster_name} turns its attention to {new_target.name}!", "combat_broadcast")
            _apply_monster_rt(world, monster, 1.0) # Small delay to switch

def _apply_monster_rt(world, monster, seconds):
    uid = monster.get("uid")
    c_state = world.get_combat_state(uid)
    if c_state:
        c_state["next_action_time"] = time.time() + seconds
        world.set_combat_state(uid, c_state)

# --- CORE AI LOOPS ---

def _scan_for_player_targets(world: 'World', monster_data: Dict, room_id: str) -> bool:
    """
    Scans the room for players. If an aggressive or KOS player is found,
    starts combat and returns True.
    """
    monster_uid = monster_data.get("uid")
    if not monster_uid: return False
    
    # If already fighting, don't switch targets in the scan phase
    if world.get_combat_state(monster_uid): return False

    # Check status effects preventing aggression (Stun/Sleep)
    status_effects = monster_data.get("status_effects", [])
    if "stunned" in status_effects or "sleeping" in status_effects:
        return False

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
        _initiate_combat(world, monster_data, target_player, room_id)
        return True # Combat started

    return False

def _initiate_combat(world: 'World', monster_data: Dict, target_player: 'Player', room_id: str):
    current_time = time.time()
    monster_uid = monster_data.get("uid")
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
        "next_action_time": current_time + (monster_rt / 2), # Attacks quickly
        "current_room_id": room_id
    })
    
    # Ensure HP is initialized
    if world.get_monster_hp(monster_uid) is None:
        world.set_monster_hp(monster_uid, monster_data.get("max_hp", 50))

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
            
        # Check room status
        with world.index_lock:
            players_in_room = world.room_players.get(room_id)
        
        room = world.get_active_room_safe(room_id)
        if not room:
             if players_in_room:
                 world.get_room(room_id) # Hydrate
                 room = world.get_active_room_safe(room_id)
             else:
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

        # Hydrate template if missing movement rules (rare but possible on reload)
        monster_id = monster_obj.get("monster_id")
        if monster_id and "movement_rules" not in monster_obj:
             template = world.game_monster_templates.get(monster_id)
             if template: monster_obj.update(copy.deepcopy(template))

        # --- AI PRIORITY 1: Check Status Effects (Stun/Delimbed/Prone) ---
        status_effects = monster_obj.get("status_effects", [])
        
        if "stunned" in status_effects:
            # Skip all actions if stunned
            continue
            
        # --- AI PRIORITY 2: Combat & Behavior Tree ---
        combat_state = world.get_combat_state(uid)
        in_combat = combat_state and combat_state.get("state_type") == "combat"
        target_id = combat_state.get("target_id") if in_combat else None

        # 2a. Execute Behavior Script (if any)
        # We do this even if not in combat to allow for passive behaviors like healing or buffering
        script_action = _execute_behavior_tree(world, monster_obj, target_id, room_id, broadcast_callback)
        
        if script_action:
            _perform_ai_action(world, monster_obj, script_action, target_id, room_id, broadcast_callback)
            # If action taken, skip standard attack/move this tick
            continue

        # 2b. Standard Aggro Scan (if not fighting)
        if not in_combat:
            started_combat = _scan_for_player_targets(world, monster_obj, room_id)
            if not started_combat:
                _check_and_start_npc_combat(world, monster_obj, room_id)

        # --- AI PRIORITY 3: Movement (Wander) ---
        # Only move if not in combat and not prone/delimbed legs
        if monster_obj.get("movement_rules") and not in_combat:
            # Check for leg damage preventing movement
            if monster_obj.get("delimbed_right_leg") or monster_obj.get("delimbed_left_leg"):
                pass # Can't wander if legless
            elif monster_obj.get("posture") == "prone":
                # Stand up chance?
                if random.random() < 0.5:
                    monster_obj["posture"] = "standing"
                    broadcast_callback(room_id, f"The {monster_obj.get('name')} struggles to its feet.", "ambient")
            else:
                potential_movers.append((monster_obj, room_id))

    moved_monster_uids = set()

    # Process Movement (Batched)
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