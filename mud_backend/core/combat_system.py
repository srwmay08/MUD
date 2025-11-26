# mud_backend/core/combat_system.py
import random
import math
import time
from typing import Dict, Any, Optional, TYPE_CHECKING, List

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

from mud_backend.core.game_objects import Player
from mud_backend.core.db import save_game_state
from mud_backend.core import loot_system
from mud_backend.core.utils import calculate_skill_bonus, get_stat_bonus
from mud_backend.core.skill_handler import attempt_skill_learning
from mud_backend.core.game_loop import environment
from mud_backend import config

# --- HELPER FUNCTIONS --- (Unchanged log builder)
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

# --- ROUNDTIME ---
def calculate_roundtime_twc(attacker_stats: dict, main_weapon: dict, off_weapon: dict) -> float:
    right_base = main_weapon.get("base_speed", 3) if main_weapon else 0
    left_base = off_weapon.get("base_speed", 3) if off_weapon else 0
    left_weight = off_weapon.get("weight", 3) if off_weapon else 0
    
    str_stat = attacker_stats.get("STR", 50)
    str_bonus = get_stat_bonus(str_stat, "STR", {})
    
    str_offset = math.trunc((str_bonus + 10) / 15)
    weight_penalty = max(0, min(left_weight - 2 - str_offset, 3))
    
    twc_base = right_base + max(left_base - 2, 0) + weight_penalty
    
    agi_stat = attacker_stats.get("AGI", 50)
    rt_reduction = (agi_stat - 50) / 25
    
    return max(3.0, twc_base - rt_reduction)

def calculate_roundtime(agility: int, weapon_base_speed: int = 3) -> float: 
    return max(3.0, float(weapon_base_speed + 2) - ((agility - 50) / 25))


# --- ATTACK STRENGTH (AS) ---

def calculate_bolt_as(attacker: Any, attacker_stats: dict, attacker_skills: dict, 
                      attacker_modifiers: dict, combat_rules: dict) -> int:
    """
    Calculates Bolt AS: DEX Bonus + Spell Aiming + Modifiers.
    """
    as_val = 0
    
    # 1. DEX Bonus
    dex_stat = attacker_stats.get("DEX", 50)
    dex_bonus = get_stat_bonus(dex_stat, "DEX", attacker_modifiers)
    as_val += dex_bonus
    
    # 2. Spell Aiming Skill
    skill_rank = attacker_skills.get("spell_aiming", 0)
    skill_bonus = calculate_skill_bonus(skill_rank)
    as_val += skill_bonus
    
    # 3. Buffs (AS Bonus)
    buffs = attacker.buffs if isinstance(attacker, Player) else attacker.get("buffs", {})
    for buff in buffs.values():
        if buff.get("type") == "as_bonus":
            as_val += buff.get("val", 0)
            
    return max(0, as_val)

def calculate_attack_strength(attacker: Any, attacker_stats: dict, attacker_skills: dict,
                              weapon_item_data: dict | None,
                              attacker_stance: str, 
                              attacker_modifiers: dict,
                              combat_rules: dict,
                              hand: str = "main") -> int:
    """
    Calculates AS for Melee, Ranged, Thrown, and TWC.
    """
    as_val = 0
    strength_stat = attacker_stats.get("STR", 50)
    str_bonus = get_stat_bonus(strength_stat, "STR", attacker_modifiers)
    dex_stat = attacker_stats.get("DEX", 50)
    dex_bonus = get_stat_bonus(dex_stat, "DEX", attacker_modifiers)

    weapon_skill_name = weapon_item_data.get("skill") if weapon_item_data else "brawling"
    
    # --- 1. RANGED LOGIC (Bows/Crossbows) ---
    if weapon_skill_name in ["bows", "crossbows"]:
        # Formula: [Skill + DEX + (Ambush-40)/4 + (Perception-40)/4 + Enchant] * Stance
        skill_rank = attacker_skills.get(weapon_skill_name, 0)
        skill_bonus = calculate_skill_bonus(skill_rank)
        as_val += skill_bonus
        as_val += dex_bonus
        
        ambush_ranks = attacker_skills.get("ambush", 0)
        perception_ranks = attacker_skills.get("perception", 0)
        if ambush_ranks > 40: as_val += math.floor((ambush_ranks - 40) / 4)
        if perception_ranks > 40: as_val += math.floor((perception_ranks - 40) / 4)
            
        if weapon_item_data: as_val += min(50, weapon_item_data.get("enchantment", 0))
        
        # Kneeling Bonus (Crossbows)
        if weapon_skill_name == "crossbows":
            posture = attacker.posture if isinstance(attacker, Player) else "standing"
            if posture == "kneeling":
                kneel_table = combat_rules.get("ranged_rules", {}).get("crossbow_kneeling_bonus", {})
                as_val += kneel_table.get(attacker_stance, 0)

        # Ranged Stance Multiplier
        ranged_stance_mods = combat_rules.get("ranged_rules", {}).get("as_stance_modifiers", {})
        stance_mod = ranged_stance_mods.get(attacker_stance, 1.0)
        as_val = int(as_val * stance_mod)
        
    # --- 2. THROWN LOGIC ---
    elif weapon_skill_name in ["small_thrown", "large_thrown"]:
        # Formula: [(STR + DEX)/2] + Skill + [(Perception + CM)/4] + Enchant + Stance
        stat_avg = math.floor((str_bonus + dex_bonus) / 2)
        as_val += stat_avg
        
        skill_rank = attacker_skills.get(weapon_skill_name, 0)
        skill_bonus = calculate_skill_bonus(skill_rank)
        as_val += skill_bonus
        
        perc_ranks = attacker_skills.get("perception", 0)
        cman_ranks = attacker_skills.get("combat_maneuvers", 0)
        as_val += math.floor((perc_ranks + cman_ranks) / 4)
        
        if weapon_item_data: as_val += weapon_item_data.get("enchantment", 0)
        
        # Use standard Melee Stance Penalties for thrown
        stance_mods = combat_rules.get("stance_modifiers", {})
        stance_data = stance_mods.get(attacker_stance, stance_mods.get("creature", {"as_penalty": 0}))
        as_val += stance_data.get("as_penalty", 0)

    # --- 3. MELEE LOGIC ---
    else:
        as_val += str_bonus # STR Bonus
        
        skill_bonus = 0
        skill_rank = 0
        if not weapon_item_data or weapon_item_data.get("item_type") != "weapon": 
            skill_rank = attacker_skills.get("brawling", 0)
            base_barehanded = getattr(config, 'BAREHANDED_BASE_AS', 0)
            as_val += base_barehanded
        else:
            skill_rank = attacker_skills.get(weapon_skill_name, 0)
        
        skill_bonus = calculate_skill_bonus(skill_rank)
        
        # TWC Offhand check
        if hand == "off":
            twc_rank = attacker_skills.get("two_weapon_combat", 0)
            twc_bonus = calculate_skill_bonus(twc_rank)
            combined_skill = (0.6 * skill_bonus) + (0.4 * twc_bonus)
            as_val += math.floor(combined_skill)
            
            # Cap check: Offhand limited by DEX if STR > DEX
            if str_bonus > dex_bonus:
                as_val -= str_bonus
                as_val += dex_bonus
        else:
            as_val += skill_bonus # Full skill
        
        # Stance Factor on Skill
        stance_mods = combat_rules.get("stance_modifiers", {})
        stance_data = stance_mods.get(attacker_stance, stance_mods.get("creature", {}))
        skill_factor = stance_data.get("weapon_skill_factor", 1.0)
        
        # Adjust skill portion by stance factor (remove full, add factored)
        # Note: This assumes skill_bonus was fully added above.
        # For TWC, we added a combined skill. We apply factor to THAT.
        # For Main, we added skill_bonus.
        # Simplification: Re-calculate total so far, find difference... 
        # Actually, cleaner to just apply factor to the skill component directly before adding.
        # But we already added it. So subtract and re-add.
        # ... Wait, simpler:
        # For TWC: as_val has stat + combined_skill. 
        # For Main: as_val has stat + skill_bonus.
        # Let's just do:
        # as_val -= current_skill_contribution
        # as_val += math.floor(current_skill_contribution * skill_factor)
        
        current_skill_contrib = math.floor((0.6 * skill_bonus) + (0.4 * calculate_skill_bonus(attacker_skills.get("two_weapon_combat", 0)))) if hand == "off" else skill_bonus
        as_val -= current_skill_contrib
        as_val += math.floor(current_skill_contrib * skill_factor)

        # CM / 2
        cman_ranks = attacker_skills.get("combat_maneuvers", 0)
        as_val += math.floor(cman_ranks / 2)
        
        if weapon_item_data:
            as_val += weapon_item_data.get("enchantment", 0)

        # Stance Penalty
        as_val += stance_data.get("as_penalty", 0)

    # Buffs (Common)
    buffs = attacker.buffs if isinstance(attacker, Player) else attacker.get("buffs", {})
    for buff in buffs.values():
        if buff.get("type") == "as_bonus":
            as_val += buff.get("val", 0)

    return max(0, as_val)

# --- DEFENSE STRENGTH (DS) ---
# (All DS functions remain unchanged from previous successful iteration)

def _get_posture_status_factor(entity_posture: str, status_effects: list, combat_rules: dict) -> float:
    factor = 1.0
    p_mods = combat_rules.get("posture_modifiers", {})
    p_data = p_mods.get(entity_posture, p_mods.get("standing", {}))
    factor *= p_data.get("defense_factor", 1.0)
    s_mods = combat_rules.get("status_modifiers", {})
    for effect in status_effects:
        if effect in s_mods: factor *= s_mods[effect].get("defense_factor", 1.0)
    return factor

def calculate_generic_defense(defender: Any, combat_rules: dict) -> int:
    ds = 0
    buffs = defender.buffs if isinstance(defender, Player) else defender.get("buffs", {})
    for buff in buffs.values():
        if buff.get("type") == "ds_bonus": ds += buff.get("val", 0)
    env_mods = combat_rules.get("environmental_modifiers", {})
    ds += env_mods.get("average", 0) 
    posture = defender.posture if isinstance(defender, Player) else defender.get("posture", "standing")
    status_effects = defender.status_effects if isinstance(defender, Player) else defender.get("status_effects", [])
    p_mods = combat_rules.get("posture_modifiers", {})
    ds += p_mods.get(posture, {}).get("ds_penalty", 0)
    s_mods = combat_rules.get("status_modifiers", {})
    for effect in status_effects: ds += s_mods.get(effect, {}).get("ds_penalty", 0)
    return ds

def calculate_evade_defense(defender_stats: dict, defender_skills: dict, defender_modifiers: dict,
                            armor_data: dict | None, shield_data: dict | None,
                            stance_percent: int, factor_mod: float, is_ranged: bool,
                            combat_rules: dict) -> int:
    agi_b = get_stat_bonus(defender_stats.get("AGI", 50), "AGI", defender_modifiers)
    int_b = get_stat_bonus(defender_stats.get("INT", 50), "INT", defender_modifiers)
    dodging_ranks = defender_skills.get("dodging", 0)
    base_evade = agi_b + math.floor(int_b / 4) + dodging_ranks
    hindrance = _get_armor_hindrance(armor_data, defender_skills)
    shield_penalty = 0 
    evade_ds = (base_evade - shield_penalty) * hindrance * (stance_percent / 100.0) * factor_mod
    if is_ranged: evade_ds *= 1.5 
    return math.floor(evade_ds)

def calculate_block_defense(defender_stats: dict, defender_skills: dict, defender_modifiers: dict,
                            shield_data: dict | None, stance_percent: int, factor_mod: float,
                            is_ranged: bool, combat_rules: dict) -> int:
    if not shield_data: return 0
    shield_ranks = defender_skills.get("shield_use", 0)
    str_b = get_stat_bonus(defender_stats.get("STR", 50), "STR", defender_modifiers)
    dex_b = get_stat_bonus(defender_stats.get("DEX", 50), "DEX", defender_modifiers)
    base_block = shield_ranks + math.floor(str_b / 4) + math.floor(dex_b / 4)
    shield_rules = combat_rules.get("shield_data", {}).get("small_wooden_shield", {})
    size_mod = shield_rules.get("size_mod_ranged", 1.2) if is_ranged else shield_rules.get("size_mod_melee", 1.0)
    block_ds = base_block * size_mod * (stance_percent / 100.0) * factor_mod
    return math.floor(block_ds)

def calculate_parry_defense(defender_stats: dict, defender_skills: dict, defender_modifiers: dict,
                            weapon_data: dict | None, offhand_data: dict | None, defender_level: int,
                            stance_percent: int, factor_mod: float, is_ranged: bool,
                            defender_stance: str, combat_rules: dict) -> int:
    
    weapon_skill = weapon_data.get("skill", "brawling") if weapon_data else "brawling"
    
    if is_ranged: 
        if weapon_skill in ["bows", "crossbows", "staves"]:
             enchant = weapon_data.get("enchantment", 0) if weapon_data else 0
             return math.floor(enchant / 2) 
        return 0
    
    # Ranged Weapon Parry
    if weapon_skill in ["bows", "crossbows"]:
        ranged_rules = combat_rules.get("ranged_rules", {})
        skill_ranks = defender_skills.get(weapon_skill, 0)
        skill_val = calculate_skill_bonus(skill_ranks)
        perc_ranks = defender_skills.get("perception", 0)
        ambush_ranks = defender_skills.get("ambush", 0)
        base_val = skill_val + math.trunc(perc_ranks / 2) + math.trunc(ambush_ranks / 2)
        weapon_type_key = "crossbow" if weapon_skill == "crossbows" else "bow"
        stance_mod = ranged_rules.get("ds_stance_modifiers", {}).get(weapon_type_key, {}).get(defender_stance, 0.0)
        enchant = weapon_data.get("enchantment", 0) if weapon_data else 0
        stance_bonus = ranged_rules.get("ds_stance_bonus", {}).get(defender_stance, 0)
        parry_ds = math.floor(base_val * stance_mod) + enchant + stance_bonus
        return math.floor(parry_ds * factor_mod)

    # Polearm Parry
    if weapon_skill == "polearms":
        polearm_rules = combat_rules.get("polearm_rules", {})
        weapon_ranks = defender_skills.get("polearms", 0)
        str_b = get_stat_bonus(defender_stats.get("STR", 50), "STR", defender_modifiers)
        dex_b = get_stat_bonus(defender_stats.get("DEX", 50), "DEX", defender_modifiers)
        enchant = weapon_data.get("enchantment", 0) if weapon_data else 0
        is_penalty_grip = (offhand_data is not None)
        
        if is_penalty_grip:
            rule_set = polearm_rules.get("1h_grip", {})
            stance_mod = rule_set.get("modifiers", {}).get(defender_stance, 0)
            stance_bonus = rule_set.get("bonuses", {}).get(defender_stance, 0)
            base = weapon_ranks + math.floor(str_b / 4) + math.floor(dex_b / 4) + math.floor(enchant / 2)
            parry_ds = math.floor((base * stance_mod) / 2) + stance_bonus
        else:
            rule_set = polearm_rules.get("2h_grip", {})
            stance_mod = rule_set.get("modifiers", {}).get(defender_stance, 0)
            polearm_bonus = rule_set.get("bonuses", {}).get(defender_stance, 0)
            base = weapon_ranks + math.floor(str_b / 4) + math.floor(dex_b / 4) + enchant
            parry_ds = math.floor(base * stance_mod) + polearm_bonus
        return math.floor(parry_ds * factor_mod)

    # TWC Parry
    is_twc = (offhand_data is not None and offhand_data.get("item_type") == "weapon")
    if is_twc:
        weapon_ranks = defender_skills.get(weapon_skill, 0)
        str_b = get_stat_bonus(defender_stats.get("STR", 50), "STR", defender_modifiers)
        dex_b = get_stat_bonus(defender_stats.get("DEX", 50), "DEX", defender_modifiers)
        enchant = weapon_data.get("enchantment", 0) if weapon_data else 0
        
        # Use Polearm 1H table as standard proxy
        stance_mods_1h = combat_rules.get("polearm_rules", {}).get("1h_grip", {}).get("modifiers", {})
        stance_bonus_1h = combat_rules.get("polearm_rules", {}).get("1h_grip", {}).get("bonuses", {})
        mod_1h = stance_mods_1h.get(defender_stance, 0.5)
        bonus_1h = stance_bonus_1h.get(defender_stance, 0)
        
        base_primary = weapon_ranks + math.floor(str_b/4) + math.floor(dex_b/4) + math.floor(enchant/2)
        primary_ds = (base_primary * mod_1h) + bonus_1h
        
        twc_ranks = defender_skills.get("two_weapon_combat", 0)
        off_enchant = offhand_data.get("enchantment", 0)
        twc_rules = combat_rules.get("twc_rules", {})
        off_mod_table = twc_rules.get("offhand_stance_modifiers", {})
        off_mod = off_mod_table.get(defender_stance, 0.25)
        
        off_keywords = offhand_data.get("keywords", [])
        flat_bonus = twc_rules.get("offhand_bonus_default", 5)
        for special in twc_rules.get("special_offhand_weapons", []):
            if special in off_keywords:
                flat_bonus = twc_rules.get("offhand_bonus_special", 15)
                break
                
        base_off = twc_ranks + math.floor(str_b/4) + math.floor(dex_b/4) + math.floor(off_enchant/2)
        offhand_ds = (base_off * off_mod) + flat_bonus
        
        total_parry = primary_ds + offhand_ds
        return math.floor(total_parry * factor_mod)

    # Standard 1H Parry
    weapon_ranks = defender_skills.get(weapon_skill, 0)
    str_b = get_stat_bonus(defender_stats.get("STR", 50), "STR", defender_modifiers)
    dex_b = get_stat_bonus(defender_stats.get("DEX", 50), "DEX", defender_modifiers)
    base_parry = weapon_ranks + math.floor(str_b / 4) + math.floor(dex_b / 4)
    if weapon_data: base_parry += weapon_data.get("enchantment", 0)
    weapon_type = _get_weapon_type(weapon_data)
    handedness_mod = 1.5 if weapon_type == "2H" else 1.0
    
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
    
    stance_mods = combat_rules.get("stance_modifiers", {})
    stance_data = stance_mods.get(defender_stance, stance_mods.get("creature", {}))
    stance_percent = stance_data.get("percent", 50)
    
    factor_mod = _get_posture_status_factor(posture, status_effects, combat_rules)
    
    evade_ds = calculate_evade_defense(stats, skills, defender_modifiers, armor_item_data, shield_item_data, stance_percent, factor_mod, is_ranged_attack, combat_rules)
    block_ds = calculate_block_defense(stats, skills, defender_modifiers, shield_item_data, stance_percent, factor_mod, is_ranged_attack, combat_rules)
    parry_ds = calculate_parry_defense(stats, skills, defender_modifiers, weapon_item_data, offhand_item_data, level, stance_percent, factor_mod, is_ranged_attack, defender_stance, combat_rules)
    generic_ds = calculate_generic_defense(defender, combat_rules)
    
    total_ds = generic_ds + evade_ds + block_ds + parry_ds
    return max(0, total_ds)


# --- MAIN RESOLVE FUNCTION ---

def resolve_attack(world: 'World', attacker: Any, defender: Any, game_items_global: dict, is_offhand: bool = False) -> dict:
    combat_rules = getattr(world, 'game_rules', {})
    if not combat_rules:
        print("[COMBAT ERROR] Combat Rules missing! Using defaults.")

    is_attacker_player = isinstance(attacker, Player)
    attacker_name = attacker.name if is_attacker_player else attacker.get("name", "Creature")
    attacker_stats = attacker.stats if is_attacker_player else attacker.get("stats", {})
    attacker_skills = attacker.skills if is_attacker_player else attacker.get("skills", {})
    attacker_posture = attacker.posture if is_attacker_player else attacker.get("posture", "standing")
    attacker_stance = attacker.stance if is_attacker_player else attacker.get("stance", "creature")
    attacker_modifiers = _get_stat_modifiers(attacker)

    is_defender_player = isinstance(defender, Player)
    defender_name = defender.name if is_defender_player else defender.get("name", "Creature")
    defender_stance = defender.stance if is_defender_player else defender.get("stance", "creature")
    defender_modifiers = _get_stat_modifiers(defender)
    
    attacker_name_possessive = f"{attacker_name}'s" if not attacker_name.endswith('s') else f"{attacker_name}'"
    
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
    
    attacker_weapon_data = None
    hand_key = "main"
    if is_attacker_player:
        if is_offhand:
            attacker_weapon_data = attacker.get_equipped_item_data("offhand")
            hand_key = "off"
        else:
            attacker_weapon_data = attacker.get_equipped_item_data("mainhand")
    else:
        mainhand_id = attacker.get("equipped", {}).get("mainhand")
        attacker_weapon_data = game_items_global.get(mainhand_id) if mainhand_id else None
        
    attack_list = []
    if attacker_weapon_data:
        attack_list = attacker_weapon_data.get("attacks", [])
    elif not is_attacker_player:
        attack_list = attacker.get("attacks", [])
    
    if not attack_list: attack_list = [{ "verb": "attack", "damage_type": "crush", "weapon_name": "fist", "chance": 1.0 }]
    selected_attack = _get_weighted_attack(attack_list)
    if not selected_attack: selected_attack = attack_list[0]

    attack_verb = selected_attack.get("verb", "attack")
    weapon_damage_type = selected_attack.get("damage_type", "crush")
    weapon_damage_factor = 0.1
    broadcast_weapon_display = ""

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
    is_ranged_attack = attacker_weapon_type in ["bow", "crossbow"]

    attacker_as = calculate_attack_strength(
        attacker, attacker_stats, attacker_skills, 
        attacker_weapon_data, 
        attacker_stance,
        attacker_modifiers,
        combat_rules,
        hand=hand_key
    )
    
    defender_ds = calculate_defense_strength(
        defender, defender_armor_data, defender_shield_data, 
        defender_weapon_data, defender_offhand_data, 
        is_ranged_attack, defender_stance, 
        defender_modifiers,
        combat_rules
    )

    d100_roll = random.randint(1, 100)
    combat_roll_result = (attacker_as + avd_bonus) - defender_ds + d100_roll 

    as_str = f"+{attacker_as}" if attacker_as >= 0 else str(attacker_as)
    avd_str = f"+{avd_bonus}" if avd_bonus >= 0 else str(avd_bonus)
    roll_string = (f"  AS: {as_str} + AvD: {avd_str} + d100: +{d100_roll} - DS: {defender_ds} = {combat_roll_result}")
    
    log_builder = CombatLogBuilder(attacker_name, defender_name, broadcast_weapon_display, attack_verb)
    results = {'hit': False, 'damage': 0, 'attempt_msg': "", 'broadcast_attempt_msg': "", 'roll_string': roll_string, 'result_msg': "", 'broadcast_result_msg': "", 'critical_msg': "", 'is_fatal': False}

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
        
        # Monster Attack (Simplified for single attack per tick)
        attack_results = resolve_attack(world, attacker, defender, world.game_items, is_offhand=False)
        
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