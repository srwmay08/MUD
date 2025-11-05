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

# --- (Config, Stances, Shield, Race data, and helper functions up to resolve_attack are unchanged) ---
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

# --- THIS IS THE FIX: Using posture, not stance, for combat bonuses ---
# We will map postures to the old stance modifiers for now.
# Standing is neutral, kneeling/sitting are defensive, prone is very defensive.
POSTURE_MODIFIERS = {
    "standing":  {"as_mod": 0.75, "ds_mod": 0.75}, # Neutral
    "sitting":   {"as_mod": 0.5,  "ds_mod": 1.0},  # Defensive
    "kneeling":  {"as_mod": 0.6,  "ds_mod": 0.9},  # Guarded
    "prone":     {"as_mod": 0.2,  "ds_mod": 1.2}   # Very Defensive (hard to hit, hard to attack from)
}
POSTURE_PERCENTAGE = {
    "standing":  0.70, # Neutral
    "sitting":   1.00, # Defensive
    "kneeling":  0.80, # Guarded
    "prone":     1.20  # (Custom value for prone, very defensive)
}
# --- END FIX ---

SHIELD_DATA = {
    "starter_small_shield": {
        "size": "small",
        "factor": 0.78,
        "size_penalty_melee": 0,
        "size_mod_melee": 0.85,
        "size_mod_ranged": 1.20,
        "size_bonus_ranged": -8
    }
}
DEFAULT_SHIELD_DATA = SHIELD_DATA["starter_small_shield"] 
RACE_MODIFIERS = {
    "Human": {"STR": 5, "CON": 0, "DEX": 0, "AGI": 0, "LOG": 5, "INT": 5, "WIS": 0, "INF": 0, "ZEA": 5, "ESS": 0, "DIS": 0, "AUR": 0},
    "Elf": {"STR": 0, "CON": 0, "DEX": 5, "AGI": 15, "LOG": 0, "INT": 0, "WIS": 0, "INF": 10, "ZEA": 0, "ESS": 5, "DIS": -15, "AUR": 5},
    "Dwarf": {"STR": 10, "CON": 15, "DEX": 0, "AGI": -5, "LOG": 5, "INT": 0, "WIS": 0, "INF": -10, "ZEA": 5, "ESS": 5, "DIS": 10, "AUR": -10},
    "Dark Elf": {"STR": 0, "CON": -5, "DEX": 10, "AGI": 5, "LOG": 0, "INT": 5, "WIS": 5, "INF": -5, "ZEA": -5, "ESS": 0, "DIS": -10, "AUR": 10},
    "Troll": {"STR": 15, "CON": 20, "DEX": -10, "AGI": -15, "LOG": -10, "INT": 0, "WIS": -5, "INF": -5, "ZEA": -10, "ESS": -10, "DIS": 10, "AUR": -15},
}
DEFAULT_RACE_MODS = {"STR": 0, "CON": 0, "DEX": 0, "AGI": 0, "LOG": 0, "INT": 0, "WIS": 0, "INF": 0, "ZEA": 0, "ESS": 0, "DIS": 0, "AUR": 0}

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
def get_stat_bonus(stat_value: int, stat_name: str, race: str) -> int:
    base_bonus = math.floor((stat_value - 50) / 2)
    race_mods = RACE_MODIFIERS.get(race, DEFAULT_RACE_MODS)
    race_bonus = race_mods.get(stat_name, 0)
    return base_bonus + race_bonus
def get_skill_bonus(skill_value: int, divisor: int) -> int:
    if divisor == 0: return 0
    return skill_value // divisor 
def get_entity_race(entity: Any) -> str:
    if isinstance(entity, Player):
        return entity.appearance.get("race", "Human")
    elif isinstance(entity, dict):
        return entity.get("race", "Human") 
    return "Human"
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

# --- UPDATED: calculate_attack_strength ---
def calculate_attack_strength(attacker_name: str, attacker_stats: dict, attacker_skills: dict, 
                              weapon_item_data: dict | None, target_armor_type: str,
                              attacker_posture: str, attacker_race: str) -> int: # <-- CHANGED: stance to posture
    as_val = 0; as_components_log = [] 
    weapon_name_display = "Barehanded"
    
    strength_stat = attacker_stats.get("STR", 50)
    str_bonus = get_stat_bonus(strength_stat, "STR", attacker_race)
    as_val += str_bonus; as_components_log.append(f"Str({str_bonus})")
    
    if not weapon_item_data or weapon_item_data.get("type") != "weapon":
        brawling_skill_rank = attacker_skills.get("brawling", 0)
        brawling_bonus = calculate_skill_bonus(brawling_skill_rank)
        as_val += brawling_bonus; as_components_log.append(f"Brawl({brawling_bonus})")
        base_barehanded_as = getattr(config, 'BAREHANDED_BASE_AS', 0)
        as_val += base_barehanded_as
        if base_barehanded_as != 0: as_components_log.append(f"BaseAS({base_barehanded_as})")
    else:
        weapon_name_display = weapon_item_data.get("name", "Unknown Weapon")
        weapon_skill_name = weapon_item_data.get("skill"); skill_bonus_val = 0
        if weapon_skill_name:
            skill_rank = attacker_skills.get(weapon_skill_name, 0)
            skill_bonus_val = calculate_skill_bonus(skill_rank) 
            as_val += skill_bonus_val; as_components_log.append(f"Skill({skill_bonus_val})")
            
        avd_mods = weapon_item_data.get("avd_modifiers", {})
        avd_bonus = avd_mods.get(target_armor_type, avd_mods.get(config.DEFAULT_UNARMORED_TYPE, 0))
        as_val += avd_bonus 
        if avd_bonus != 0: as_components_log.append(f"ItemAvD({avd_bonus})")
        
    cman_ranks = attacker_skills.get("combat_maneuvers", 0)
    cman_bonus = math.floor(cman_ranks / 2)
    as_val += cman_bonus
    if cman_bonus != 0: as_components_log.append(f"CMan({cman_bonus})")
    
    # --- THIS IS THE FIX: Use POSTURE_MODIFIERS ---
    posture_mod = POSTURE_MODIFIERS.get(attacker_posture, POSTURE_MODIFIERS["standing"])["as_mod"]
    final_as = int(as_val * posture_mod)
    if config.DEBUG_MODE and getattr(config, 'DEBUG_COMBAT_ROLLS', False):
        print(f"DEBUG AS CALC for {attacker_name} (Wpn: {weapon_name_display}, Posture: {attacker_posture}, Race: {attacker_race}): Factors = {' + '.join(as_components_log)} => Raw AS = {as_val} * {posture_mod} = {final_as}")
    # --- END FIX ---
    return final_as

def _get_armor_hindrance(armor_item_data: dict | None, defender_skills: dict) -> float:
    if not armor_item_data:
        return 1.0 
    base_ap = armor_item_data.get("armor_ap", 0)
    if base_ap == 0:
        return 1.0
    base_rt = armor_item_data.get("armor_rt", 0)
    armor_use_ranks = defender_skills.get("armor_use", 0)
    skill_bonus = calculate_skill_bonus(armor_use_ranks)
    threshold = ((base_rt * 20) - 10)
    effective_ap = base_ap
    if skill_bonus > threshold:
        effective_ap = base_ap / 2
    hindrance_factor = 1.0 + (effective_ap / 200.0)
    return max(0.0, hindrance_factor) 
def _get_weapon_type(weapon_item_data: dict | None) -> str:
    if not weapon_item_data:
        return "brawling"
    skill = weapon_item_data.get("skill")
    if skill in ["two_handed_edged", "two_handed_blunt"]:
        return "2H"
    if skill == "polearms":
        return "polearm"
    if skill in ["bows", "crossbows"]:
        return "bow"
    if skill == "staves":
        return "runestaff" 
    if skill in ["brawling"]:
        return "brawling"
    return "1H" 

# --- UPDATED: calculate_evade_defense ---
def calculate_evade_defense(defender_stats: dict, defender_skills: dict, defender_race: str, 
                            armor_data: dict | None, shield_data: dict | None, 
                            posture_percent: float, is_ranged_attack: bool) -> int: # <-- CHANGED: stance to posture
    dodging_ranks = defender_skills.get("dodging", 0)
    agi_bonus = get_stat_bonus(defender_stats.get("AGI", 50), "AGI", defender_race)
    int_bonus = get_stat_bonus(defender_stats.get("INT", 50), "INT", defender_race)
    base_value = dodging_ranks + agi_bonus + math.floor(int_bonus / 4)
    armor_hindrance = _get_armor_hindrance(armor_data, defender_skills)
    shield_factor = 1.0
    shield_size_penalty = 0
    if shield_data:
        shield_id = "starter_small_shield" 
        shield_props = SHIELD_DATA.get(shield_id, DEFAULT_SHIELD_DATA)
        shield_factor = shield_props["factor"]
        if not is_ranged_attack:
            shield_size_penalty = shield_props["size_penalty_melee"]
    # --- THIS IS THE FIX: Use POSTURE_PERCENTAGE ---
    posture_modifier = 0.75 + (posture_percent / 4)
    ds = (base_value * armor_hindrance * shield_factor - shield_size_penalty) * posture_modifier
    # --- END FIX ---
    if is_ranged_attack:
        ds *= 1.5
    return math.floor(ds)

# --- UPDATED: calculate_block_defense ---
def calculate_block_defense(defender_stats: dict, defender_skills: dict, defender_race: str, 
                            shield_data: dict | None, 
                            posture_percent: float, is_ranged_attack: bool) -> int: # <-- CHANGED: stance to posture
    if not shield_data:
        return 0 
    shield_ranks = defender_skills.get("shield_use", 0)
    str_bonus = get_stat_bonus(defender_stats.get("STR", 50), "STR", defender_race)
    dex_bonus = get_stat_bonus(defender_stats.get("DEX", 50), "DEX", defender_race)
    base_value = shield_ranks + math.floor(str_bonus / 4) + math.floor(dex_bonus / 4)
    # --- THIS IS THE FIX: Use POSTURE_PERCENTAGE ---
    posture_modifier = 0.50 + (posture_percent / 2)
    # --- END FIX ---
    enchant_bonus = 0 
    ds = 0
    shield_id = "starter_small_shield"
    shield_props = SHIELD_DATA.get(shield_id, DEFAULT_SHIELD_DATA)
    if is_ranged_attack:
        size_mod = shield_props["size_mod_ranged"]
        size_bonus = shield_props["size_bonus_ranged"]
        ds = (base_value * size_mod + size_bonus) * posture_modifier * (2/3) + 20 + enchant_bonus
    else:
        size_mod = shield_props["size_mod_melee"]
        ds = (base_value * size_mod) * posture_modifier * (2/3) + 20 + enchant_bonus
    return math.floor(ds)

# --- UPDATED: calculate_parry_defense ---
def calculate_parry_defense(defender_stats: dict, defender_skills: dict, defender_race: str, 
                            weapon_data: dict | None, offhand_data: dict | None, defender_level: int,
                            posture_percent: float, is_ranged_attack: bool) -> int: # <-- CHANGED: stance to posture
    if not weapon_data:
        return 0 
    # --- THIS IS THE FIX: Use POSTURE_PERCENTAGE ---
    posture_bonus = posture_percent * 50
    # --- END FIX ---
    enchant_bonus = 0
    str_bonus = get_stat_bonus(defender_stats.get("STR", 50), "STR", defender_race)
    dex_bonus = get_stat_bonus(defender_stats.get("DEX", 50), "DEX", defender_race)
    stat_bonus = math.floor(str_bonus / 4) + math.floor(dex_bonus / 4)
    weapon_type = _get_weapon_type(weapon_data)
    weapon_skill_name = weapon_data.get("skill", "brawling")
    weapon_ranks = defender_skills.get(weapon_skill_name, 0)
    ds = 0
    if is_ranged_attack:
        if weapon_type == "runestaff":
            ds = calculate_parry_defense(defender_stats, defender_skills, defender_race,
                                         weapon_data, offhand_data, defender_level,
                                         posture_percent, is_ranged_attack=False)
            ds = ds / 2 
        else:
            ds = 0 
        return math.floor(ds)
    if weapon_type == "1H":
        base_value = weapon_ranks + stat_bonus + (enchant_bonus / 2)
        # --- THIS IS THE FIX: Use POSTURE_PERCENTAGE ---
        posture_mod = 0.20 + (posture_percent / 2)
        ds = base_value * posture_mod + posture_bonus
        # --- END FIX ---
        if offhand_data and _get_weapon_type(offhand_data) != "shield":
            twc_ranks = defender_skills.get("two_weapon_combat", 0)
            twc_base = twc_ranks + stat_bonus
            # --- THIS IS THE FIX: Use POSTURE_PERCENTAGE ---
            twc_posture_mod = 0.10 + (posture_percent / 4)
            twc_bonus = 5 
            ds += (twc_base * twc_posture_mod) + twc_bonus
            # --- END FIX ---
    elif weapon_type == "2H":
        base_value = weapon_ranks + stat_bonus + enchant_bonus
        # --- THIS IS THE FIX: Use POSTURE_PERCENTAGE ---
        posture_mod = 0.30 + (posture_percent * 0.75)
        ds = base_value * posture_mod + posture_bonus
        # --- END FIX ---
    elif weapon_type == "polearm":
        base_value = weapon_ranks + stat_bonus + enchant_bonus
        # --- THIS IS THE FIX: Use POSTURE_PERCENTAGE ---
        posture_mod = 0.27 + (posture_percent * 0.67)
        polearm_bonus = 15 + (posture_percent * 65)
        ds = (base_value * posture_mod) + posture_bonus + polearm_bonus
        # --- END FIX ---
    elif weapon_type == "bow":
        base_value = weapon_ranks + 0 + 0
        # --- THIS IS THE FIX: Use POSTURE_PERCENTAGE ---
        posture_mod = 0.15 + (posture_percent * 0.30)
        ds = (base_value * posture_mod) + posture_bonus + enchant_bonus
        # --- END FIX ---
    elif weapon_type == "runestaff":
        magic_ranks = 0
        magic_skills = ["arcane_symbols", "harness_power", "magic_item_use", 
                        "mana_control", "elemental_lore", "sorcerous_lore", 
                        "mental_lore", "spiritual_lore", "theology"]
        for skill in magic_skills:
            magic_ranks += defender_skills.get(skill, 0)
        magic_ranks_per_level = magic_ranks / (defender_level if defender_level > 0 else 1)
        parry_ranks = 0
        if magic_ranks_per_level < 4:
            parry_ranks = 10 + (0.15 * magic_ranks)
        elif 4 <= magic_ranks_per_level <= 11:
            parry_ranks = 10 + (1 + 0.1 * (magic_ranks_per_level - 8)) * (defender_level if defender_level > 0 else 1)
        else: 
            parry_ranks = 10 + (1.3 + 0.05 * (magic_ranks_per_level - 11)) * (defender_level if defender_level > 0 else 1)
        base_value = parry_ranks + stat_bonus
        # --- THIS IS THE FIX: Use POSTURE_PERCENTAGE ---
        posture_mod = 0.20 + (posture_percent / 2)
        ds = (base_value * posture_mod * 1.5) + posture_bonus + enchant_bonus
        # --- END FIX ---
    return math.floor(ds)

# --- UPDATED: calculate_defense_strength ---
def calculate_defense_strength(defender: Any, 
                               armor_item_data: dict | None, shield_item_data: dict | None,
                               weapon_item_data: dict | None, offhand_item_data: dict | None,
                               is_ranged_attack: bool) -> int:
    if isinstance(defender, Player):
        defender_name = defender.name
        defender_stats = defender.stats
        defender_skills = defender.skills
        defender_race = defender.race
        # --- THIS IS THE FIX: Use posture, not stance ---
        defender_posture = defender.posture
        # --- END FIX ---
        defender_level = defender.level
        
        # --- THIS IS THE FIX: The line that caused the crash is REMOVED ---
        # defender_status = defender.status_effects # <-- REMOVED
        # --- END FIX ---
        
    elif isinstance(defender, dict):
        defender_name = defender.get("name", "Creature")
        defender_stats = defender.get("stats", {})
        defender_skills = defender.get("skills", {})
        defender_race = defender.get("race", "Human")
        # --- THIS IS THE FIX: Use posture, not stance ---
        defender_posture = defender.get("posture", "standing")
        # --- END FIX ---
        defender_level = defender.get("level", 1) 
    else:
        return 0 
    
    # --- THIS IS THE FIX: Use POSTURE_PERCENTAGE ---
    posture_percent = POSTURE_PERCENTAGE.get(defender_posture, 0.70) 
    # --- END FIX ---
    ds_components_log = []
    generic_ds = 0 
    ds_components_log.append(f"Generic({generic_ds})")
    evade_ds = calculate_evade_defense(
        defender_stats, defender_skills, defender_race,
        armor_item_data, shield_item_data, posture_percent, is_ranged_attack
    )
    ds_components_log.append(f"Evade({evade_ds})")
    block_ds = calculate_block_defense(
        defender_stats, defender_skills, defender_race,
        shield_item_data, posture_percent, is_ranged_attack
    )
    ds_components_log.append(f"Block({block_ds})")
    parry_ds = calculate_parry_defense(
        defender_stats, defender_skills, defender_race,
        weapon_item_data, offhand_item_data, defender_level,
        posture_percent, is_ranged_attack
    )
    ds_components_log.append(f"Parry({parry_ds})")
    final_ds = generic_ds + evade_ds + block_ds + parry_ds
    if config.DEBUG_MODE and getattr(config, 'DEBUG_COMBAT_ROLLS', False):
        # --- THIS IS THE FIX: Use posture, not stance ---
        print(f"DEBUG DS CALC for {defender_name} (Posture: {defender_posture} ({posture_percent*100}%)): Factors = {' + '.join(ds_components_log)} => Final DS = {final_ds}")
        # --- END FIX ---
    return final_ds
# --- END UPDATED FUNCTION ---

# ---
# --- Re-adding the missing helper functions ---
# ---
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
# --- END ---
# ---

# ---
# --- MODIFIED: resolve_attack
# ---
def resolve_attack(attacker: Any, defender: Any, game_items_global: dict) -> dict:
    is_attacker_player = isinstance(attacker, Player)
    attacker_name = attacker.name if is_attacker_player else attacker.get("name", "Creature")
    attacker_stats = attacker.stats if is_attacker_player else attacker.get("stats", {})
    attacker_skills = attacker.skills if is_attacker_player else attacker.get("skills", {})
    
    # --- THIS IS THE FIX: Use posture, not stance ---
    attacker_posture = attacker.posture if is_attacker_player else attacker.get("posture", "standing")
    # --- END FIX ---
    attacker_race = get_entity_race(attacker)
    
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
        attacker_posture, attacker_race # <-- CHANGED: stance to posture
    )
    
    defender_ds = calculate_defense_strength(
        defender, 
        defender_armor_data,
        defender_shield_data,
        defender_weapon_data,   
        defender_offhand_data,  
        is_ranged_attack
    )
    
    d100_roll = random.randint(1, 100)
    combat_roll_result = (attacker_as - defender_ds) + config.COMBAT_ADVANTAGE_FACTOR + d100_roll
    
    roll_string = (
        f"  AS: +{attacker_as} vs DS: +{defender_ds} "
        f"+ d100: +{d100_roll} = +{combat_roll_result}"
    )
    
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

    # --- (Initialize new message keys) ---
    results = {
        'hit': False, 'damage': 0, 
        'roll_string': roll_string, 
        'attacker_msg': "", 'defender_msg': "", 'broadcast_msg': "",
        'damage_msg': "", 'defender_damage_msg': "", 'broadcast_damage_msg': ""
    }
    # --- END ---

    if combat_roll_result > config.COMBAT_HIT_THRESHOLD:
        results['hit'] = True
        
        flat_base_damage_component = 0
        if attacker_weapon_data and attacker_weapon_data.get("type") == "weapon":
            flat_base_damage_component = getattr(config, 'BAREHANDED_FLAT_DAMAGE', 1) 
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
        
        # --- (Separate flavor and damage messages) ---
        results['attacker_msg'] = flavor_msg.format(**msg_vars)
        results['defender_msg'] = flavor_msg.format(**msg_vars)
        results['damage_msg'] = f"You hit for **{total_damage}** damage!"
        results['defender_damage_msg'] = f"You are hit for **{total_damage}** damage!"
        
        broadcast_flavor_msg = get_flavor_message(msg_key_hit.replace("player", "monster"), d100_roll, combat_roll_result)
        results['broadcast_msg'] = broadcast_flavor_msg.format(**msg_vars)
        results['broadcast_damage_msg'] = f"{attacker_name} hits for **{total_damage}** damage!"
        # --- END ---

    else:
        results['hit'] = False
        flavor_msg = get_flavor_message(msg_key_miss, d100_roll, combat_roll_result)
        
        results['attacker_msg'] = flavor_msg.format(**msg_vars)
        results['defender_msg'] = flavor_msg.format(**msg_vars)
        
        broadcast_flavor_msg = get_flavor_message(msg_key_miss.replace("player", "monster"), d100_roll, combat_roll_result)
        results['broadcast_msg'] = broadcast_flavor_msg.format(**msg_vars)

    return results


# --- (calculate_roundtime, _find_combatant, stop_combat are unchanged) ---
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
# --- MODIFIED: process_combat_tick
# ---
def process_combat_tick(broadcast_callback, send_to_player_callback):
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
        
        # --- THIS IS THE FIX: Allow players to attack in combat tick ---
        # (This was preventing monsters from *starting* combat)
        # if is_attacker_player:
        #     continue
        # --- END FIX ---
            
        is_defender_player = isinstance(defender, Player)
        
        # --- NEW: Check if attacker is in a valid posture ---
        attacker_posture = "standing" # Default for monsters
        if is_attacker_player:
            attacker_posture = attacker.posture
            if attacker_posture != "standing":
                # Can't attack unless standing
                if attacker_posture in ["sitting", "prone", "kneeling"]:
                    send_to_player_callback(attacker.name, f"You must be standing to attack! (You are {attacker_posture})", "system_error")
                # Give a small RT for the failed attempt
                state["next_action_time"] = current_time + 1.0
                continue
        # --- END NEW CHECK ---

        # --- THIS IS THE FIX: Removed the extra 'room_data' argument ---
        attack_results = resolve_attack(attacker, defender, game_items_global=game_state.GAME_ITEMS) 
        # --- END FIX ---
        
        sid_to_skip = None
        
        # --- (Re-order message sending) ---
        
        # --- Message 1: Flavor Text ---
        if is_attacker_player:
            send_to_player_callback(attacker.name, attack_results['attacker_msg'], "combat_self")
            attacker_info = game_state.ACTIVE_PLAYERS.get(attacker.name.lower())
            if attacker_info:
                sid_to_skip = attacker_info.get("sid")

        if is_defender_player:
            send_to_player_callback(defender.name, attack_results['defender_msg'], "combat_other")
            defender_info = game_state.ACTIVE_PLAYERS.get(defender.name.lower())
            if defender_info and not sid_to_skip: # Don't overwrite attacker's SID
                sid_to_skip = defender_info.get("sid")
        
        broadcast_callback(room_id, attack_results['broadcast_msg'], "combat_broadcast", skip_sid=sid_to_skip)
        
        # --- Message 2: Roll String ---
        # Only show roll string to players involved
        if is_attacker_player:
            send_to_player_callback(attacker.name, attack_results['roll_string'], "combat_roll")
        if is_defender_player:
            send_to_player_callback(defender.name, attack_results['roll_string'], "combat_roll")
        
        # --- Message 3: Damage (if hit) ---
        if attack_results['hit']:
            damage = attack_results['damage']
            
            if is_attacker_player:
                send_to_player_callback(attacker.name, attack_results['damage_msg'], "combat_self")
            if is_defender_player:
                send_to_player_callback(defender.name, attack_results['defender_damage_msg'], "combat_other")
            
            broadcast_callback(room_id, attack_results['broadcast_damage_msg'], "combat_broadcast", skip_sid=sid_to_skip)

            # --- Message 4: Consequences (HP, Death) ---
            if is_defender_player:
                defender.hp -= damage
                if defender.hp <= 0:
                    # --- THIS IS THE FIX: Set HP to 0, not 1 ---
                    defender.hp = 0 
                    # --- END FIX ---
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
                    
                    # --- NEW: Force player to stand on death ---
                    defender.posture = "standing"
                    # --- END NEW ---
                    
                    save_game_state(defender)
                    stop_combat(combatant_id, state["target_id"])
                    continue
                else:
                    send_to_player_callback(defender.name, f"(You have {defender.hp}/{defender.max_hp} HP remaining)", "system_info")
                    save_game_state(defender)
            else:
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
        # --- END ---
        
        # --- Calculate and set next action time ---
        rt_seconds = 0.0
        if is_attacker_player:
            base_rt = combat_system.calculate_roundtime(self.player.stats.get("AGI", 50))
            armor_penalty = self.player.armor_rt_penalty
            rt_seconds = base_rt + armor_penalty
        else:
             rt_seconds = combat_system.calculate_roundtime(attacker.get("stats", {}).get("AGI", 50))
             
        state["next_action_time"] = current_time + rt_seconds