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
# --- NEW IMPORT ---
from mud_backend.core.skill_handler import calculate_skill_bonus
# --- END NEW IMPORT ---

# --- (MockConfigCombat, STANCE_MODIFIERS, STANCE_PERCENTAGE, SHIELD_DATA, RACE_MODIFIERS, DEFAULT_RACE_MODS unchanged) ---
class MockConfigCombat:
# ... (class contents unchanged) ...
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
# ... (dict contents unchanged) ...
    "offensive": {"as_mod": 1.0,  "ds_mod": 0.5},
    "advance":   {"as_mod": 0.9,  "ds_mod": 0.6},
    "forward":   {"as_mod": 0.8,  "ds_mod": 0.7},
    "neutral":   {"as_mod": 0.75, "ds_mod": 0.75},
    "guarded":   {"as_mod": 0.6,  "ds_mod": 0.9},
    "defensive": {"as_mod": 0.5,  "ds_mod": 1.0}
}
STANCE_PERCENTAGE = {
# ... (dict contents unchanged) ...
    "offensive": 0.20, # Low value, fits 5% evade chance
    "advance":   0.40,
    "forward":   0.60,
    "neutral":   0.70,
    "guarded":   0.80, # From your documentation
    "defensive": 1.00  # Max value
}
SHIELD_DATA = {
# ... (dict contents unchanged) ...
    "starter_small_shield": {
        "size": "small",
        "factor": 0.78,
        "size_penalty_melee": 0,
        "size_mod_melee": 0.85,
        "size_mod_ranged": 1.20,
        "size_bonus_ranged": -8
    }
}
DEFAULT_SHIELD_DATA = SHIELD_DATA["starter_small_shield"] # Default to small
RACE_MODIFIERS = {
# ... (dict contents unchanged) ...
    "Human": {"STR": 5, "CON": 0, "DEX": 0, "AGI": 0, "LOG": 5, "INT": 5, "WIS": 0, "INF": 0, "ZEA": 5, "ESS": 0, "DIS": 0, "AUR": 0},
    "Elf": {"STR": 0, "CON": 0, "DEX": 5, "AGI": 15, "LOG": 0, "INT": 0, "WIS": 0, "INF": 10, "ZEA": 0, "ESS": 5, "DIS": -15, "AUR": 5},
    "Dwarf": {"STR": 10, "CON": 15, "DEX": 0, "AGI": -5, "LOG": 5, "INT": 0, "WIS": 0, "INF": -10, "ZEA": 5, "ESS": 5, "DIS": 10, "AUR": -10},
    "Dark Elf": {"STR": 0, "CON": -5, "DEX": 10, "AGI": 5, "LOG": 0, "INT": 5, "WIS": 5, "INF": -5, "ZEA": -5, "ESS": 0, "DIS": -10, "AUR": 10},
    "Troll": {"STR": 15, "CON": 20, "DEX": -10, "AGI": -15, "LOG": -10, "INT": 0, "WIS": -5, "INF": -5, "ZEA": -10, "ESS": -10, "DIS": 10, "AUR": -15},
}
DEFAULT_RACE_MODS = {"STR": 0, "CON": 0, "DEX": 0, "AGI": 0, "LOG": 0, "INT": 0, "WIS": 0, "INF": 0, "ZEA": 0, "ESS": 0, "DIS": 0, "AUR": 0}

# --- (parse_and_roll_dice, get_stat_bonus, get_skill_bonus, get_entity_race, get_entity_armor_type, calculate_attack_strength unchanged) ---
def parse_and_roll_dice(dice_string: str) -> int:
# ... (function contents unchanged) ...
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
# ... (function contents unchanged) ...
    base_bonus = math.floor((stat_value - 50) / 2)
    race_mods = RACE_MODIFIERS.get(race, DEFAULT_RACE_MODS)
    race_bonus = race_mods.get(stat_name, 0)
    return base_bonus + race_bonus
def get_skill_bonus(skill_value: int, divisor: int) -> int:
# ... (function contents unchanged) ...
    if divisor == 0: return 0
    return skill_value // divisor 
def get_entity_race(entity: Any) -> str:
# ... (function contents unchanged) ...
    if isinstance(entity, Player):
        return entity.appearance.get("race", "Human")
    elif isinstance(entity, dict):
        return entity.get("race", "Human") # Monsters default to Human mods for now
    return "Human"
def get_entity_armor_type(entity, game_items_global: dict) -> str:
# ... (function contents unchanged) ...
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
                              attacker_stance: str, attacker_race: str) -> int: 
# ... (function contents unchanged) ...
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
        
    stance_mod = STANCE_MODIFIERS.get(attacker_stance, STANCE_MODIFIERS["neutral"])["as_mod"]
    final_as = int(as_val * stance_mod)
    if config.DEBUG_MODE and getattr(config, 'DEBUG_COMBAT_ROLLS', False):
        print(f"DEBUG AS CALC for {attacker_name} (Wpn: {weapon_name_display}, Stance: {attacker_stance}, Race: {attacker_race}): Factors = {' + '.join(as_components_log)} => Raw AS = {as_val} * {stance_mod} = {final_as}")
    return final_as

# ---
# --- MODIFIED: _get_armor_hindrance ---
# ---
def _get_armor_hindrance(armor_item_data: dict | None, defender_skills: dict) -> float:
    """
    Calculates the armor hindrance factor for Evade DS.
    HindranceFactor = 1.0 + (EffectiveAP / 200.0)
    """
    if not armor_item_data:
        return 1.0 # No armor, no hindrance
        
    # 1. Get Base AP from item
    base_ap = armor_item_data.get("armor_ap", 0) # e.g., -20
    if base_ap == 0:
        return 1.0

    # 2. Get RT to calculate reduction threshold
    base_rt = armor_item_data.get("armor_rt", 0)
    
    # 3. Get Armor Use Skill Bonus
    armor_use_ranks = defender_skills.get("armor_use", 0)
    skill_bonus = calculate_skill_bonus(armor_use_ranks)

    # 4. Calculate the "overtraining" bonus
    # ASSUMPTION: The formula for reducing AP is not given, only the
    # threshold. I will assume that *any* overtraining bonus
    # (bonus > threshold) negates the AP for now.
    # This is a placeholder until the real formula is provided.
    
    threshold = ((base_rt * 20) - 10)
    
    effective_ap = base_ap
    if skill_bonus > threshold:
        # ASSUMPTION: Overtraining reduces AP. How much?
        # For now, let's say it reduces the penalty by half.
        # This is a GUESS.
        effective_ap = base_ap / 2
        # A better implementation would be:
        # overtrain_bonus = skill_bonus - threshold
        # reduction_factor = 1.0 - (overtrain_bonus * 0.01) # e.g. 1% per bonus pt
        # effective_ap = base_ap * reduction_factor
        
    # 5. Calculate Evade Hindrance Factor
    # "penalty equal to 1/2 of the action penalty"
    # Example: AP of -20 -> -10% penalty -> 0.9 factor
    # Formula: 1.0 + (EffectiveAP / 2.0 / 100.0)
    hindrance_factor = 1.0 + (effective_ap / 200.0)
    
    return max(0.0, hindrance_factor) # Clamp at 0, can't be negative
# ---
# --- END MODIFIED FUNCTION ---
# ---

# --- ( _get_weapon_type is unchanged) ---
def _get_weapon_type(weapon_item_data: dict | None) -> str:
# ... (function contents unchanged) ...
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
        return "runestaff" # ASSUMPTION: All staves are runestaves
    if skill in ["brawling"]:
        return "brawling"
        
    return "1H" # Default

# ---
# --- MODIFIED: calculate_evade_defense ---
# ---
def calculate_evade_defense(defender_stats: dict, defender_skills: dict, defender_race: str, 
                            armor_data: dict | None, shield_data: dict | None, 
                            stance_percent: float, is_ranged_attack: bool) -> int:
    """Calculates the Evade component of DS."""
    
    # [Base Value] = [Dodging Ranks] + AGI Bonus + floor(INT Bonus / 4)
    dodging_ranks = defender_skills.get("dodging", 0)
    agi_bonus = get_stat_bonus(defender_stats.get("AGI", 50), "AGI", defender_race)
    int_bonus = get_stat_bonus(defender_stats.get("INT", 50), "INT", defender_race)
    
    base_value = dodging_ranks + agi_bonus + math.floor(int_bonus / 4)
    
    # [Armor Hindrance] - NOW USES THE NEW HELPER
    armor_hindrance = _get_armor_hindrance(armor_data, defender_skills)
    
    # [Shield Factor] & [Shield Size Penalty]
    shield_factor = 1.0
    shield_size_penalty = 0
    
    if shield_data:
        # ASSUMPTION: Need a way to get 'item_id' from 'shield_data'
        # This will fail if 'item_id' isn't in the dict.
        # Let's check if it's from get_equipped_item_data, which returns the
        # full item dict from GAME_ITEMS. items.json keys are the item_id.
        # This is a problem. resolve_attack needs to pass the item_id.
        
        # ---
        # HACK: For now, I'll assume all shields are 'starter_small_shield'
        # This needs to be fixed by passing item_id to calculate_ds
        # ---
        shield_id = "starter_small_shield" 
        shield_props = SHIELD_DATA.get(shield_id, DEFAULT_SHIELD_DATA)
        
        shield_factor = shield_props["factor"]
        if not is_ranged_attack:
            shield_size_penalty = shield_props["size_penalty_melee"]

    # [Stance Modifier] = 75% + (Stance / 4)
    stance_modifier = 0.75 + (stance_percent / 4)
    
    ds = (base_value * armor_hindrance * shield_factor - shield_size_penalty) * stance_modifier
    
    # Bonus vs Ranged
    if is_ranged_attack:
        ds *= 1.5
        
    # TODO: Add encumbrance penalty
    
    return math.floor(ds)
# ---
# --- END MODIFIED FUNCTION ---
# ---

# --- (calculate_block_defense is unchanged) ---
def calculate_block_defense(defender_stats: dict, defender_skills: dict, defender_race: str, 
                            shield_data: dict | None, 
                            stance_percent: float, is_ranged_attack: bool) -> int:
# ... (function contents unchanged) ...
    if not shield_data:
        return 0 # Can't block without a shield

    # [Base Value] = [Shield Use Ranks] + floor(STR Bonus / 4) + floor(DEX Bonus / 4)
    shield_ranks = defender_skills.get("shield_use", 0)
    str_bonus = get_stat_bonus(defender_stats.get("STR", 50), "STR", defender_race)
    dex_bonus = get_stat_bonus(defender_stats.get("DEX", 50), "DEX", defender_race)
    
    base_value = shield_ranks + math.floor(str_bonus / 4) + math.floor(dex_bonus / 4)
    
    # [Stance Modifier] = 50% + (Stance / 2)
    stance_modifier = 0.50 + (stance_percent / 2)
    
    # ASSUMPTION: [Shield Enchant Bonus] = 0
    enchant_bonus = 0 
    
    ds = 0
    # HACK: Same assumption as Evade. This needs to be fixed.
    shield_id = "starter_small_shield"
    shield_props = SHIELD_DATA.get(shield_id, DEFAULT_SHIELD_DATA)

    if is_ranged_attack:
        # DS = ([Base Value] * [Ranged Shield Size Mod] + [Shield Size Bonus]) * [Stance Mod] * (2/3) + 20 + [Enchant]
        size_mod = shield_props["size_mod_ranged"]
        size_bonus = shield_props["size_bonus_ranged"]
        ds = (base_value * size_mod + size_bonus) * stance_modifier * (2/3) + 20 + enchant_bonus
    else:
        # DS = [Base Value] * [Shield Size Mod] * [Stance Mod] * (2/3) + 20 + [Enchant]
        size_mod = shield_props["size_mod_melee"]
        ds = (base_value * size_mod) * stance_modifier * (2/3) + 20 + enchant_bonus
        
    return math.floor(ds)

# --- (calculate_parry_defense is unchanged) ---
def calculate_parry_defense(defender_stats: dict, defender_skills: dict, defender_race: str, 
                            weapon_data: dict | None, offhand_data: dict | None, defender_level: int,
                            stance_percent: float, is_ranged_attack: bool) -> int:
# ... (function contents unchanged) ...
    if not weapon_data:
        return 0 # Can't parry with fists (Brawling AS is handled, but not Parry DS)

    # [Stance Bonus] = Stance * 50
    stance_bonus = stance_percent * 50
    
    # ASSUMPTION: [Weapon Enchant Bonus] = 0
    enchant_bonus = 0

    # Base Value components
    str_bonus = get_stat_bonus(defender_stats.get("STR", 50), "STR", defender_race)
    dex_bonus = get_stat_bonus(defender_stats.get("DEX", 50), "DEX", defender_race)
    stat_bonus = math.floor(str_bonus / 4) + math.floor(dex_bonus / 4)
    
    weapon_type = _get_weapon_type(weapon_data)
    weapon_skill_name = weapon_data.get("skill", "brawling")
    weapon_ranks = defender_skills.get(weapon_skill_name, 0)
    
    ds = 0

    # Ranged attacks can only be parried by Runestaves (and a little by other ranged)
    if is_ranged_attack:
        if weapon_type == "runestaff":
            # (DS = ([Base Value] * [Staff Stance Mod] * 1.5)/2 + [Stance Bonus]/2 + [Enchant]/2)
            # This is complex, so we'll call the main melee function and divide
            ds = calculate_parry_defense(defender_stats, defender_skills, defender_race,
                                         weapon_data, offhand_data, defender_level,
                                         stance_percent, is_ranged_attack=False)
            ds = ds / 2 # Halve the total DS vs ranged
        else:
            # "Ranged weapon users receive a small amount of DS vs. ranged attacks"
            ds = 0 # ASSUMPTION: 0 for now
        return math.floor(ds)

    # --- Melee Attack Parry Logic ---
    
    if weapon_type == "1H":
        # DS = [1H Base Value] * [1H Stance Mod] + [Stance Bonus]
        # [1H Base Value] = [Ranks] + ⌊STR/4⌋ + ⌊DEX/4⌋ + [Enchant]/2
        base_value = weapon_ranks + stat_bonus + (enchant_bonus / 2)
        # [1H Stance Mod] = 20% + (Stance/2)
        stance_mod = 0.20 + (stance_percent / 2)
        ds = base_value * stance_mod + stance_bonus

        # Check for Two Weapon Combat (TWC)
        if offhand_data and _get_weapon_type(offhand_data) != "shield":
            # DS = [Base Value] * [Offhand Stance Mod] + [Weapon Type Bonus]
            twc_ranks = defender_skills.get("two_weapon_combat", 0)
            twc_base = twc_ranks + stat_bonus
            # [Offhand Stance Mod] = 10% + Stance/4
            twc_stance_mod = 0.10 + (stance_percent / 4)
            # ASSUMPTION: Weapon Type Bonus = 5 (general)
            twc_bonus = 5 
            ds += (twc_base * twc_stance_mod) + twc_bonus

    elif weapon_type == "2H":
        # DS = [2H Base Value] * [2H Stance Mod] + [Stance Bonus]
        # [2H Base Value] = [Ranks] + ⌊STR/4⌋ + ⌊DEX/4⌋ + [Enchant]
        base_value = weapon_ranks + stat_bonus + enchant_bonus
        # [2H Stance Mod] = 30% + (Stance * 75%)
        stance_mod = 0.30 + (stance_percent * 0.75)
        ds = base_value * stance_mod + stance_bonus

    elif weapon_type == "polearm":
        # DS = [2H Base Value] * [2HPole Stance Mod] + [Stance Bonus] + [Polearm Bonus]
        base_value = weapon_ranks + stat_bonus + enchant_bonus
        # [2HPole Stance Mod] = 27% + (Stance * 67%)
        stance_mod = 0.27 + (stance_percent * 0.67)
        # [Polearm Bonus] = 15 + (Stance * 65)
        polearm_bonus = 15 + (stance_percent * 65)
        ds = (base_value * stance_mod) + stance_bonus + polearm_bonus

    elif weapon_type == "bow":
        # DS = [Base Value] * [Ranged Stance Mod] + [Stance Bonus] + [Enchant]
        # [Base Value] = [Ranks] + [Perception Ranks]/2 + [Ambush Ranks]/2
        # ASSUMPTION: Perception/Ambush ranks not available, using 0
        base_value = weapon_ranks + 0 + 0
        # [Ranged Stance Mod] = 15% + Stance * 30% (short/composite/long bows)
        stance_mod = 0.15 + (stance_percent * 0.30)
        ds = (base_value * stance_mod) + stance_bonus + enchant_bonus

    elif weapon_type == "runestaff":
        # DS = [Base Value] * [Staff Stance Mod] * 1.5 + [Stance Bonus] + [Enchant]
        
        # Calculate Magic Ranks
        magic_ranks = 0
        magic_skills = ["arcane_symbols", "harness_power", "magic_item_use", 
                        "mana_control", "elemental_lore", "sorcerous_lore", 
                        "mental_lore", "spiritual_lore", "theology"]
        for skill in magic_skills:
            magic_ranks += defender_skills.get(skill, 0)
        
        magic_ranks_per_level = magic_ranks / (defender_level if defender_level > 0 else 1)

        # [Parry Ranks]
        parry_ranks = 0
        if magic_ranks_per_level < 4:
            parry_ranks = 10 + (0.15 * magic_ranks)
        elif 4 <= magic_ranks_per_level <= 11:
            parry_ranks = 10 + (1 + 0.1 * (magic_ranks_per_level - 8)) * (defender_level if defender_level > 0 else 1)
        else: # > 11
            parry_ranks = 10 + (1.3 + 0.05 * (magic_ranks_per_level - 11)) * (defender_level if defender_level > 0 else 1)
            
        # [Base Value] = [Parry Ranks] + ⌊STR/4⌋ + ⌊DEX/4⌋
        base_value = parry_ranks + stat_bonus
        # [Staff Stance Mod] = 20% + Stance/2
        stance_mod = 0.20 + (stance_percent / 2)
        ds = (base_value * stance_mod * 1.5) + stance_bonus + enchant_bonus

    return math.floor(ds)

# --- (calculate_defense_strength main function is unchanged) ---
def calculate_defense_strength(defender: Any, 
                               armor_item_data: dict | None, shield_item_data: dict | None,
                               weapon_item_data: dict | None, offhand_item_data: dict | None,
                               is_ranged_attack: bool) -> int:
# ... (function contents unchanged) ...
    
    # Get common defender properties
    if isinstance(defender, Player):
        defender_name = defender.name
        defender_stats = defender.stats
        defender_skills = defender.skills
        defender_race = defender.race
        defender_stance = defender.stance
        defender_level = defender.level
    elif isinstance(defender, dict):
        defender_name = defender.get("name", "Creature")
        defender_stats = defender.get("stats", {})
        defender_skills = defender.get("skills", {})
        defender_race = defender.get("race", "Human")
        defender_stance = defender.get("stance", "neutral")
        defender_level = defender.get("level", 1) # ASSUMPTION: Monsters are level 1
    else:
        return 0 # Invalid defender

    # Get Stance Percentage
    stance_percent = STANCE_PERCENTAGE.get(defender_stance, 0.70) # Default neutral
    
    ds_components_log = []

    # 1. Generic Defense (Spells, Environment, Status)
    # ASSUMPTION: Base generic defense is 0.
    # Statuses like "stunned" (-20) or "prone" (-50) would be added here.
    generic_ds = 0 
    # TODO: Add room/status modifiers (fog, dark, prone, stunned)
    ds_components_log.append(f"Generic({generic_ds})")

    # 2. Evade Defense
    evade_ds = calculate_evade_defense(
        defender_stats, defender_skills, defender_race,
        armor_item_data, shield_item_data, stance_percent, is_ranged_attack
    )
    ds_components_log.append(f"Evade({evade_ds})")

    # 3. Block Defense
    block_ds = calculate_block_defense(
        defender_stats, defender_skills, defender_race,
        shield_item_data, stance_percent, is_ranged_attack
    )
    ds_components_log.append(f"Block({block_ds})")

    # 4. Parry Defense
    parry_ds = calculate_parry_defense(
        defender_stats, defender_skills, defender_race,
        weapon_item_data, offhand_item_data, defender_level,
        stance_percent, is_ranged_attack
    )
    ds_components_log.append(f"Parry({parry_ds})")
    
    # Total DS = Generic + Evade + Block + Parry
    final_ds = generic_ds + evade_ds + block_ds + parry_ds

    if config.DEBUG_MODE and getattr(config, 'DEBUG_COMBAT_ROLLS', False):
        print(f"DEBUG DS CALC for {defender_name} (Stance: {defender_stance} ({stance_percent*100}%)): Factors = {' + '.join(ds_components_log)} => Final DS = {final_ds}")
    
    return final_ds


# --- (resolve_attack is unchanged) ---
def resolve_attack(attacker: Any, defender: Any, game_items_global: dict) -> dict:
# ... (function contents unchanged) ...
    is_attacker_player = isinstance(attacker, Player)
    attacker_name = attacker.name if is_attacker_player else attacker.get("name", "Creature")
    attacker_stats = attacker.stats if is_attacker_player else attacker.get("stats", {})
    attacker_skills = attacker.skills if is_attacker_player else attacker.get("skills", {})
    attacker_stance = attacker.stance if is_attacker_player else attacker.get("stance", "neutral")
    attacker_race = get_entity_race(attacker)
    
    if is_attacker_player:
        attacker_weapon_data = attacker.get_equipped_item_data("mainhand", game_items_global)
        attacker.add_field_exp(1)
    else:
        mainhand_id = attacker.get("equipped", {}).get("mainhand")
        attacker_weapon_data = game_items_global.get(mainhand_id) if mainhand_id else None

    # --- THIS IS THE FIX: Check if attack is ranged ---
    attacker_weapon_type = _get_weapon_type(attacker_weapon_data)
    is_ranged_attack = attacker_weapon_type in ["bow"] # TODO: Add crossbows, hurled
    # --- END FIX ---

    is_defender_player = isinstance(defender, Player)
    defender_name = defender.name if is_defender_player else defender.get("name", "Creature")
    # defender_stats = defender.stats if is_defender_player else defender.get("stats", {})
    # defender_skills = defender.skills if is_defender_player else defender.get("skills", {})
    # defender_stance = defender.stance if is_defender_player else defender.get("stance", "neutral")
    # defender_race = get_entity_race(defender)

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
        
    # Check if shield is actually a shield (not a TWC weapon)
    if defender_shield_data and defender_shield_data.get("type") != "shield":
        defender_shield_data = None # It's a weapon, not a shield
        
    # Check if offhand is a TWC weapon (and not a shield)
    if defender_offhand_data and defender_offhand_data.get("type") == "shield":
        defender_offhand_data = None # It's a shield, not a weapon

    attacker_as = calculate_attack_strength(
        attacker_name, attacker_stats, attacker_skills, 
        attacker_weapon_data, defender_armor_type_str,
        attacker_stance, attacker_race
    )
    
    # --- THIS IS THE FIX: Call the new DS calculation ---
    defender_ds = calculate_defense_strength(
        defender, # Pass the full object
        defender_armor_data,
        defender_shield_data,
        defender_weapon_data,   # For parry
        defender_offhand_data,  # For TWC parry
        is_ranged_attack
    )
    # --- END FIX ---
    
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

    results = {
        'hit': False, 'damage': 0, 
        'roll_string': roll_string, 
        'attacker_msg': "", 'defender_msg': "", 'broadcast_msg': ""
    }

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
        
        results['attacker_msg'] = (flavor_msg + f" You hit for **{total_damage}** damage!").format(**msg_vars)
        results['defender_msg'] = (flavor_msg + f" You are hit for **{total_damage}** damage!").format(**msg_vars)
        
        broadcast_flavor_msg = get_flavor_message(msg_key_hit.replace("player", "monster"), d100_roll, combat_roll_result)
        results['broadcast_msg'] = (broadcast_flavor_msg + f" {attacker_name} hits for **{total_damage}** damage!").format(**msg_vars)

    else:
        results['hit'] = False
        flavor_msg = get_flavor_message(msg_key_miss, d100_roll, combat_roll_result)
        
        results['attacker_msg'] = flavor_msg.format(**msg_vars)
        results['defender_msg'] = flavor_msg.format(**msg_vars)
        
        broadcast_flavor_msg = get_flavor_message(msg_key_miss.replace("player", "monster"), d100_roll, combat_roll_result)
        results['broadcast_msg'] = broadcast_flavor_msg.format(**msg_vars)

    return results

# --- (calculate_roundtime, _find_combatant, stop_combat, process_combat_tick are unchanged) ---
def calculate_roundtime(agility: int) -> float:
# ... (function contents unchanged) ...
    agi_bonus_seconds = (agility - 50.0) / 20.0
    return max(2.0, 6.0 - agi_bonus_seconds)
def _find_combatant(entity_id: str) -> Optional[Any]:
# ... (function contents unchanged) ...
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
# ... (function contents unchanged) ...
    game_state.COMBAT_STATE.pop(combatant_id, None)
    game_state.COMBAT_STATE.pop(target_id, None)
def process_combat_tick(broadcast_callback, send_to_player_callback):
# ... (function contents unchanged) ...
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
        
        sid_to_skip = None
        
        if is_attacker_player:
            send_to_player_callback(attacker.name, attack_results['attacker_msg'], "combat_self")
            attacker_info = game_state.ACTIVE_PLAYERS.get(attacker.name.lower())
            if attacker_info:
                sid_to_skip = attacker_info.get("sid")

        if is_defender_player:
            send_to_player_callback(defender.name, attack_results['defender_msg'], "combat_other")
            defender_info = game_state.ACTIVE_PLAYERS.get(defender.name.lower())
            if defender_info:
                sid_to_skip = defender_info.get("sid")
        
        broadcast_callback(room_id, attack_results['broadcast_msg'], "combat_broadcast", skip_sid=sid_to_skip)
        
        broadcast_callback(room_id, attack_results['roll_string'], "combat_roll")

        if attack_results['hit']:
            damage = attack_results['damage']
            
            if is_defender_player:
                defender.hp -= damage
                if defender.hp <= 0:
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
        
        attacker_stats = attacker.stats if is_attacker_player else attacker.get("stats", {})
        rt_seconds = calculate_roundtime(attacker_stats.get("AGI", 50))
        state["next_action_time"] = current_time + rt_seconds