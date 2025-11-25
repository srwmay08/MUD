# mud_backend/core/combat_system.py
import random
import math
import time
from typing import Dict, Any, Optional, TYPE_CHECKING, List

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

from mud_backend.core.game_objects import Player
from mud_backend.core.utils import calculate_skill_bonus, get_stat_bonus
from mud_backend.core.skill_handler import attempt_skill_learning
from mud_backend.core.game_loop import environment
from mud_backend import config

# --- HELPER FUNCTIONS --- (Logging and Utilities)

class CombatLogBuilder:
    PLAYER_MISS_MESSAGES = [
        "   A clean miss.", "   You miss {defender} completely.", "   {defender} avoids the attack!",
        "   An awkward miss.", "   Your attack goes wide."
    ]
    MONSTER_MISS_MESSAGES = [
        "   A clean miss.", "   {attacker} misses {defender} completely.", "   {defender} avoids the attack!",
        "   An awkward miss.", "   The attack goes wide."
    ]
    def __init__(self, attacker_name: str, defender_name: str, weapon_name: str, verb: str):
        self.attacker = attacker_name
        self.defender = defender_name
        self.weapon = weapon_name
        self.verb = verb
        self.verb_npc = self._conjugate(verb)
    def _conjugate(self, verb: str) -> str:
        if verb.endswith(('s', 'sh', 'ch', 'x', 'o')): return verb + "es"
        return verb + "s"
    def get_attempt_message(self, perspective: str) -> str:
        if perspective == 'attacker': return f"You {self.verb} {self.weapon} at {self.defender}!"
        elif perspective == 'defender': return f"{self.attacker} {self.verb_npc} {self.weapon} at you!"
        else: return f"{self.attacker} {self.verb_npc} {self.weapon} at {self.defender}!"
    def get_hit_result_message(self, total_damage: int) -> str:
        return f"   ... and hits for {total_damage} points of damage!"
    def get_broadcast_hit_message(self, perspective: str, total_damage: int) -> str:
        if perspective == 'attacker': return f"You hit {self.defender} for {total_damage} points of damage!"
        else: return f"{self.attacker} hits {self.defender} for {total_damage} points of damage!"
    def get_miss_message(self, perspective: str) -> str:
        if perspective == 'attacker': return random.choice(self.PLAYER_MISS_MESSAGES).format(defender=self.defender)
        elif perspective == 'defender': return random.choice(self.MONSTER_MISS_MESSAGES).format(attacker=self.attacker, defender="you")
        else: return random.choice(self.MONSTER_MISS_MESSAGES).format(attacker=self.attacker, defender=self.defender)
    def get_broadcast_miss_message(self, perspective: str) -> str:
        if perspective == 'attacker': return f"You miss {self.defender}."
        else: return f"{self.attacker} misses {self.defender}."

def _get_weighted_attack(attack_list: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not attack_list: return None
    total_weight = sum(attack.get("chance", 0) for attack in attack_list)
    if total_weight == 0: return random.choice(attack_list)
    roll = random.uniform(0, total_weight)
    upto = 0
    for attack in attack_list:
        chance = attack.get("chance", 0)
        if upto + chance >= roll: return attack
        upto += chance
    return random.choice(attack_list)

def get_entity_armor_type(entity, game_items_global: dict) -> str:
    if hasattr(entity, 'get_armor_type'): return entity.get_armor_type() 
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

def _get_random_hit_location(combat_rules: dict) -> str: 
    locations = combat_rules.get("hit_locations", ["chest"])
    return random.choice(locations)

def _get_entity_critical_divisor(entity: Any, armor_data: Optional[Dict]) -> int:
    if armor_data: return armor_data.get("critical_divisor", 11) 
    if isinstance(entity, dict): return entity.get("critical_divisor", 5) 
    return 5 

def _get_randomized_crit_rank(base_rank: int) -> int:
    if base_rank <= 0: return 0
    if base_rank == 1: return 1
    if base_rank == 2: return random.choice([1, 2])
    if base_rank == 3: return random.choice([2, 3])
    if base_rank == 4: return random.choice([2, 3, 4])
    if base_rank == 5: return random.choice([3, 4, 5])
    if base_rank == 6: return random.choice([3, 4, 5, 6])
    if base_rank == 7: return random.choice([4, 5, 6, 7])
    if base_rank == 8: return random.choice([4, 5, 6, 7, 8])
    return random.choice([5, 6, 7, 8, 9])

def _find_combatant(world: 'World', entity_id: str) -> Optional[Any]:
    player_info = world.get_player_info(entity_id.lower())
    if player_info: return player_info.get("player_obj")
    room_id = world.mob_locations.get(entity_id)
    if room_id:
        room = world.get_active_room_safe(room_id)
        if room:
            with room.lock:
                for obj in room.objects:
                    if obj.get("uid") == entity_id: return obj 
    return None

def _get_critical_result(world: 'World', damage_type: str, location: str, rank: int) -> Dict[str, Any]:
    if rank <= 0: return {"message": "", "extra_damage": 0, "wound_rank": 0}
    if damage_type not in world.game_criticals: damage_type = "slash"
    crit_table = world.game_criticals[damage_type]
    if location not in crit_table:
        location = list(crit_table.keys())[0] if crit_table else "chest"
    location_table = crit_table.get(location, {})
    rank_str = str(min(rank, max([int(k) for k in location_table.keys()] or [1])))
    result = location_table.get(rank_str, {"message": "A solid hit!", "extra_damage": 1, "wound_rank": 1})
    result.setdefault("stun", False)
    result.setdefault("fatal", False)
    return result

def _get_stat_modifiers(entity: Any) -> Dict[str, int]:
    return entity.stat_modifiers if isinstance(entity, Player) else {}

# --- CALCULATION FUNCTIONS ---

def calculate_attack_strength(attacker: Any, attacker_stats: dict, attacker_skills: dict,
                              weapon_item_data: dict | None,
                              attacker_stance: str, 
                              attacker_modifiers: dict,
                              combat_rules: dict) -> int:
    """
    AS = STR Bonus + (Skill Bonus * Stance_Factor) + (CM / 2) + Enchant + Buffs
    """
    as_val = 0
    
    # 1. Strength Bonus
    strength_stat = attacker_stats.get("STR", 50)
    as_val += get_stat_bonus(strength_stat, "STR", attacker_modifiers)
    
    # 2. Weapon Skill Bonus (Scaled by Stance)
    stance_mods = combat_rules.get("stance_modifiers", {})
    stance_data = stance_mods.get(attacker_stance, stance_mods.get("creature", {}))
    skill_factor = stance_data.get("weapon_skill_factor", 1.0)

    skill_bonus = 0
    if not weapon_item_data or weapon_item_data.get("item_type") != "weapon": 
        # Brawling
        brawling_rank = attacker_skills.get("brawling", 0)
        skill_bonus = calculate_skill_bonus(brawling_rank)
        base_barehanded = getattr(config, 'BAREHANDED_BASE_AS', 0)
        as_val += base_barehanded
    else:
        # Armed
        skill_name = weapon_item_data.get("skill")
        if skill_name:
            skill_rank = attacker_skills.get(skill_name, 0)
            skill_bonus = calculate_skill_bonus(skill_rank)
    
    # Apply Stance Factor (Offensive=1.0, Defensive=0.5)
    as_val += math.floor(skill_bonus * skill_factor)
    
    # 3. Combat Maneuvers (CM / 2)
    cman_ranks = attacker_skills.get("combat_maneuvers", 0)
    as_val += math.floor(cman_ranks / 2)
    
    # 4. Weapon Enchantment
    if weapon_item_data:
        as_val += weapon_item_data.get("enchantment", 0)

    # 5. Buffs (AS Bonus)
    buffs = attacker.buffs if isinstance(attacker, Player) else attacker.get("buffs", {})
    for buff in buffs.values():
        if buff.get("type") == "as_bonus":
            as_val += buff.get("val", 0)

    return max(0, as_val)

def _get_posture_status_factor(entity_posture: str, status_effects: list, combat_rules: dict) -> float:
    """Calculates the multiplier for Evade/Block/Parry based on posture/status."""
    factor = 1.0
    
    # Posture Factor (e.g., Prone = 0.5)
    p_mods = combat_rules.get("posture_modifiers", {})
    p_data = p_mods.get(entity_posture, p_mods.get("standing", {}))
    factor *= p_data.get("defense_factor", 1.0)
    
    # Status Factor (e.g., Stunned = 0.5, Immobilized = 0.0)
    s_mods = combat_rules.get("status_modifiers", {})
    for effect in status_effects:
        if effect in s_mods:
            factor *= s_mods[effect].get("defense_factor", 1.0)
            
    return factor

def calculate_generic_defense(defender: Any, combat_rules: dict) -> int:
    """Calculates Generic DS: Spells + Environment + Status Penalties."""
    ds = 0
    
    # 1. Active Spells (Buffs)
    buffs = defender.buffs if isinstance(defender, Player) else defender.get("buffs", {})
    for buff in buffs.values():
        if buff.get("type") == "ds_bonus":
            ds += buff.get("val", 0)
            
    # 2. Environment
    # We need to check the room. Using a simpler logic: Environment.current_weather/time?
    # Or passing in lighting. For now, assuming "average" if not implemented.
    # (In a full implementation, pass room brightness here)
    env_mods = combat_rules.get("environmental_modifiers", {})
    # Default to average (0)
    ds += env_mods.get("average", 0) 

    # 3. Status/Posture Penalties (Flat DS reduction)
    posture = defender.posture if isinstance(defender, Player) else defender.get("posture", "standing")
    status_effects = defender.status_effects if isinstance(defender, Player) else defender.get("status_effects", [])
    
    p_mods = combat_rules.get("posture_modifiers", {})
    ds += p_mods.get(posture, {}).get("ds_penalty", 0)
    
    s_mods = combat_rules.get("status_modifiers", {})
    for effect in status_effects:
        ds += s_mods.get(effect, {}).get("ds_penalty", 0)
        
    return ds

def calculate_evade_defense(defender_stats: dict, defender_skills: dict, defender_modifiers: dict,
                            armor_data: dict | None, shield_data: dict | None,
                            stance_percent: int, factor_mod: float, is_ranged: bool,
                            combat_rules: dict) -> int:
    # Base Evade: Agility + (Int/4) + Dodging Ranks
    agi_b = get_stat_bonus(defender_stats.get("AGI", 50), "AGI", defender_modifiers)
    int_b = get_stat_bonus(defender_stats.get("INT", 50), "INT", defender_modifiers)
    dodging_ranks = defender_skills.get("dodging", 0)
    
    base_evade = agi_b + math.floor(int_b / 4) + dodging_ranks
    
    # Armor Hindrance
    hindrance = _get_armor_hindrance(armor_data, defender_skills)
    
    # Shield Penalty
    shield_penalty = 0 # Simplified for now
    
    # Total Evade = (Base + ShieldPenalty) * Hindrance * Stance% * StatusFactor
    evade_ds = (base_evade - shield_penalty) * hindrance * (stance_percent / 100.0) * factor_mod
    
    if is_ranged: evade_ds *= 1.5 # Easier to dodge ranged
    return math.floor(evade_ds)

def calculate_block_defense(defender_stats: dict, defender_skills: dict, defender_modifiers: dict,
                            shield_data: dict | None, stance_percent: int, factor_mod: float,
                            is_ranged: bool, combat_rules: dict) -> int:
    if not shield_data: return 0
    
    # Base Block: Shield Ranks + (STR/4) + (DEX/4)
    shield_ranks = defender_skills.get("shield_use", 0)
    str_b = get_stat_bonus(defender_stats.get("STR", 50), "STR", defender_modifiers)
    dex_b = get_stat_bonus(defender_stats.get("DEX", 50), "DEX", defender_modifiers)
    
    base_block = shield_ranks + math.floor(str_b / 4) + math.floor(dex_b / 4)
    
    # Shield Size Mods
    shield_rules = combat_rules.get("shield_data", {}).get("small_wooden_shield", {})
    size_mod = shield_rules.get("size_mod_ranged", 1.2) if is_ranged else shield_rules.get("size_mod_melee", 1.0)
    
    # Total Block = Base * SizeMod * Stance% * StatusFactor
    block_ds = base_block * size_mod * (stance_percent / 100.0) * factor_mod
    return math.floor(block_ds)

def calculate_parry_defense(defender_stats: dict, defender_skills: dict, defender_modifiers: dict,
                            weapon_data: dict | None, defender_level: int,
                            stance_percent: int, factor_mod: float, is_ranged: bool) -> int:
    if is_ranged: return 0 # Cannot parry arrows usually (unless monk/special)
    
    # Base Parry: Weapon Ranks + (STR/4) + (DEX/4) + Enchant? (Usually weapon enchant helps parry)
    skill_name = weapon_data.get("skill", "brawling") if weapon_data else "brawling"
    weapon_ranks = defender_skills.get(skill_name, 0)
    
    str_b = get_stat_bonus(defender_stats.get("STR", 50), "STR", defender_modifiers)
    dex_b = get_stat_bonus(defender_stats.get("DEX", 50), "DEX", defender_modifiers)
    
    base_parry = weapon_ranks + math.floor(str_b / 4) + math.floor(dex_b / 4)
    
    if weapon_data:
        base_parry += weapon_data.get("enchantment", 0)
        
    weapon_type = _get_weapon_type(weapon_data)
    handedness_mod = 1.5 if weapon_type == "2H" else 1.0
    
    # Total Parry = Base * HandMod * Stance% * StatusFactor
    parry_ds = base_parry * handedness_mod * (stance_percent / 100.0) * factor_mod
    return math.floor(parry_ds)

def calculate_defense_strength(defender: Any,
                               armor_item_data: dict | None, shield_item_data: dict | None,
                               weapon_item_data: dict | None, offhand_item_data: dict | None,
                               is_ranged_attack: bool, defender_stance: str,
                               defender_modifiers: dict,
                               combat_rules: dict) -> int:
    
    if isinstance(defender, Player):
        stats, skills, posture, level = defender.stats, defender.skills, defender.posture, defender.level
        status_effects = defender.status_effects
    elif isinstance(defender, dict):
        stats, skills, posture, level = defender.get("stats",{}), defender.get("skills",{}), defender.get("posture","standing"), defender.get("level",1)
        status_effects = defender.get("status_effects", [])
    else: return 0
    
    # 1. Get Stance Percent (0-100)
    stance_mods = combat_rules.get("stance_modifiers", {})
    stance_data = stance_mods.get(defender_stance, stance_mods.get("creature", {}))
    stance_percent = stance_data.get("percent", 50)
    
    # 2. Get Status Factor (multiplier for E/B/P)
    factor_mod = _get_posture_status_factor(posture, status_effects, combat_rules)
    
    # 3. Calculate Components
    evade_ds = calculate_evade_defense(stats, skills, defender_modifiers, armor_item_data, shield_item_data, stance_percent, factor_mod, is_ranged_attack, combat_rules)
    block_ds = calculate_block_defense(stats, skills, defender_modifiers, shield_item_data, stance_percent, factor_mod, is_ranged_attack, combat_rules)
    parry_ds = calculate_parry_defense(stats, skills, defender_modifiers, weapon_item_data, level, stance_percent, factor_mod, is_ranged_attack)
    generic_ds = calculate_generic_defense(defender, combat_rules)
    
    total_ds = generic_ds + evade_ds + block_ds + parry_ds
    
    return max(0, total_ds)

def calculate_roundtime(agility: int) -> float: return max(3.0, 5.0 - ((agility - 50) / 25))

# --- MAIN RESOLVE FUNCTION ---

def resolve_attack(world: 'World', attacker: Any, defender: Any, game_items_global: dict) -> dict:
    combat_rules = getattr(world, 'game_rules', {})
    if not combat_rules:
        print("[COMBAT ERROR] Combat Rules missing! Using defaults.")

    # --- Setup Attacker Data ---
    is_attacker_player = isinstance(attacker, Player)
    attacker_name = attacker.name if is_attacker_player else attacker.get("name", "Creature")
    attacker_stats = attacker.stats if is_attacker_player else attacker.get("stats", {})
    attacker_skills = attacker.skills if is_attacker_player else attacker.get("skills", {})
    attacker_posture = attacker.posture if is_attacker_player else attacker.get("posture", "standing")
    attacker_stance = attacker.stance if is_attacker_player else attacker.get("stance", "creature")
    attacker_modifiers = _get_stat_modifiers(attacker)

    # --- Setup Defender Data ---
    is_defender_player = isinstance(defender, Player)
    defender_name = defender.name if is_defender_player else defender.get("name", "Creature")
    defender_stance = defender.stance if is_defender_player else defender.get("stance", "creature")
    defender_modifiers = _get_stat_modifiers(defender)
    
    attacker_name_possessive = f"{attacker_name}'s" if not attacker_name.endswith('s') else f"{attacker_name}'"
    
    # --- Equip Setup ---
    if is_defender_player:
        defender_armor_data = defender.get_equipped_item_data("torso")
        defender_shield_data = defender.get_equipped_item_data("offhand")
        defender_weapon_data = defender.get_equipped_item_data("mainhand")
        defender_offhand_data = defender.get_equipped_item_data("offhand")
        defender_armor_type_str = defender.get_armor_type()
    else:
        torso_id = defender.get("equipped", {}).get("torso")
        offhand_id = defender.get("equipped", {}).get("offhand")
        mainhand_id = defender.get("equipped", {}).get("mainhand")
        defender_armor_data = game_items_global.get(torso_id) if torso_id else None
        defender_shield_data = game_items_global.get(offhand_id) if offhand_id else None
        defender_weapon_data = game_items_global.get(mainhand_id) if mainhand_id else None
        defender_offhand_data = game_items_global.get(offhand_id) if offhand_id else None
        defender_armor_type_str = get_entity_armor_type(defender, game_items_global)

    if defender_shield_data and defender_shield_data.get("item_type") != "shield": defender_shield_data = None
    if defender_offhand_data and defender_offhand_data.get("item_type") == "shield": defender_offhand_data = None
        
    selected_attack = None
    attack_list = []
    attacker_weapon_data = None
    
    # --- Weapon & Attack Selection ---
    if is_attacker_player:
        attacker_weapon_data = attacker.get_equipped_item_data("mainhand")
        weapon_skill_to_learn = "brawling"
        if attacker_weapon_data: weapon_skill_to_learn = attacker_weapon_data.get("skill", "brawling")
        attempt_skill_learning(attacker, weapon_skill_to_learn)
        if attacker_weapon_data: attack_list = attacker_weapon_data.get("attacks", [])
        else: attack_list = [{ "verb": "punch", "damage_type": "crush", "weapon_name": "your fist", "chance": 1.0 }]
    else:
        mainhand_id = attacker.get("equipped", {}).get("mainhand")
        attacker_weapon_data = game_items_global.get(mainhand_id) if mainhand_id else None
        if attacker_weapon_data: attack_list = attacker_weapon_data.get("attacks", [])
        else: attack_list = attacker.get("attacks", [])
        
    if not attack_list: attack_list = [{ "verb": "attack", "damage_type": "crush", "weapon_name": "something", "chance": 1.0 }]
    selected_attack = _get_weighted_attack(attack_list)
    if not selected_attack: selected_attack = attack_list[0]

    attack_verb = selected_attack.get("verb", "attack")
    weapon_damage_type = selected_attack.get("damage_type", "crush")
    weapon_damage_factor = 0.100
    broadcast_weapon_display = "" 

    # --- Determine AvD Bonus (Attack vs Defense) ---
    avd_bonus = 0
    if attacker_weapon_data:
        weapon_damage_factor = attacker_weapon_data.get("damage_factors", {}).get(defender_armor_type_str, 0.100)
        avd_mods = attacker_weapon_data.get("avd_modifiers", {})
        avd_bonus = avd_mods.get(defender_armor_type_str, avd_mods.get(config.DEFAULT_UNARMORED_TYPE, 0))
        
        if is_attacker_player: broadcast_weapon_display = f"your {attacker_weapon_data.get('name', 'weapon')}"
        else: broadcast_weapon_display = f"{attacker_name_possessive} {attacker_weapon_data.get('name', 'weapon')}"
    else:
        if is_attacker_player: 
            broadcast_weapon_display = "your fist"
        else: 
            broadcast_weapon_display = selected_attack.get("weapon_name", f"{attacker_name_possessive} fist")
            
        damage_factors = attacker.get("damage_factors", {}) if not is_attacker_player else {}
        weapon_damage_factor = damage_factors.get(defender_armor_type_str, 0.100)
        
        avd_mods = attacker.get("avd_modifiers", {})
        avd_bonus = avd_mods.get(defender_armor_type_str, 0)

    attacker_weapon_type = _get_weapon_type(attacker_weapon_data)
    is_ranged_attack = attacker_weapon_type in ["bow"]

    # --- CALCULATE AS/DS ---
    attacker_as = calculate_attack_strength(
        attacker, attacker_stats, attacker_skills, 
        attacker_weapon_data, 
        attacker_stance, # Posture doesn't affect AS in standard GSIV usually, stance does
        attacker_modifiers,
        combat_rules
    )
    
    defender_ds = calculate_defense_strength(
        defender, defender_armor_data, defender_shield_data, 
        defender_weapon_data, defender_offhand_data, 
        is_ranged_attack, defender_stance, 
        defender_modifiers,
        combat_rules
    )

    # --- COMBAT ROLL ---
    # Result = (AS + AvD) - DS + d100
    d100_roll = random.randint(1, 100)
    combat_roll_result = (attacker_as + avd_bonus) - defender_ds + d100_roll 

    as_str = f"+{attacker_as}" if attacker_as >= 0 else str(attacker_as)
    avd_str = f"+{avd_bonus}" if avd_bonus >= 0 else str(avd_bonus)
    ds_str = f"-{defender_ds}" 
    
    roll_string = (f"  AS: {as_str} + AvD: {avd_str} + d100: +{d100_roll} - DS: {defender_ds} = {combat_roll_result}")
    
    log_builder = CombatLogBuilder(attacker_name, defender_name, broadcast_weapon_display, attack_verb)
    results = {'hit': False, 'damage': 0, 'attempt_msg': "", 'defender_attempt_msg': "", 'broadcast_attempt_msg': "", 'roll_string': roll_string, 'result_msg': "", 'broadcast_result_msg': "", 'critical_msg': "", 'is_fatal': False}

    if is_attacker_player:
        results['attempt_msg'] = log_builder.get_attempt_message('attacker')
        results['broadcast_attempt_msg'] = log_builder.get_attempt_message('room')
    else:
        results['attempt_msg'] = log_builder.get_attempt_message('defender')
        results['broadcast_attempt_msg'] = log_builder.get_attempt_message('room')

    if combat_roll_result > config.COMBAT_HIT_THRESHOLD:
        results['hit'] = True
        endroll_success_margin = combat_roll_result - config.COMBAT_HIT_THRESHOLD
        raw_damage = max(1, endroll_success_margin * weapon_damage_factor) 
        critical_divisor = _get_entity_critical_divisor(defender, defender_armor_data)
        base_crit_rank = math.trunc(raw_damage / critical_divisor)
        final_crit_rank = _get_randomized_crit_rank(base_crit_rank)
        
        hit_location = _get_random_hit_location(combat_rules)
        
        crit_result = _get_critical_result(world, weapon_damage_type, hit_location, final_crit_rank)
        extra_damage = crit_result["extra_damage"]
        total_damage = math.trunc(raw_damage) + extra_damage
        results['damage'] = total_damage
        results['is_fatal'] = crit_result.get("fatal", False)
        
        wound_rank = crit_result.get("wound_rank", 0)
        if is_defender_player and wound_rank > 0:
            existing_wound = defender.wounds.get(hit_location, 0)
            if wound_rank > existing_wound: defender.wounds[hit_location] = wound_rank
        
        results['result_msg'] = log_builder.get_hit_result_message(total_damage)
        if is_attacker_player: results['broadcast_result_msg'] = log_builder.get_broadcast_hit_message('attacker', total_damage)
        else: results['broadcast_result_msg'] = log_builder.get_broadcast_hit_message('room', total_damage)
        
        crit_msg = crit_result.get("message", "").format(defender=defender_name)
        if crit_msg: results['critical_msg'] = f"   {crit_msg}"
    else:
        results['hit'] = False
        if is_attacker_player:
            results['result_msg'] = log_builder.get_miss_message('attacker')
            results['broadcast_result_msg'] = log_builder.get_broadcast_miss_message('attacker')
        else:
            results['result_msg'] = log_builder.get_miss_message('defender')
            results['broadcast_result_msg'] = log_builder.get_broadcast_miss_message('room')
    return results

def stop_combat(world: 'World', combatant_id: str, target_id: str):
    world.stop_combat_for_all(combatant_id, target_id)

def process_combat_tick(world: 'World', broadcast_callback, send_to_player_callback, send_vitals_callback):
    current_time = time.time()
    combatant_list = world.get_all_combat_states()

    for combatant_id, state in combatant_list:
        if state.get("state_type") != "combat": continue
        if not world.get_combat_state(combatant_id): continue
        if current_time < state["next_action_time"]: continue

        attacker = _find_combatant(world, combatant_id)
        defender = _find_combatant(world, state["target_id"])
        attacker_room_id = state.get("current_room_id")

        if not attacker or not defender or not attacker_room_id:
            world.stop_combat_for_all(combatant_id, state["target_id"])
            continue

        if isinstance(attacker, Player): continue 

        is_defender_player = isinstance(defender, Player)
        defender_room_id = None
        if is_defender_player:
            defender_room_id = defender.current_room_id
        else:
            defender_state = world.get_combat_state(state["target_id"])
            if defender_state: defender_room_id = defender_state.get("current_room_id")
            else: 
                loc = world.mob_locations.get(state["target_id"])
                if loc: defender_room_id = loc

        if attacker_room_id != defender_room_id:
            world.remove_combat_state(combatant_id) 
            continue

        attack_results = resolve_attack(world, attacker, defender, game_items_global=world.game_items)

        sid_to_skip = None
        if is_defender_player:
            send_to_player_callback(defender.name, attack_results['attempt_msg'], "message")
            send_to_player_callback(defender.name, attack_results['roll_string'], "message")
            send_to_player_callback(defender.name, attack_results['result_msg'], "message")
            if attack_results['hit'] and attack_results['critical_msg']:
                 send_to_player_callback(defender.name, attack_results['critical_msg'], "message")
            defender_info = world.get_player_info(defender.name.lower())
            if defender_info: sid_to_skip = defender_info.get("sid")
        
        broadcast_msg = attack_results['broadcast_attempt_msg']
        if attack_results['hit']:
            broadcast_msg = attack_results['broadcast_result_msg']
            if attack_results['critical_msg']: broadcast_msg += f"\n{attack_results['critical_msg']}"
        else:
            broadcast_msg += f"\n{attack_results['broadcast_result_msg']}"
        
        broadcast_callback(attacker_room_id, broadcast_msg, "combat_broadcast", skip_sid=sid_to_skip)

        if attack_results['hit']:
            damage = attack_results['damage']
            is_fatal = attack_results['is_fatal']
            
            if is_defender_player:
                defender.hp -= damage
                if defender.hp <= 0 or is_fatal:
                    if is_fatal and defender.hp > 0: send_to_player_callback(defender.name, "The world goes black as you suffer a fatal wound...", "combat_death")
                    defender.hp = 0
                    vitals_data = defender.get_vitals()
                    send_vitals_callback(defender.name, vitals_data)
                    consequence_msg = f"**{defender.name} has been DEFEATED!**"
                    send_to_player_callback(defender.name, consequence_msg, "combat_death")
                    broadcast_callback(attacker_room_id, consequence_msg, "combat_death", skip_sid=sid_to_skip)
                    defender.move_to_room(config.PLAYER_DEATH_ROOM_ID, "You have been slain... You awaken on a cold stone altar, feeling weak.")
                    defender.deaths_recent = min(5, defender.deaths_recent + 1)
                    con_loss = min(3 + defender.deaths_recent, 25 - defender.con_lost)
                    if con_loss > 0:
                        defender.stats["CON"] = defender.stats.get("CON", 50) - con_loss
                        defender.con_lost += con_loss
                        send_to_player_callback(defender.name, f"You have lost {con_loss} Constitution.", "system_error")
                    defender.death_sting_points += 2000
                    send_to_player_callback(defender.name, "You feel the sting of death... (XP gain is reduced)", "system_error")
                    defender.posture = "prone"
                    save_game_state(defender)
                    continue
                else:
                    vitals_data = defender.get_vitals()
                    send_vitals_callback(defender.name, vitals_data)
                    send_to_player_callback(defender.name, f"(You have {defender.hp}/{defender.max_hp} HP remaining)", "system_info")
                    save_game_state(defender)
            else: 
                defender_uid = defender.get("uid")
                new_hp = world.modify_monster_hp(defender_uid, defender.get("max_hp", 1), damage)
                if new_hp <= 0 or is_fatal:
                    consequence_msg = f"**The {defender['name']} has been DEFEATED!**"
                    broadcast_callback(attacker_room_id, consequence_msg, "combat_death", skip_sid=sid_to_skip)
                    corpse_data = loot_system.create_corpse_object_data(defender, defender_uid, world.game_items, world.game_loot_tables, {})
                    active_room = world.get_active_room_safe(attacker_room_id)
                    if active_room:
                        with active_room.lock:
                            active_room.objects.append(corpse_data)
                            active_room.objects = [obj for obj in active_room.objects if obj.get("uid") != defender_uid]
                        world.save_room(active_room)
                    broadcast_callback(attacker_room_id, f"The {corpse_data['name']} falls to the ground.", "ambient")
                    respawn_time = defender.get("respawn_time_seconds", 300)
                    respawn_chance = defender.get("respawn_chance_per_tick", getattr(config, "NPC_DEFAULT_RESPAWN_CHANCE", 0.2))
                    world.set_defeated_monster(defender_uid, {
                        "room_id": attacker_room_id,
                        "template_key": defender.get("monster_id"), 
                        "type": "npc" if defender.get("is_npc") else "monster",
                        "eligible_at": current_time + respawn_time,
                        "chance": respawn_chance,
                        "faction": defender.get("faction")
                    })
                    world.stop_combat_for_all(combatant_id, state["target_id"])
                    continue 

        rt_seconds = calculate_roundtime(attacker.get("stats", {}).get("AGI", 50))
        data = world.get_combat_state(combatant_id)
        if data:
            data["next_action_time"] = current_time + rt_seconds
            data["duration"] = rt_seconds 
            world.set_combat_state(combatant_id, data)