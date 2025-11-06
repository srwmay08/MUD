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
from mud_backend.core.skill_handler import calculate_skill_bonus
from mud_backend import config

# --- STANCE MODIFIERS ---
# Multipliers applied to final AS and DS based on stance.
STANCE_MODIFIERS = {
    "offensive": {"as_mod": 1.15, "ds_mod": 0.70},
    "advance":   {"as_mod": 1.10, "ds_mod": 0.80},
    "forward":   {"as_mod": 1.05, "ds_mod": 0.90},
    "neutral":   {"as_mod": 1.00, "ds_mod": 1.00},
    "guarded":   {"as_mod": 0.90, "ds_mod": 1.10},
    "defensive": {"as_mod": 0.75, "ds_mod": 1.25},
    # Fallback for creatures without stances
    "creature":  {"as_mod": 1.00, "ds_mod": 1.00}
}

POSTURE_MODIFIERS = {
    "standing":  {"as_mod": 1.0, "ds_mod": 1.0},
    "sitting":   {"as_mod": 0.5, "ds_mod": 0.5},
    "kneeling":  {"as_mod": 0.75, "ds_mod": 0.75},
    "prone":     {"as_mod": 0.3, "ds_mod": 0.9}
}

# Percentages of full DS applied in different postures
POSTURE_PERCENTAGE = {
    "standing":  1.00,
    "sitting":   0.50,
    "kneeling":  0.75,
    "prone":     0.90
}

SHIELD_DATA = {
    "starter_small_shield": {
        "size": "small",
        "factor": 1.0,
        "size_penalty_melee": 0,
        "size_mod_melee": 1.0,
        "size_mod_ranged": 1.2,
        "size_bonus_ranged": 10
    }
}
DEFAULT_SHIELD_DATA = SHIELD_DATA["starter_small_shield"]

RACE_MODIFIERS = {
    "Human": {"STR": 5, "CON": 0, "DEX": 0, "AGI": 0, "LOG": 5, "INT": 5, "WIS": 0, "INF": 0, "ZEA": 5, "ESS": 0, "DIS": 0, "AUR": 0},
    "Elf": {"STR": 0, "CON": -5, "DEX": 10, "AGI": 15, "LOG": 0, "INT": 0, "WIS": 0, "INF": 5, "ZEA": 0, "ESS": 0, "DIS": -10, "AUR": 5},
    "Dwarf": {"STR": 10, "CON": 15, "DEX": 0, "AGI": -5, "LOG": 5, "INT": 0, "WIS": 0, "INF": -5, "ZEA": 5, "ESS": 0, "DIS": 15, "AUR": 0},
    "Dark Elf": {"STR": 0, "CON": -5, "DEX": 10, "AGI": 5, "LOG": 0, "INT": 5, "WIS": 5, "INF": -5, "ZEA": -5, "ESS": 0, "DIS": -10, "AUR": 10},
}
DEFAULT_RACE_MODS = {"STR": 0, "CON": 0, "DEX": 0, "AGI": 0, "LOG": 0, "INT": 0, "WIS": 0, "INF": 0, "ZEA": 0, "ESS": 0, "DIS": 0, "AUR": 0}

def get_stat_bonus(stat_value: int, stat_name: str, race: str) -> int:
    base_bonus = math.floor((stat_value - 50) / 2)
    race_mods = RACE_MODIFIERS.get(race, DEFAULT_RACE_MODS)
    race_bonus = race_mods.get(stat_name, 0)
    return base_bonus + race_bonus

def get_entity_race(entity: Any) -> str:
    if isinstance(entity, Player):
        return entity.appearance.get("race", "Human")
    elif isinstance(entity, dict):
        return entity.get("race", "Human")
    return "Human"

def get_entity_armor_type(entity, game_items_global: dict) -> str:
    if hasattr(entity, 'get_armor_type'):
        return entity.get_armor_type(game_items_global)
    elif isinstance(entity, dict):
        equipped_items_dict = entity.get("equipped", {})
        torso_id = equipped_items_dict.get("torso")
        if torso_id and game_items_global:
            armor_data = game_items_global.get(torso_id)
            if armor_data and armor_data.get("type") == "armor":
                return armor_data.get("armor_type", config.DEFAULT_UNARMORED_TYPE)
        return entity.get("innate_armor_type", config.DEFAULT_UNARMORED_TYPE)
    return config.DEFAULT_UNARMORED_TYPE

def _get_weapon_type(weapon_item_data: dict | None) -> str:
    if not weapon_item_data: return "brawling"
    skill = weapon_item_data.get("skill")
    if skill in ["two_handed_edged", "two_handed_blunt", "polearms"]: return "2H"
    if skill in ["bows", "crossbows"]: return "bow"
    if skill == "staves": return "runestaff"
    return "1H"

def _get_armor_hindrance(armor_item_data: dict | None, defender_skills: dict) -> float:
    if not armor_item_data: return 1.0
    base_ap = armor_item_data.get("armor_ap", 0)
    if base_ap == 0: return 1.0
    base_rt = armor_item_data.get("armor_rt", 0)
    armor_use_ranks = defender_skills.get("armor_use", 0)
    skill_bonus = calculate_skill_bonus(armor_use_ranks)
    threshold = ((base_rt * 20) - 10)
    effective_ap = base_ap if skill_bonus <= threshold else base_ap / 2
    return max(0.0, 1.0 + (effective_ap / 200.0))

# --- UPDATED AS CALCULATION ---
def calculate_attack_strength(attacker_name: str, attacker_stats: dict, attacker_skills: dict,
                              weapon_item_data: dict | None, target_armor_type: str,
                              attacker_posture: str, attacker_stance: str, attacker_race: str) -> int:
    as_val = 0
    as_components_log = []
    weapon_name_display = "Barehanded"

    strength_stat = attacker_stats.get("STR", 50)
    str_bonus = get_stat_bonus(strength_stat, "STR", attacker_race)
    as_val += str_bonus
    as_components_log.append(f"Str({str_bonus})")

    if not weapon_item_data or weapon_item_data.get("type") != "weapon":
        brawling_skill_rank = attacker_skills.get("brawling", 0)
        brawling_bonus = calculate_skill_bonus(brawling_skill_rank)
        as_val += brawling_bonus
        as_components_log.append(f"Brawl({brawling_bonus})")
        base_barehanded_as = getattr(config, 'BAREHANDED_BASE_AS', 0)
        as_val += base_barehanded_as
        if base_barehanded_as != 0: as_components_log.append(f"BaseAS({base_barehanded_as})")
    else:
        weapon_name_display = weapon_item_data.get("name", "Unknown Weapon")
        weapon_skill_name = weapon_item_data.get("skill")
        if weapon_skill_name:
            skill_rank = attacker_skills.get(weapon_skill_name, 0)
            skill_bonus = calculate_skill_bonus(skill_rank)
            as_val += skill_bonus
            as_components_log.append(f"Skill({skill_bonus})")

        avd_mods = weapon_item_data.get("avd_modifiers", {})
        avd_bonus = avd_mods.get(target_armor_type, avd_mods.get(config.DEFAULT_UNARMORED_TYPE, 0))
        as_val += avd_bonus
        if avd_bonus != 0: as_components_log.append(f"ItemAvD({avd_bonus})")

    cman_ranks = attacker_skills.get("combat_maneuvers", 0)
    cman_bonus = math.floor(cman_ranks / 2)
    as_val += cman_bonus
    if cman_bonus != 0: as_components_log.append(f"CMan({cman_bonus})")

    # Apply Posture Modifier
    posture_mod = POSTURE_MODIFIERS.get(attacker_posture, POSTURE_MODIFIERS["standing"])["as_mod"]
    as_val = int(as_val * posture_mod)

    # Apply Stance Modifier
    stance_data = STANCE_MODIFIERS.get(attacker_stance, STANCE_MODIFIERS["creature"])
    stance_mod = stance_data["as_mod"]
    final_as = int(as_val * stance_mod)

    if config.DEBUG_MODE and getattr(config, 'DEBUG_COMBAT_ROLLS', False):
        print(f"DEBUG AS CALC for {attacker_name} (Wpn: {weapon_name_display}, Pos: {attacker_posture}, Stance: {attacker_stance}): Raw={as_val} * Stance({stance_mod}) = {final_as} [{' + '.join(as_components_log)}]")
    return final_as

# --- DS CALCULATIONS ---
def calculate_evade_defense(defender_stats: dict, defender_skills: dict, defender_race: str,
                            armor_data: dict | None, shield_data: dict | None,
                            posture_percent: float, is_ranged_attack: bool) -> int:
    dodging_ranks = defender_skills.get("dodging", 0)
    agi_bonus = get_stat_bonus(defender_stats.get("AGI", 50), "AGI", defender_race)
    int_bonus = get_stat_bonus(defender_stats.get("INT", 50), "INT", defender_race)

    base_value = agi_bonus + math.floor(int_bonus / 4) + dodging_ranks
    armor_hindrance = _get_armor_hindrance(armor_data, defender_skills)

    shield_factor = 1.0
    shield_size_penalty = 0
    if shield_data:
        shield_props = SHIELD_DATA.get("starter_small_shield", DEFAULT_SHIELD_DATA)
        shield_factor = shield_props["factor"]
        if not is_ranged_attack:
            shield_size_penalty = shield_props["size_penalty_melee"]

    ds = (base_value * armor_hindrance * shield_factor - shield_size_penalty) * posture_percent
    if is_ranged_attack: ds *= 1.5
    return math.floor(ds)

def calculate_block_defense(defender_stats: dict, defender_skills: dict, defender_race: str,
                            shield_data: dict | None, posture_percent: float, is_ranged_attack: bool) -> int:
    if not shield_data: return 0
    shield_ranks = defender_skills.get("shield_use", 0)
    str_bonus = get_stat_bonus(defender_stats.get("STR", 50), "STR", defender_race)
    dex_bonus = get_stat_bonus(defender_stats.get("DEX", 50), "DEX", defender_race)

    base_value = shield_ranks + math.floor(str_bonus / 4) + math.floor(dex_bonus / 4)
    shield_props = SHIELD_DATA.get("starter_small_shield", DEFAULT_SHIELD_DATA)
    size_mod = shield_props["size_mod_ranged"] if is_ranged_attack else shield_props["size_mod_melee"]
    size_bonus = shield_props["size_bonus_ranged"] if is_ranged_attack else 0

    ds = (base_value * size_mod + size_bonus) * posture_percent * (2/3) + 20
    return math.floor(ds)

def calculate_parry_defense(defender_stats: dict, defender_skills: dict, defender_race: str,
                            weapon_data: dict | None, offhand_data: dict | None, defender_level: int,
                            posture_percent: float, is_ranged_attack: bool) -> int:
    if is_ranged_attack: return 0
    weapon_skill = weapon_data.get("skill", "brawling") if weapon_data else "brawling"
    weapon_ranks = defender_skills.get(weapon_skill, 0)

    str_bonus = get_stat_bonus(defender_stats.get("STR", 50), "STR", defender_race)
    dex_bonus = get_stat_bonus(defender_stats.get("DEX", 50), "DEX", defender_race)
    base_value = weapon_ranks + math.floor(str_bonus / 4) + math.floor(dex_bonus / 4)

    weapon_type = _get_weapon_type(weapon_data)
    handedness_mod = 1.5 if weapon_type == "2H" else 1.0
    ds = base_value * handedness_mod * posture_percent * 0.5
    return math.floor(ds)

# --- UPDATED DS CALCULATION ---
def calculate_defense_strength(defender: Any,
                               armor_item_data: dict | None, shield_item_data: dict | None,
                               weapon_item_data: dict | None, offhand_item_data: dict | None,
                               is_ranged_attack: bool, defender_stance: str) -> int:
    if isinstance(defender, Player):
        stats, skills, race, posture, level = defender.stats, defender.skills, defender.race, defender.posture, defender.level
        name = defender.name
    elif isinstance(defender, dict):
        stats, skills, race, posture, level = defender.get("stats",{}), defender.get("skills",{}), defender.get("race","Human"), defender.get("posture","standing"), defender.get("level",1)
        name = defender.get("name", "Creature")
    else:
        return 0

    posture_percent = POSTURE_PERCENTAGE.get(posture, 1.0)

    evade_ds = calculate_evade_defense(stats, skills, race, armor_item_data, shield_item_data, posture_percent, is_ranged_attack)
    block_ds = calculate_block_defense(stats, skills, race, shield_item_data, posture_percent, is_ranged_attack)
    parry_ds = calculate_parry_defense(stats, skills, race, weapon_item_data, offhand_item_data, level, posture_percent, is_ranged_attack)

    base_ds = evade_ds + block_ds + parry_ds

    # Apply Stance Modifier
    stance_data = STANCE_MODIFIERS.get(defender_stance, STANCE_MODIFIERS["creature"])
    stance_mod = stance_data["ds_mod"]
    final_ds = int(base_ds * stance_mod)

    if config.DEBUG_MODE and getattr(config, 'DEBUG_COMBAT_ROLLS', False):
        print(f"DEBUG DS CALC for {name} (Pos: {posture}({posture_percent}), Stance: {defender_stance}({stance_mod})): Base={base_ds} (E:{evade_ds}+B:{block_ds}+P:{parry_ds}) -> Final={final_ds}")

    return final_ds

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

def resolve_attack(attacker: Any, defender: Any, game_items_global: dict) -> dict:
    is_attacker_player = isinstance(attacker, Player)
    attacker_name = attacker.name if is_attacker_player else attacker.get("name", "Creature")
    attacker_stats = attacker.stats if is_attacker_player else attacker.get("stats", {})
    attacker_skills = attacker.skills if is_attacker_player else attacker.get("skills", {})
    attacker_posture = attacker.posture if is_attacker_player else attacker.get("posture", "standing")
    attacker_race = get_entity_race(attacker)
    # Get attacker stance, default to 'creature' for monsters
    attacker_stance = attacker.stance if is_attacker_player else attacker.get("stance", "creature")

    if is_attacker_player:
        attacker_weapon_data = attacker.get_equipped_item_data("mainhand", game_items_global)
        attacker.add_field_exp(1)
    else:
        mainhand_id = attacker.get("equipped", {}).get("mainhand")
        attacker_weapon_data = game_items_global.get(mainhand_id) if mainhand_id else None

    attacker_weapon_type = _get_weapon_type(attacker_weapon_data)
    is_ranged_attack = attacker_weapon_type in ["bow"]

    is_defender_player = isinstance(defender, Player)
    defender_name = defender.name if is_defender_player else defender.get("name", "Creature")
    # Get defender stance, default to 'creature' for monsters
    defender_stance = defender.stance if is_defender_player else defender.get("stance", "creature")

    if is_defender_player:
        defender_armor_data = defender.get_equipped_item_data("torso", game_items_global)
        defender_shield_data = defender.get_equipped_item_data("offhand", game_items_global)
        defender_weapon_data = defender.get_equipped_item_data("mainhand", game_items_global)
        defender_offhand_data = defender.get_equipped_item_data("offhand", game_items_global)
        defender_armor_type_str = defender.get_armor_type(game_items_global)
    else:
        torso_id = defender.get("equipped", {}).get("torso")
        offhand_id = defender.get("equipped", {}).get("offhand")
        mainhand_id = defender.get("equipped", {}).get("mainhand")
        defender_armor_data = game_items_global.get(torso_id) if torso_id else None
        defender_shield_data = game_items_global.get(offhand_id) if offhand_id else None
        defender_weapon_data = game_items_global.get(mainhand_id) if mainhand_id else None
        defender_offhand_data = game_items_global.get(offhand_id) if offhand_id else None
        defender_armor_type_str = get_entity_armor_type(defender, game_items_global)

    if defender_shield_data and defender_shield_data.get("type") != "shield":
        defender_shield_data = None
    if defender_offhand_data and defender_offhand_data.get("type") == "shield":
        defender_offhand_data = None

    attacker_as = calculate_attack_strength(
        attacker_name, attacker_stats, attacker_skills,
        attacker_weapon_data, defender_armor_type_str,
        attacker_posture, attacker_stance, attacker_race
    )

    defender_ds = calculate_defense_strength(
        defender, defender_armor_data, defender_shield_data,
        defender_weapon_data, defender_offhand_data,
        is_ranged_attack, defender_stance
    )

    d100_roll = random.randint(1, 100)
    combat_advantage = getattr(config, 'COMBAT_ADVANTAGE_FACTOR', 40)
    combat_roll_result = (attacker_as - defender_ds) + combat_advantage + d100_roll

    as_str = f"+{attacker_as}" if attacker_as >= 0 else str(attacker_as)
    ds_str = f"+{defender_ds}" if defender_ds >= 0 else str(defender_ds)
    roll_string = (
        f"  AS: {as_str} vs DS: {ds_str} "
        f"+ ADV: +{combat_advantage} + d100: +{d100_roll} = +{combat_roll_result}"
    )

    if is_attacker_player:
        weapon_display = attacker_weapon_data.get("name", "your fist") if attacker_weapon_data else "your fist"
        msg_key_hit = "player_hit"
        msg_key_miss = "player_miss"
    else:
        weapon_display = attacker_weapon_data.get("name", "its natural weapons") if attacker_weapon_data else "its natural weapons"
        msg_key_hit = "monster_hit"
        msg_key_miss = "monster_miss"

    msg_vars = {"attacker": attacker_name, "defender": defender_name, "weapon_display": weapon_display}

    results = {
        'hit': False, 'damage': 0, 'roll_string': roll_string,
        'attacker_msg': "", 'defender_msg': "", 'broadcast_msg': "",
        'damage_msg': "", 'defender_damage_msg': "", 'broadcast_damage_msg': ""
    }

    if combat_roll_result > config.COMBAT_HIT_THRESHOLD:
        results['hit'] = True
        flat_base_damage_component = getattr(config, 'BAREHANDED_FLAT_DAMAGE', 1)
        if not is_attacker_player and (not attacker_weapon_data or attacker_weapon_data.get("type") != "weapon"):
             flat_base_damage_component += attacker.get("natural_attack_bonus_damage", 0)

        damage_divisor = getattr(config, 'COMBAT_DAMAGE_MODIFIER_DIVISOR', 10)
        damage_bonus_from_roll = max(0, (combat_roll_result - config.COMBAT_HIT_THRESHOLD) // damage_divisor)
        total_damage = max(1, flat_base_damage_component + damage_bonus_from_roll)
        if d100_roll >= 95: total_damage = int(total_damage * 1.5)
        results['damage'] = total_damage

        flavor_msg = get_flavor_message(msg_key_hit, d100_roll, combat_roll_result)
        results['attacker_msg'] = flavor_msg.format(**msg_vars)
        results['defender_msg'] = flavor_msg.format(**msg_vars)
        results['damage_msg'] = f"You hit for **{total_damage}** damage!"
        results['defender_damage_msg'] = f"You are hit for **{total_damage}** damage!"

        broadcast_flavor_msg = get_flavor_message(msg_key_hit.replace("player", "monster"), d100_roll, combat_roll_result)
        results['broadcast_msg'] = broadcast_flavor_msg.format(**msg_vars)
        results['broadcast_damage_msg'] = f"{attacker_name} hits for **{total_damage}** damage!"
    else:
        results['hit'] = False
        flavor_msg = get_flavor_message(msg_key_miss, d100_roll, combat_roll_result)
        results['attacker_msg'] = flavor_msg.format(**msg_vars)
        results['defender_msg'] = flavor_msg.format(**msg_vars)
        broadcast_flavor_msg = get_flavor_message(msg_key_miss.replace("player", "monster"), d100_roll, combat_roll_result)
        results['broadcast_msg'] = broadcast_flavor_msg.format(**msg_vars)

    return results

def calculate_roundtime(agility: int) -> float:
    return max(3.0, 5.0 - ((agility - 50) / 25))

def _find_combatant(entity_id: str) -> Optional[Any]:
    player_info = None
    with game_state.PLAYER_LOCK:
        player_info = game_state.ACTIVE_PLAYERS.get(entity_id.lower())
    if player_info: return player_info.get("player_obj")

    combat_data = None
    with game_state.COMBAT_LOCK:
        combat_data = game_state.COMBAT_STATE.get(entity_id)
    if not combat_data: return None

    room_id = combat_data.get("current_room_id")
    if not room_id: return None

    room_data = None
    with game_state.ROOM_LOCK:
        room_data = game_state.GAME_ROOMS.get(room_id)
    if not room_data: return None

    return next((obj for obj in room_data.get("objects", []) if obj.get("monster_id") == entity_id), None)

def stop_combat(combatant_id: str, target_id: str):
    game_state.COMBAT_STATE.pop(combatant_id, None)
    game_state.COMBAT_STATE.pop(target_id, None)

def process_combat_tick(broadcast_callback, send_to_player_callback):
    current_time = time.time()
    combatant_list = []
    with game_state.COMBAT_LOCK:
        combatant_list = list(game_state.COMBAT_STATE.items())

    for combatant_id, state in combatant_list:
        if state.get("state_type") != "combat": continue
        with game_state.COMBAT_LOCK:
             if combatant_id not in game_state.COMBAT_STATE: continue
        if current_time < state["next_action_time"]: continue

        attacker = _find_combatant(combatant_id)
        defender = _find_combatant(state["target_id"])
        attacker_room_id = state.get("current_room_id")

        if not attacker or not defender or not attacker_room_id:
            with game_state.COMBAT_LOCK: stop_combat(combatant_id, state["target_id"])
            continue

        if isinstance(attacker, Player): continue # Players attack via command

        is_defender_player = isinstance(defender, Player)
        defender_room_id = defender.current_room_id if is_defender_player else game_state.COMBAT_STATE.get(state["target_id"], {}).get("current_room_id")

        if attacker_room_id != defender_room_id:
            with game_state.COMBAT_LOCK: game_state.COMBAT_STATE.pop(combatant_id, None)
            continue

        attack_results = resolve_attack(attacker, defender, game_items_global=game_state.GAME_ITEMS)

        sid_to_skip = None
        if is_defender_player:
            send_to_player_callback(defender.name, attack_results['defender_msg'], "combat_other")
            defender_info = game_state.ACTIVE_PLAYERS.get(defender.name.lower())
            if defender_info: sid_to_skip = defender_info.get("sid")

        broadcast_callback(attacker_room_id, attack_results['broadcast_msg'], "combat_broadcast", skip_sid=sid_to_skip)
        if is_defender_player: send_to_player_callback(defender.name, attack_results['roll_string'], "combat_roll")

        if attack_results['hit']:
            damage = attack_results['damage']
            if is_defender_player: send_to_player_callback(defender.name, attack_results['defender_damage_msg'], "combat_other")
            broadcast_callback(attacker_room_id, attack_results['broadcast_damage_msg'], "combat_broadcast", skip_sid=sid_to_skip)

            if is_defender_player:
                defender.hp -= damage
                if defender.hp <= 0:
                    defender.hp = 0
                    broadcast_callback(attacker_room_id, f"**{defender.name} has been DEFEATED!**", "combat_death")
                    defender.current_room_id = config.PLAYER_DEATH_ROOM_ID
                    defender.deaths_recent = min(5, defender.deaths_recent + 1)
                    con_loss = min(3 + defender.deaths_recent, 25 - defender.con_lost)
                    if con_loss > 0:
                        defender.stats["CON"] = defender.stats.get("CON", 50) - con_loss
                        defender.con_lost += con_loss
                        send_to_player_callback(defender.name, f"You have lost {con_loss} Constitution.", "system_error")
                    defender.death_sting_points += 2000
                    send_to_player_callback(defender.name, "You feel the sting of death... (XP gain is reduced)", "system_error")
                    defender.posture = "standing"
                    save_game_state(defender)
                    with game_state.COMBAT_LOCK: stop_combat(combatant_id, state["target_id"])
                    continue
                else:
                    send_to_player_callback(defender.name, f"(You have {defender.hp}/{defender.max_hp} HP remaining)", "system_info")
                    save_game_state(defender)

        rt_seconds = calculate_roundtime(attacker.get("stats", {}).get("AGI", 50))
        with game_state.COMBAT_LOCK:
            # Use direct access to ensure we update the live state, not a stale copy
            if combatant_id in game_state.COMBAT_STATE:
                 game_state.COMBAT_STATE[combatant_id]["next_action_time"] = current_time + rt_seconds