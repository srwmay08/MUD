# mud_backend/core/combat_system.py
import random
import re
import math
import time
import copy
from typing import Dict, Any, Optional

# --- UPDATED: Import global state ---
from mud_backend.core import game_state
from mud_backend.core.game_objects import Player
from mud_backend.core.db import save_game_state
# --- NEW: Import our full loot system ---
from mud_backend.core import loot_system

# (MockConfig and utility functions are unchanged)
class MockConfigCombat:
    DEBUG_MODE = True; STAT_BONUS_BASELINE = 50; MELEE_AS_STAT_BONUS_DIVISOR = 20
    WEAPON_SKILL_AS_BONUS_DIVISOR = 50; BAREHANDED_BASE_AS = 0; DEFAULT_UNARMORED_TYPE = "unarmored"
    MELEE_DS_STAT_BONUS_DIVISOR = 10; UNARMORED_BASE_DS = 0; SHIELD_SKILL_DS_BONUS_DIVISOR = 10
    COMBAT_ADVANTAGE_FACTOR = 40; COMBAT_HIT_THRESHOLD = 0 
    COMBAT_DAMAGE_MODIFIER_DIVISOR = 10
    ROUNDTIME_DEFAULTS = {'roundtime_attack': 3.0, 'roundtime_look': 0.2}
    EQUIPMENT_SLOTS = {"torso": "Torso", "mainhand": "Main Hand", "offhand": "Off Hand"}
    PLAYER_DEATH_ROOM_ID = "town_square"
    BAREHANDED_FLAT_DAMAGE = 1
    DEBUG_COMBAT_ROLLS = True
config = MockConfigCombat()

def parse_and_roll_dice(dice_string: str) -> int:
    # ... (function unchanged)
    if not isinstance(dice_string, str): return 0
    match = re.match(r"(\d+)d(\d+)([+-]\d+)?", dice_string.lower())
    if not match:
        try: return int(dice_string)
        except ValueError: return 0
    num_dice, dice_sides = int(match.group(1)), int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0
    if num_dice <= 0 or dice_sides <= 0: return modifier
    return sum(random.randint(1, dice_sides) for _ in range(num_dice)) + modifier

def get_stat_bonus(stat_value: int, baseline: int, divisor: int) -> int:
    # ... (function unchanged)
    if divisor == 0: return 0
    return (stat_value - baseline) // divisor 

def get_skill_bonus(skill_value: int, divisor: int) -> int:
    # ... (function unchanged)
    if divisor == 0: return 0
    return skill_value // divisor 

def get_entity_armor_type(entity, game_items_global: dict) -> str:
    # ... (function unchanged)
    equipped_items_dict = {}
    if hasattr(entity, 'equipped_items') and hasattr(entity, 'get_armor_type'):
        return entity.get_armor_type(game_items_global)
    elif isinstance(entity, dict):
        equipped_items_dict = entity.get("equipped", {})
        torso_slot_key = "torso"
        chest_item_id = equipped_items_dict.get(torso_slot_key)
        if chest_item_id and game_items_global:
            chest_item_data = game_items_global.get(chest_item_id)
            if chest_item_data and chest_item_data.get("type") == "armor":
                return chest_item_data.get("armor_type", config.DEFAULT_UNARMORED_TYPE)
        return entity.get("innate_armor_type", config.DEFAULT_UNARMORED_TYPE)
    return config.DEFAULT_UNARMORED_TYPE

def calculate_attack_strength(attacker_name: str, attacker_stats: dict, attacker_skills: dict, 
                              weapon_item_data: dict | None, target_armor_type: str) -> int:
    # ... (function unchanged)
    as_val = 0; as_components_log = [] 
    weapon_name_display = "Barehanded"
    if not weapon_item_data or weapon_item_data.get("type") != "weapon":
        strength_barehanded = attacker_stats.get("STR", config.STAT_BONUS_BASELINE) # Use STR
        str_bonus_barehanded = get_stat_bonus(strength_barehanded, config.STAT_BONUS_BASELINE, config.MELEE_AS_STAT_BONUS_DIVISOR)
        as_val += str_bonus_barehanded; as_components_log.append(f"Str({str_bonus_barehanded})")
        brawling_skill = attacker_skills.get("brawling", 0)
        brawling_bonus = get_skill_bonus(brawling_skill, config.WEAPON_SKILL_AS_BONUS_DIVISOR)
        as_val += brawling_bonus; as_components_log.append(f"Brawl({brawling_bonus})")
        base_barehanded_as = getattr(config, 'BAREHANDED_BASE_AS', 0)
        as_val += base_barehanded_as
        if base_barehanded_as != 0: as_components_log.append(f"BaseAS({base_barehanded_as})")
    else:
        weapon_name_display = weapon_item_data.get("name", "Unknown Weapon")
        strength = attacker_stats.get("STR", config.STAT_BONUS_BASELINE) # Use STR
        str_bonus = get_stat_bonus(strength, config.STAT_BONUS_BASELINE, config.MELEE_AS_STAT_BONUS_DIVISOR)
        as_val += str_bonus; as_components_log.append(f"Str({str_bonus})")
        weapon_skill_name = weapon_item_data.get("skill"); skill_bonus_val = 0
        if weapon_skill_name:
            skill_rank = attacker_skills.get(weapon_skill_name, 0)
            skill_bonus_val = get_skill_bonus(skill_rank, config.WEAPON_SKILL_AS_BONUS_DIVISOR)
            as_val += skill_bonus_val; as_components_log.append(f"Skill({skill_bonus_val})")
        weapon_base_as = weapon_item_data.get("weapon_as_bonus", 0) 
        as_val += weapon_base_as; as_components_log.append(f"WpnAS({weapon_base_as})")
        enchant_as = weapon_item_data.get("enchantment_as_bonus", 0)
        as_val += enchant_as
        if enchant_as != 0: as_components_log.append(f"EnchAS({enchant_as})")
        avd_mods = weapon_item_data.get("avd_modifiers", {})
        avd_bonus = avd_mods.get(target_armor_type, avd_mods.get(config.DEFAULT_UNARMORED_TYPE, 0))
        as_val += avd_bonus 
        if avd_bonus != 0: as_components_log.append(f"ItemAvD({avd_bonus})")
    if config.DEBUG_MODE and getattr(config, 'DEBUG_COMBAT_ROLLS', False):
        print(f"DEBUG AS CALC for {attacker_name} (Wpn: {weapon_name_display}): Factors = {' + '.join(as_components_log)} => Raw AS = {as_val}")
    return as_val

def calculate_defense_strength(defender_name: str, defender_stats: dict, defender_skills: dict, 
                               armor_item_data: dict | None, shield_item_data: dict | None) -> int:
    # ... (function unchanged)
    ds_val = 0; ds_components_log = []
    armor_name_display = "Unarmored"; shield_name_display = "No Shield"
    agility_stat = defender_stats.get("AGI", config.STAT_BONUS_BASELINE) # Use AGI
    ds_stat_divisor = getattr(config, 'MELEE_DS_STAT_BONUS_DIVISOR', 10) 
    agi_bonus = get_stat_bonus(agility_stat, config.STAT_BONUS_BASELINE, ds_stat_divisor)
    ds_val += agi_bonus; ds_components_log.append(f"Agi({agi_bonus})")
    armor_ds_bonus = 0
    if armor_item_data and armor_item_data.get("type") == "armor":
        armor_ds_bonus = armor_item_data.get("armor_ds_bonus", 0)
        armor_name_display = armor_item_data.get("name", "Unknown Armor")
        ds_val += armor_ds_bonus; ds_components_log.append(f"Armor({armor_ds_bonus})")
    else:
        unarmored_ds = getattr(config, 'UNARMORED_BASE_DS', 0)
        ds_val += unarmored_ds
        if unarmored_ds !=0: ds_components_log.append(f"BaseDS({unarmored_ds})")
    shield_base_bonus = 0
    if shield_item_data and shield_item_data.get("type") == "shield":
        shield_base_bonus = shield_item_data.get("shield_ds_bonus", 0)
        shield_name_display = shield_item_data.get("name", "Unknown Shield")
        ds_val += shield_base_bonus; ds_components_log.append(f"Shield({shield_base_bonus})")
        shield_skill_rank = defender_skills.get("shield_use", 0)
        shield_skill_divisor = getattr(config, 'SHIELD_SKILL_DS_BONUS_DIVISOR', 10)
        shield_skill_bonus = get_skill_bonus(shield_skill_rank, shield_skill_divisor)
        ds_val += shield_skill_bonus
        if shield_skill_bonus !=0: ds_components_log.append(f"ShSkill({shield_skill_bonus})")
    if config.DEBUG_MODE and getattr(config, 'DEBUG_COMBAT_ROLLS', False):
        print(f"DEBUG DS CALC for {defender_name if defender_name else 'entity'} (Armor: {armor_name_display}, Shield: {shield_name_display}): Factors = {' + '.join(ds_components_log)} => Raw DS = {ds_val}")
    return ds_val

def resolve_attack(attacker: Any, defender: Any, game_items_global: dict) -> dict:
    """
    Resolves a single attack.
    Uses 'isinstance(obj, Player)' to differentiate player objects
    from monster data dictionaries.
    """
    is_attacker_player = isinstance(attacker, Player)
    attacker_name = attacker.name if is_attacker_player else attacker.get("name", "Creature")
    attacker_stats = attacker.stats if is_attacker_player else attacker.get("stats", {})
    attacker_skills = attacker.skills if is_attacker_player else attacker.get("skills", {})
    
    if is_attacker_player:
        attacker_weapon_data = attacker.get_equipped_item_data("mainhand", game_items_global)
    else:
        mainhand_id = attacker.get("equipped", {}).get("mainhand")
        attacker_weapon_data = game_items_global.get(mainhand_id) if mainhand_id else None

    is_defender_player = isinstance(defender, Player)
    defender_name = defender.name if is_defender_player else defender.get("name", "Creature")
    defender_stats = defender.stats if is_defender_player else defender.get("stats", {})
    defender_skills = defender.skills if is_defender_player else defender.get("skills", {})

    if is_defender_player:
        defender_armor_data = defender.get_equipped_item_data("torso", game_items_global)
        defender_shield_data = defender.get_equipped_item_data("offhand", game_items_global)
        defender_armor_type_str = defender.get_armor_type(game_items_global)
    else:
        torso_id = defender.get("equipped", {}).get("torso")
        offhand_id = defender.get("equipped", {}).get("offhand")
        defender_armor_data = game_items_global.get(torso_id) if torso_id else None
        defender_shield_data = game_items_global.get(offhand_id) if offhand_id else None
        defender_armor_type_str = get_entity_armor_type(defender, game_items_global)

    attacker_as = calculate_attack_strength(
        attacker_name, attacker_stats, attacker_skills, 
        attacker_weapon_data, defender_armor_type_str
    )
    defender_ds = calculate_defense_strength(
        defender_name, defender_stats, defender_skills, 
        defender_armor_data, defender_shield_data
    )
    
    d100_roll = random.randint(1, 100)
    combat_roll_result = (attacker_as - defender_ds) + config.COMBAT_ADVANTAGE_FACTOR + d100_roll
    
    roll_string = f"  (Roll: {attacker_name} AS {attacker_as} vs {defender_name} DS {defender_ds} -> Result {combat_roll_result})"
    
    if is_attacker_player:
        weapon_name_self = attacker_weapon_data.get("name", "your fist") if attacker_weapon_data else "your fist"
        weapon_name_other = attacker_weapon_data.get("name", "their fist") if attacker_weapon_data else "their fist"
    else:
        weapon_name_self = attacker_weapon_data.get("name", "its natural weapons") if attacker_weapon_data else "its natural weapons"
        weapon_name_other = weapon_name_self

    results = {
        'hit': False, 'damage': 0, 'roll_string': roll_string,
        'attacker_msg': "", 'defender_msg': "", 'broadcast_msg': ""
    }

    if combat_roll_result > config.COMBAT_HIT_THRESHOLD:
        results['hit'] = True
        
        flat_base_damage_component = 0
        if attacker_weapon_data and attacker_weapon_data.get("type") == "weapon":
            flat_base_damage_component = attacker_weapon_data.get("weapon_as_bonus", 0) + attacker_weapon_data.get("enchantment_as_bonus", 0)
        else:
            flat_base_damage_component = getattr(config, 'BAREHANDED_FLAT_DAMAGE', 1)
            if not is_attacker_player:
                flat_base_damage_component += attacker.get("natural_attack_bonus_damage", 0)
        
        damage_bonus_from_roll = max(0, (combat_roll_result - config.COMBAT_HIT_THRESHOLD) // config.COMBAT_DAMAGE_MODIFIER_DIVISOR)
        total_damage = max(1, flat_base_damage_component + damage_bonus_from_roll)
        results['damage'] = total_damage

        results['attacker_msg'] = f"You swing your {weapon_name_self} at {defender_name} and HIT for {total_damage} damage!"
        results['defender_msg'] = f"{attacker_name} swings {weapon_name_other} at you and HITS for {total_damage} damage!"
        results['broadcast_msg'] = f"{attacker_name} HITS {defender_name} with {weapon_name_other} for {total_damage} damage!"
    else:
        results['hit'] = False
        results['attacker_msg'] = f"You swing your {weapon_name_self} at {defender_name} but MISS!"
        results['defender_msg'] = f"{attacker_name} swings {weapon_name_other} at you but MISSES!"
        results['broadcast_msg'] = f"{attacker_name} attacks {defender_name} with {weapon_name_other} but MISSES!"

    return results


# ---
# UPDATED: COMBAT ROUNDTIME AND TICK LOGIC
# ---

def calculate_roundtime(agility: int) -> float:
    """
    Calculates the time (in seconds) until the next action
    based on Agility.
    """
    # Base 6 second roundtime, minus 1 second for every 20 AGI over 50.
    # Capped at a minimum of 2 seconds.
    agi_bonus_seconds = (agility - 50.0) / 20.0
    return max(2.0, 6.0 - agi_bonus_seconds)

def _find_combatant(entity_id: str) -> Optional[Any]:
    """
    Finds a combatant (Player object or *live* monster dict) by their ID.
    """
    # 1. Is it a player?
    player_data = game_state.ACTIVE_PLAYERS.get(entity_id.lower()) # key is lowercase name
    if player_data:
        return player_data.get("player_obj") # Return the full Player object

    # 2. Is it a monster?
    combat_data = game_state.COMBAT_STATE.get(entity_id)
    if not combat_data:
        return None 
    
    room_id = combat_data.get("current_room_id")
    if not room_id:
        return None 
        
    room_data = game_state.GAME_ROOMS.get(room_id)
    if not room_data:
        return None 

    # --- UPDATED: Find *live* monster in room ---
    # We now find the *live* monster object in the room's list.
    # This is no longer just a template.
    monster_data = next((obj for obj in room_data.get("objects", []) if obj.get("monster_id") == entity_id), None)
    return monster_data 

def stop_combat(combatant_id: str, target_id: str):
    """Removes both combatant and target from the COMBAT_STATE."""
    game_state.COMBAT_STATE.pop(combatant_id, None)
    game_state.COMBAT_STATE.pop(target_id, None)

def process_combat_tick(broadcast_callback):
    """
    This is the main combat loop, run by the global game tick.
    """
    current_time = time.time()
    
    for combatant_id, state in list(game_state.COMBAT_STATE.items()):
        
        if current_time < state["next_action_time"]:
            continue 
            
        attacker = _find_combatant(combatant_id)
        defender = _find_combatant(state["target_id"])
        room_id = state.get("current_room_id")

        if not attacker or not defender or not room_id:
            stop_combat(combatant_id, state["target_id"])
            continue

        # --- Use global item data ---
        attack_results = resolve_attack(attacker, defender, game_items_global=game_state.GAME_ITEMS) 
        
        # 5. Broadcast the public result
        broadcast_callback(room_id, attack_results['broadcast_msg'], "combat")
        broadcast_callback(room_id, attack_results['roll_string'], "combat_roll")

        # 6. Apply damage and check for death
        if attack_results['hit']:
            damage = attack_results['damage']
            is_defender_player = isinstance(defender, Player)
            
            if is_defender_player:
                defender.hp -= damage
                if defender.hp <= 0:
                    defender.hp = 0
                    broadcast_callback(room_id, f"**{defender.name} has been DEFEATED!**", "combat_death")
                    
                    defender.current_room_id = config.PLAYER_DEATH_ROOM_ID
                    defender.hp = 1
                    save_game_state(defender)
                    stop_combat(combatant_id, state["target_id"])
                    continue
                else:
                    save_game_state(defender) # Save player's new HP
            else:
                # Defender is a monster
                monster_id = defender.get("monster_id")
                
                # --- Get/Set RUNTIME HP ---
                if monster_id not in game_state.RUNTIME_MONSTER_HP:
                    game_state.RUNTIME_MONSTER_HP[monster_id] = defender.get("max_hp", 1)
                
                game_state.RUNTIME_MONSTER_HP[monster_id] -= damage
                
                if game_state.RUNTIME_MONSTER_HP[monster_id] <= 0:
                    broadcast_callback(room_id, f"**The {defender.get('name')} has been DEFEATED!**", "combat_death")
                    
                    # --- NEW: Loot/Corpse Generation ---
                    corpse_data = loot_system.create_corpse_object_data(
                        defeated_entity_template=defender, # Pass the live monster dict
                        defeated_entity_runtime_id=monster_id,
                        game_items_data=game_state.GAME_ITEMS,
                        game_loot_tables=game_state.GAME_LOOT_TABLES,
                        game_equipment_tables_data={} # TODO: Pass real data
                    )
                    
                    # Add corpse to the room's objects list
                    room_data = game_state.GAME_ROOMS.get(room_id)
                    if room_data:
                        room_data["objects"].append(corpse_data)
                        # Remove live monster
                        room_data["objects"] = [obj for obj in room_data["objects"] if obj.get("monster_id") != monster_id]
                        broadcast_callback(room_id, f"The {corpse_data['name']} falls to the ground.", "combat")
                    
                    # ---
                    
                    game_state.DEFEATED_MONSTERS[monster_id] = {
                        "room_id": room_id,
                        "template_key": monster_id,
                        "type": "monster",
                        "eligible_at": time.time() + 300 # 5 min respawn
                    }
                    stop_combat(combatant_id, state["target_id"])
                    continue
        
        # 7. Calculate and set next action time for the attacker
        rt_seconds = calculate_roundtime(attacker.stats.get("AGI", 50))
        state["next_action_time"] = current_time + rt_seconds