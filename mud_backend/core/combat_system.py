# mud_backend/core/combat_system.py
import random
import re
import math
import time
import copy
from typing import Dict, Any, Optional

from mud_backend.core import game_state
from mud_backend.core.game_objects import Player
from mud_backend.core.db import save_game_state
from mud_backend.core import loot_system

# --- (MockConfigCombat, STANCE_MODIFIERS, and helper functions are unchanged) ---
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

STANCE_MODIFIERS = {
    "offensive": {"as_mod": 1.0,  "ds_mod": 0.5},
    "advance":   {"as_mod": 0.9,  "ds_mod": 0.6},
    "forward":   {"as_mod": 0.8,  "ds_mod": 0.7},
    "neutral":   {"as_mod": 0.75, "ds_mod": 0.75},
    "guarded":   {"as_mod": 0.6,  "ds_mod": 0.9},
    "defensive": {"as_mod": 0.5,  "ds_mod": 1.0}
}
def parse_and_roll_dice(dice_string: str) -> int:
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
    if divisor == 0: return 0
    return (stat_value - baseline) // divisor 
def get_skill_bonus(skill_value: int, divisor: int) -> int:
    if divisor == 0: return 0
    return skill_value // divisor 
def get_entity_armor_type(entity, game_items_global: dict) -> str:
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
                              weapon_item_data: dict | None, target_armor_type: str,
                              attacker_stance: str) -> int:
    as_val = 0; as_components_log = [] 
    weapon_name_display = "Barehanded"
    if not weapon_item_data or weapon_item_data.get("type") != "weapon":
        strength_barehanded = attacker_stats.get("STR", config.STAT_BONUS_BASELINE)
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
        strength = attacker_stats.get("STR", config.STAT_BONUS_BASELINE)
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
    stance_mod = STANCE_MODIFIERS.get(attacker_stance, STANCE_MODIFIERS["neutral"])["as_mod"]
    final_as = int(as_val * stance_mod)
    if config.DEBUG_MODE and getattr(config, 'DEBUG_COMBAT_ROLLS', False):
        print(f"DEBUG AS CALC for {attacker_name} (Wpn: {weapon_name_display}, Stance: {attacker_stance}): Factors = {' + '.join(as_components_log)} => Raw AS = {as_val} * {stance_mod} = {final_as}")
    return final_as
def calculate_defense_strength(defender_name: str, defender_stats: dict, defender_skills: dict, 
                               armor_item_data: dict | None, shield_item_data: dict | None,
                               defender_stance: str) -> int:
    ds_val = 0; ds_components_log = []
    armor_name_display = "Unarmored"; shield_name_display = "No Shield"
    agility_stat = defender_stats.get("AGI", config.STAT_BONUS_BASELINE)
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
    stance_mod = STANCE_MODIFIERS.get(defender_stance, STANCE_MODIFIERS["neutral"])["ds_mod"]
    final_ds = int(ds_val * stance_mod)
    if config.DEBUG_MODE and getattr(config, 'DEBUG_COMBAT_ROLLS', False):
        print(f"DEBUG DS CALC for {defender_name if defender_name else 'entity'} (Armor: {armor_name_display}, Shield: {shield_name_display}, Stance: {defender_stance}): Factors = {' + '.join(ds_components_log)} => Raw DS = {ds_val} * {stance_mod} = {final_ds}")
    return final_ds

# --- (HIT_MESSAGES are unchanged) ---
HIT_MESSAGES = {
    "player_hit": ["You swing {weapon_display} and strike {defender}!", "Your {weapon_display} finds its mark on {defender}!", "A solid blow from {weapon_display} connects with {defender}!"],
    "monster_hit": ["{attacker} swings {weapon_display} and strikes {defender}!", "{attacker}'s {weapon_display} finds its mark on {defender}!", "A solid blow from {attacker}'s {weapon_display} connects with {defender}!"],
    "player_crit": ["A devastating blow! Your {weapon_display} slams into {defender} with incredible force!", "You find a vital spot, driving your {weapon_display} deep into {defender}!", "A perfect strike! {defender} reels from the hit!"],
    "monster_crit": ["A devastating blow! {attacker}'s {weapon_display} slams into {defender}!", "{attacker} finds a vital spot, driving its {weapon_display} into {defender}!", "A perfect strike! {defender} reels from {attacker}'s hit!"],
    "player_miss": ["You swing {weapon_display} at {defender}, but miss.", "{defender} deftly avoids your {weapon_display}!", "Your {weapon_display} whistles through the air, hitting nothing."],
    "monster_miss": ["{attacker} swings {weapon_display} at {defender}, but misses.", "{defender} deftly avoids {attacker}'s {weapon_display}!", "{attacker}'s {weapon_display} whistles through the air, hitting nothing."],
    "player_fumble": ["You swing wildly and lose your balance, fumbling your attack!", "Your {weapon_display} slips! You completely miss {defender}."],
    "monster_fumble": ["{attacker} swings wildly and loses its balance, fumbling the attack!", "{attacker}'s {weapon_display} slips! It completely misses {defender}."]
}

def get_flavor_message(key, d100_roll, combat_roll_result):
    if combat_roll_result > config.COMBAT_HIT_THRESHOLD:
        if d100_roll >= 95: return random.choice(HIT_MESSAGES[key.replace("hit", "crit")])
        else: return random.choice(HIT_MESSAGES[key])
    else:
        if d100_roll <= 5: return random.choice(HIT_MESSAGES[key.replace("miss", "fumble")])
        else: return random.choice(HIT_MESSAGES[key.replace("hit", "miss")])
            
def get_roll_descriptor(roll_result):
    if roll_result > 100: return "a **critical** strike"
    elif roll_result > 75: return "a **solid** strike"
    elif roll_result > 50: return "a **good** hit"
    elif roll_result > 25: return "a glancing hit"
    elif roll_result > 0: return "a minor hit"
    elif roll_result > -25: return "a near miss"
    else: return "a total miss"

# ---
# MODIFIED: resolve_attack
# ---

def resolve_attack(attacker: Any, defender: Any, game_items_global: dict) -> dict:
    is_attacker_player = isinstance(attacker, Player)
    attacker_name = attacker.name if is_attacker_player else attacker.get("name", "Creature")
    attacker_stats = attacker.stats if is_attacker_player else attacker.get("stats", {})
    attacker_skills = attacker.skills if is_attacker_player else attacker.get("skills", {})
    attacker_stance = attacker.stance if is_attacker_player else attacker.get("stance", "neutral")
    
    if is_attacker_player:
        attacker_weapon_data = attacker.get_equipped_item_data("mainhand", game_items_global)
        attacker.add_field_exp(1)
    else:
        mainhand_id = attacker.get("equipped", {}).get("mainhand")
        attacker_weapon_data = game_items_global.get(mainhand_id) if mainhand_id else None

    is_defender_player = isinstance(defender, Player)
    defender_name = defender.name if is_defender_player else defender.get("name", "Creature")
    defender_stats = defender.stats if is_defender_player else defender.get("stats", {})
    defender_skills = defender.skills if is_defender_player else defender.get("skills", {})
    defender_stance = defender.stance if is_defender_player else defender.get("stance", "neutral")

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
        attacker_weapon_data, defender_armor_type_str,
        attacker_stance
    )
    defender_ds = calculate_defense_strength(
        defender_name, defender_stats, defender_skills, 
        defender_armor_data, defender_shield_data,
        defender_stance
    )
    
    d100_roll = random.randint(1, 100)
    combat_roll_result = (attacker_as - defender_ds) + config.COMBAT_ADVANTAGE_FACTOR + d100_roll
    
    # --- THIS IS THE FIX ---
    # Create the full roll string
    roll_string = (
        f"  AS: +{attacker_as} vs DS: +{defender_ds} "
        f"+ d100: +{d100_roll} = +{combat_roll_result}"
    )
    # --- END FIX ---
    
    if is_attacker_player:
        weapon_display = attacker_weapon_data.get("name", "your fist") if attacker_weapon_data else "your fist"
        msg_key_hit = "player_hit"
        msg_key_miss = "player_miss"
    else:
        weapon_display = attacker_weapon_data.get("name", "its natural weapons") if attacker_weapon_data else "its natural weapons"
        msg_key_hit = "monster_hit"
        msg_key_miss = "monster_miss"
    
    msg_vars = {
        "attacker": attacker_name,
        "defender": defender_name,
        "weapon_display": weapon_display
    }

    results = {
        'hit': False, 'damage': 0, 
        'roll_string': roll_string, # <-- Pass the new string
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
        
        if d100_roll >= 95:
             total_damage = int(total_damage * 1.5) 
             
        results['damage'] = total_damage

        flavor_msg = get_flavor_message(msg_key_hit, d100_roll, combat_roll_result)
        
        results['attacker_msg'] = (flavor_msg + f" You hit for **{total_damage}** damage!").format(**msg_vars)
        results['defender_msg'] = (flavor_msg + f" You are hit for **{total_damage}** damage!").format(**msg_vars)
        results['broadcast_msg'] = (flavor_msg + f" It hits for **{total_damage}** damage!").format(**msg_vars)

    else:
        results['hit'] = False
        flavor_msg = get_flavor_message(msg_key_miss, d100_roll, combat_roll_result)
        
        results['attacker_msg'] = flavor_msg.format(**msg_vars)
        results['defender_msg'] = flavor_msg.format(**msg_vars)
        results['broadcast_msg'] = flavor_msg.format(**msg_vars)

    return results


# --- (calculate_roundtime and _find_combatant are unchanged) ---
def calculate_roundtime(agility: int) -> float:
    agi_bonus_seconds = (agility - 50.0) / 20.0
    return max(2.0, 6.0 - agi_bonus_seconds)
def _find_combatant(entity_id: str) -> Optional[Any]:
    player_data = game_state.ACTIVE_PLAYERS.get(entity_id.lower())
    if player_data:
        return player_data.get("player_obj") 
    combat_data = game_state.COMBAT_STATE.get(entity_id)
    if not combat_data: return None 
    room_id = combat_data.get("current_room_id")
    if not room_id: return None 
    room_data = game_state.GAME_ROOMS.get(room_id)
    if not room_data: return None 
    monster_data = next((obj for obj in room_data.get("objects", []) if obj.get("monster_id") == entity_id), None)
    return monster_data 
def stop_combat(combatant_id: str, target_id: str):
    game_state.COMBAT_STATE.pop(combatant_id, None)
    game_state.COMBAT_STATE.pop(target_id, None)

# ---
# MODIFIED: process_combat_tick
# ---
def process_combat_tick(broadcast_callback, send_to_player_callback):
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
            
        is_attacker_player = isinstance(attacker, Player)
        
        if is_attacker_player:
            continue
            
        is_defender_player = isinstance(defender, Player)

        attack_results = resolve_attack(attacker, defender, game_items_global=game_state.GAME_ITEMS) 
        
        # --- Send messages to correct recipients ---
        if is_attacker_player:
            send_to_player_callback(attacker.name, attack_results['attacker_msg'], "combat_self")
        if is_defender_player:
            send_to_player_callback(defender.name, attack_results['defender_msg'], "combat_other")
        
        broadcast_callback(room_id, attack_results['broadcast_msg'], "combat_broadcast")
        
        # --- THIS IS THE FIX ---
        # Send the full roll string to the room
        broadcast_callback(room_id, attack_results['roll_string'], "combat_roll")
        # --- END FIX ---

        # 6. Apply damage and check for death
        if attack_results['hit']:
            damage = attack_results['damage']
            
            if is_defender_player:
                defender.hp -= damage
                if defender.hp <= 0:
                    # --- (Player Death Logic is unchanged) ---
                    defender.hp = 1
                    broadcast_callback(room_id, f"**{defender.name} has been DEFEATED!**", "combat_death")
                    defender.current_room_id = config.PLAYER_DEATH_ROOM_ID
                    defender.deaths_recent = min(5, defender.deaths_recent + 1)
                    con_loss = 3 + defender.deaths_recent
                    con_loss = min(con_loss, 25 - defender.con_lost)
                    if con_loss > 0:
                        defender.stats["CON"] = defender.stats.get("CON", 50) - con_loss
                        defender.con_lost += con_loss
                        send_to_player_callback(defender.name, f"You have lost {con_loss} Constitution from this death.", "system_error")
                    defender.death_sting_points += 2000
                    send_to_player_callback(defender.name, "You feel the sting of death... (XP gain is reduced)", "system_error")
                    save_game_state(defender)
                    stop_combat(combatant_id, state["target_id"])
                    continue
                else:
                    # --- MODIFIED: Show player's HP/MaxHP ---
                    send_to_player_callback(defender.name, f"(You have {defender.hp}/{defender.max_hp} HP remaining)", "system_info")
                    # --- END MODIFIED ---
                    save_game_state(defender)
            else:
                # --- (Monster Death Logic is unchanged) ---
                monster_id = defender.get("monster_id")
                if monster_id not in game_state.RUNTIME_MONSTER_HP:
                    game_state.RUNTIME_MONSTER_HP[monster_id] = defender.get("max_hp", 1)
                game_state.RUNTIME_MONSTER_HP[monster_id] -= damage
                new_hp = game_state.RUNTIME_MONSTER_HP[monster_id]
                
                if new_hp <= 0:
                    broadcast_callback(room_id, f"**The {defender.get('name')} has been DEFEATED!**", "combat_death")
                    if is_attacker_player:
                        nominal_xp = 1000 
                        if nominal_xp > 0:
                            attacker.add_field_exp(nominal_xp)
                            send_to_player_callback(attacker.name, "You gain field experience.", "system_info")
                    
                    corpse_data = loot_system.create_corpse_object_data(
                        defeated_entity_template=defender, 
                        defeated_entity_runtime_id=monster_id,
                        game_items_data=game_state.GAME_ITEMS,
                        game_loot_tables=game_state.GAME_LOOT_TABLES,
                        game_equipment_tables_data={} 
                    )
                    room_data = game_state.GAME_ROOMS.get(room_id)
                    if room_data:
                        room_data["objects"].append(corpse_data)
                        room_data["objects"] = [obj for obj in room_data["objects"] if obj.get("monster_id") != monster_id]
                        broadcast_callback(room_id, f"The {corpse_data['name']} falls to the ground.", "combat")
                    
                    game_state.DEFEATED_MONSTERS[monster_id] = {
                        "room_id": room_id,
                        "template_key": monster_id,
                        "type": "monster",
                        "eligible_at": time.time() + 300
                    }
                    stop_combat(combatant_id, state["target_id"])
                    continue
                else:
                    if is_attacker_player:
                         send_to_player_callback(attacker.name, f"(The {defender.get('name')} has {new_hp} HP remaining)", "system_info")
        
        # --- (Roundtime logic is unchanged) ---
        attacker_stats = attacker.stats if is_attacker_player else attacker.get("stats", {})
        rt_seconds = calculate_roundtime(attacker_stats.get("AGI", 50))
        state["next_action_time"] = current_time + rt_seconds