# mud_backend/core/combat_system.py
import random
import math
import time
from typing import Dict
from typing import Any
from typing import Optional
from typing import TYPE_CHECKING
from typing import List

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

from mud_backend.core.game_objects import Player
from mud_backend.core.utils import calculate_skill_bonus
from mud_backend.core.utils import get_stat_bonus
from mud_backend import config
# NEW IMPORTS FOR DEATH HANDLER
from mud_backend.core import loot_system
from mud_backend.core import faction_handler

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
        if verb.endswith(('s', 'sh', 'ch', 'x', 'o')):
            return verb + "es"
        return verb + "s"

    def get_attempt_message(self, perspective: str) -> str:
        if perspective == 'attacker':
            return f"You {self.verb} {self.weapon} at {self.defender}!"
        elif perspective == 'defender':
            return f"{self.attacker} {self.verb_npc} {self.weapon} at you!"
        else:
            return f"{self.attacker} {self.verb_npc} {self.weapon} at {self.defender}!"

    def get_hit_result_message(self, total_damage: int) -> str:
        return f"   ... and hits for {total_damage} points of damage!"

    def get_broadcast_hit_message(self, perspective: str, total_damage: int) -> str:
        if perspective == 'attacker':
            return f"You hit {self.defender} for {total_damage} points of damage!"
        else:
            return f"{self.attacker} hits {self.defender} for {total_damage} points of damage!"

    def get_miss_message(self, perspective: str) -> str:
        if perspective == 'attacker':
            return random.choice(self.PLAYER_MISS_MESSAGES).format(defender=self.defender)
        elif perspective == 'defender':
            return random.choice(self.MONSTER_MISS_MESSAGES).format(attacker=self.attacker, defender="you")
        else:
            return random.choice(self.MONSTER_MISS_MESSAGES).format(attacker=self.attacker, defender=self.defender)

    def get_broadcast_miss_message(self, perspective: str) -> str:
        if perspective == 'attacker':
            return f"You miss {self.defender}."
        else:
            return f"{self.attacker} misses {self.defender}."

def _get_weighted_attack(attack_list: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not attack_list:
        return None
    total_weight = sum(attack.get("chance", 0) for attack in attack_list)
    if total_weight == 0:
        return random.choice(attack_list)
    roll = random.uniform(0, total_weight)
    upto = 0
    for attack in attack_list:
        chance = attack.get("chance", 0)
        if upto + chance >= roll:
            return attack
        upto += chance
    return random.choice(attack_list)

def get_entity_armor_type(entity, game_items_global: dict) -> str:
    if hasattr(entity, 'get_armor_type'):
        return entity.get_armor_type()
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
    if not weapon_item_data:
        return "brawling"
    skill = weapon_item_data.get("skill")
    if skill in ["two_handed_edged", "two_handed_blunt", "polearms"]:
        return "2H"
    if skill in ["bows", "crossbows"]:
        return "bow"
    if skill == "staves":
        return "runestaff"
    return "1H"

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
    effective_ap = base_ap if skill_bonus <= threshold else base_ap / 2
    return max(0.0, 1.0 + (effective_ap / 200.0))

def _get_random_hit_location(combat_rules: dict) -> str:
    locations = combat_rules.get("hit_locations", ["chest"])
    return random.choice(locations)

def _get_entity_critical_divisor(entity: Any, armor_data: Optional[Dict]) -> int:
    if armor_data:
        return armor_data.get("critical_divisor", 11)
    if isinstance(entity, dict):
        return entity.get("critical_divisor", 5)
    return 5

def _get_randomized_crit_rank(base_rank: int) -> int:
    if base_rank <= 0:
        return 0
    if base_rank == 1:
        return 1
    if base_rank == 2:
        return random.choice([1, 2])
    if base_rank == 3:
        return random.choice([2, 3])
    if base_rank == 4:
        return random.choice([2, 3, 4])
    if base_rank == 5:
        return random.choice([3, 4, 5])
    if base_rank == 6:
        return random.choice([3, 4, 5, 6])
    if base_rank == 7:
        return random.choice([4, 5, 6, 7])
    if base_rank == 8:
        return random.choice([4, 5, 6, 7, 8])
    return random.choice([5, 6, 7, 8, 9])

def _find_combatant(world: 'World', entity_id: str) -> Optional[Any]:
    player_info = world.get_player_info(entity_id.lower())
    if player_info:
        return player_info.get("player_obj")
    room_id = world.mob_locations.get(entity_id)
    if room_id:
        room = world.get_active_room_safe(room_id)
        if room:
            with room.lock:
                for obj in room.objects:
                    if obj.get("uid") == entity_id:
                        return obj
    return None

def _get_critical_result(world: 'World', damage_type: str, location: str, rank: int) -> Dict[str, Any]:
    if rank <= 0:
        return {"message": "", "extra_damage": 0, "wound_rank": 0}
    if damage_type not in world.game_criticals:
        damage_type = "slash"
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

def _get_posture_status_factor(entity_posture: str, status_effects: list, combat_rules: dict) -> float:
    factor = 1.0
    p_mods = combat_rules.get("posture_modifiers", {})
    p_data = p_mods.get(entity_posture, p_mods.get("standing", {}))
    factor *= p_data.get("defense_factor", 1.0)
    s_mods = combat_rules.get("status_modifiers", {})
    for effect in status_effects:
        if effect in s_mods:
            factor *= s_mods[effect].get("defense_factor", 1.0)
    return factor

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

# --- MAGIC COMBAT CALCULATIONS ---

def get_casting_stat(school: str) -> str:
    """Returns the primary attribute for a spell school."""
    if "elemental" in school or "sorcerous" in school:
        return "INT"
    if "spiritual" in school or "abjuration" in school:
        return "WIS"
    if "mental" in school:
        return "LOG"
    return "WIS" # Default

def calculate_casting_strength(caster: Any, spell_data: dict) -> int:
    """
    Calculates CS (Casting Strength).
    CS = Level + Stat Bonus + (Ranks * 3)
    """
    # 1. Stats
    skill_name = spell_data.get("skill", "spiritual_lore")
    school = spell_data.get("school", "spiritual")
    stat_name = get_casting_stat(school)

    caster_stats = caster.stats if isinstance(caster, Player) else caster.get("stats", {})
    caster_modifiers = _get_stat_modifiers(caster)
    stat_val = caster_stats.get(stat_name, 50)
    stat_bonus = get_stat_bonus(stat_val, stat_name, caster_modifiers)

    # 2. Level
    caster_level = caster.level if isinstance(caster, Player) else caster.get("level", 1)

    # 3. Skill Ranks
    ranks = 0
    if isinstance(caster, Player):
        ranks = caster.skills.get(skill_name, 0)
    else:
        # Monsters assume rank = level for primary magic skills
        ranks = caster_level

    cs = caster_level + stat_bonus + (ranks * 3)
    return cs

def calculate_target_defense(target: Any, spell_data: dict) -> int:
    """
    Calculates TD (Target Defense) against magic.
    TD = Level + Stat Bonus + Magic Defense Buffs
    """
    # 1. Stats (Target defends with same stat type as attack usually, or WIS for will)
    school = spell_data.get("school", "spiritual")
    stat_name = get_casting_stat(school)

    target_stats = target.stats if isinstance(target, Player) else target.get("stats", {})
    target_modifiers = _get_stat_modifiers(target)
    stat_val = target_stats.get(stat_name, 50)
    stat_bonus = get_stat_bonus(stat_val, stat_name, target_modifiers)

    # 2. Level
    target_level = target.level if isinstance(target, Player) else target.get("level", 1)

    # 3. Buffs
    buff_bonus = 0
    buffs = target.buffs if isinstance(target, Player) else target.get("buffs", {})
    for buff in buffs.values():
        if buff.get("type") == "magic_defense":
            buff_bonus += buff.get("val", 0)

    td = target_level + stat_bonus + buff_bonus
    return td

def get_cva(target: Any) -> int:
    """
    Cast vs Armor (CvA).
    Positive = Easier to hit (Cloth). Negative = Harder to hit (Plate).
    """
    armor_type = config.DEFAULT_UNARMORED_TYPE
    if isinstance(target, Player):
        armor_type = target.get_armor_type()
    else:
        # Heuristic for monsters based on description/attributes
        defense_attrs = target.get("defense_attributes", [])
        if "plate" in str(defense_attrs):
            armor_type = "plate"
        elif "chain" in str(defense_attrs):
            armor_type = "chain"
        elif "leather" in str(defense_attrs):
            armor_type = "leather"
        else:
            armor_type = "cloth"

    # Arbitrary values: High negative protects well, positive makes it easier
    cva_map = {
        "unarmored": 20,
        "cloth": 15,
        "leather": 0,
        "scale": -5,
        "chain": -10,
        "plate": -20
    }
    return cva_map.get(armor_type, 0)


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
        if ambush_ranks > 40:
            as_val += math.floor((ambush_ranks - 40) / 4)
        if perception_ranks > 40:
            as_val += math.floor((perception_ranks - 40) / 4)

        if weapon_item_data:
            as_val += min(50, weapon_item_data.get("enchantment", 0))

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

        if weapon_item_data:
            as_val += weapon_item_data.get("enchantment", 0)

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

def calculate_generic_defense(defender: Any, combat_rules: dict) -> int:
    ds = 0
    buffs = defender.buffs if isinstance(defender, Player) else defender.get("buffs", {})
    for buff in buffs.values():
        if buff.get("type") == "ds_bonus":
            ds += buff.get("val", 0)
    env_mods = combat_rules.get("environmental_modifiers", {})
    ds += env_mods.get("average", 0)
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
    agi_b = get_stat_bonus(defender_stats.get("AGI", 50), "AGI", defender_modifiers)
    int_b = get_stat_bonus(defender_stats.get("INT", 50), "INT", defender_modifiers)
    dodging_ranks = defender_skills.get("dodging", 0)
    base_evade = agi_b + math.floor(int_b / 4) + dodging_ranks
    hindrance = _get_armor_hindrance(armor_data, defender_skills)
    shield_penalty = 0
    evade_ds = (base_evade - shield_penalty) * hindrance * (stance_percent / 100.0) * factor_mod
    if is_ranged:
        evade_ds *= 1.5
    return math.floor(evade_ds)

def calculate_block_defense(defender_stats: dict, defender_skills: dict, defender_modifiers: dict,
                            shield_data: dict | None, stance_percent: int, factor_mod: float,
                            is_ranged: bool, combat_rules: dict) -> int:
    if not shield_data:
        return 0
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
        off_mod = twc_rules.get("offhand_modifier", {}).get(defender_stance, 0.25)

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
    if weapon_data:
        base_parry += weapon_data.get("enchantment", 0)
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
    else:
        return 0

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

    if defender_shield_data and defender_shield_data.get("item_type") != "shield":
        defender_shield_data = None

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

    if not attack_list:
        attack_list = [{ "verb": "attack", "damage_type": "crush", "weapon_name": "fist", "chance": 1.0 }]
    selected_attack = _get_weighted_attack(attack_list)
    if not selected_attack:
        selected_attack = attack_list[0]

    attack_verb = selected_attack.get("verb", "attack")
    weapon_damage_type = selected_attack.get("damage_type", "crush")
    weapon_damage_factor = 0.1
    broadcast_weapon_display = ""

    avd_bonus = 0
    if attacker_weapon_data:
        weapon_damage_factor = attacker_weapon_data.get("damage_factors", {}).get(defender_armor_type_str, 0.100)
        avd_mods = attacker_weapon_data.get("avd_modifiers", {})
        avd_bonus = avd_mods.get(defender_armor_type_str, avd_mods.get(config.DEFAULT_UNARMORED_TYPE, 0))
        if is_attacker_player:
            broadcast_weapon_display = f"your {attacker_weapon_data.get('name', 'weapon')}"
        else:
            broadcast_weapon_display = f"{attacker_name_possessive} {attacker_weapon_data.get('name', 'weapon')}"
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

        # --- WOUND AGGRAVATION LOGIC START ---
        if is_defender_player:
            current_rank = defender.wounds.get(hit_location, 0)

            # If hit in same location, upgrade wound (Aggravation)
            if current_rank > 0 and wound_rank > 0:
                new_rank = min(3, current_rank + 1)
                defender.wounds[hit_location] = new_rank

                # Message for aggravation
                severity = "worsens"
                if new_rank == 2:
                    severity = "begins to bleed profusely"
                if new_rank == 3:
                    severity = "is mangled badly"

                # Append to existing critical message or create new one
                aggravation_msg = f"\nThe wound on {defender_name}'s {hit_location} {severity}!"
                if "message" in crit_result:
                    crit_result["message"] += aggravation_msg
                else:
                    crit_result["message"] = aggravation_msg

                # TEAR OFF BANDAGES
                if hasattr(defender, "bandages") and hit_location in defender.bandages:
                    del defender.bandages[hit_location]
                    crit_result["message"] += f"\nThe bandages on {defender_name}'s {hit_location} are torn away!"

            elif wound_rank > 0:
                # Fresh wound
                defender.wounds[hit_location] = wound_rank
        # --- WOUND AGGRAVATION LOGIC END ---

        results['result_msg'] = log_builder.get_hit_result_message(total_damage)
        if is_attacker_player:
            results['broadcast_result_msg'] = log_builder.get_broadcast_hit_message('attacker', total_damage)
        else:
            results['broadcast_result_msg'] = log_builder.get_broadcast_hit_message('room', total_damage)

        crit_msg = crit_result.get("message", "").format(defender=defender_name)
        if crit_msg:
            results['critical_msg'] = f"   {crit_msg}"
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
        if state.get("state_type") != "combat":
            continue
        if not world.get_combat_state(combatant_id):
            continue
        if current_time < state["next_action_time"]:
            continue

        attacker = _find_combatant(world, combatant_id)
        defender = _find_combatant(world, state["target_id"])
        attacker_room_id = state.get("current_room_id")

        if not attacker or not defender or not attacker_room_id:
            world.stop_combat_for_all(combatant_id, state["target_id"])
            continue

        # [FIX] Check for Room/Distance integrity
        attacker_loc = None
        if isinstance(attacker, Player):
            attacker_loc = attacker.current_room_id
        else:
            attacker_loc = world.mob_locations.get(attacker.get("uid"))

        defender_loc = None
        if isinstance(defender, Player):
            defender_loc = defender.current_room_id
        else:
            defender_loc = world.mob_locations.get(defender.get("uid"))

        if attacker_loc != defender_loc:
            world.stop_combat_for_all(combatant_id, state["target_id"])
            continue

        if isinstance(attacker, Player):
            continue

        # [FIX] Check if Monster Attacker is Dead
        if not isinstance(attacker, Player):
            att_uid = attacker.get("uid")
            att_hp = world.get_monster_hp(att_uid)
            if att_hp is not None and att_hp <= 0:
                world.remove_combat_state(combatant_id)
                continue

        is_defender_player = isinstance(defender, Player)

        # Monster Attack
        attack_results = resolve_attack(world, attacker, defender, world.game_items, is_offhand=False)

        sid_to_skip = None
        if is_defender_player:
            send_to_player_callback(defender.name, attack_results['attempt_msg'], "message")
            send_to_player_callback(defender.name, attack_results['roll_string'], "message")
            send_to_player_callback(defender.name, attack_results['result_msg'], "message")
            if attack_results['hit'] and attack_results['critical_msg']:
                send_to_player_callback(defender.name, attack_results['critical_msg'], "message")
            defender_info = world.get_player_info(defender.name.lower())
            if defender_info:
                sid_to_skip = defender_info.get("sid")

        broadcast_msg = attack_results['broadcast_attempt_msg']
        if attack_results['hit']:
            broadcast_msg = attack_results['broadcast_result_msg']
            if attack_results['critical_msg']:
                broadcast_msg += f"\n{attack_results['critical_msg']}"
        else:
            broadcast_msg += f"\n{attack_results['broadcast_result_msg']}"

        broadcast_callback(attacker_room_id, broadcast_msg, "combat_broadcast", skip_sid=sid_to_skip)

        if attack_results['hit']:
            damage = attack_results['damage']
            is_fatal = attack_results['is_fatal']

            if is_defender_player:
                defender.hp -= damage
                if defender.hp <= 0 or is_fatal:
                    if is_fatal and defender.hp > 0:
                        send_to_player_callback(defender.name, "The world goes black as you suffer a fatal wound...", "combat_death")
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
                    defender.mark_dirty() 
                    continue
                else:
                    vitals_data = defender.get_vitals()
                    send_vitals_callback(defender.name, vitals_data)
                    send_to_player_callback(defender.name, f"(You have {defender.hp}/{defender.max_hp} HP remaining)", "system_info")
                    defender.mark_dirty()
            else:
                # Monster killed by Monster (uncommon but possible)
                defender_uid = defender.get("uid")
                new_hp = world.modify_monster_hp(defender_uid, defender.get("max_hp", 1), damage)
                if new_hp <= 0 or is_fatal:
                    consequence_msg = f"**The {defender['name']} has been DEFEATED!**"
                    broadcast_callback(attacker_room_id, consequence_msg, "combat_death", skip_sid=sid_to_skip)
                    
                    # Monster vs Monster cleanup
                    world.set_defeated_monster(defender_uid, {
                        "room_id": attacker_room_id,
                        "template_key": defender.get("monster_id"),
                        "type": "monster",
                        "eligible_at": time.time() + 300, # Default wait
                        "chance": 1.0,
                        "faction": defender.get("faction")
                    })
                    
                    room = world.get_active_room_safe(attacker_room_id)
                    if room:
                         with room.lock:
                             if defender in room.objects:
                                 room.objects.remove(defender)
                    world.unregister_mob(defender_uid)
                    
                    world.stop_combat_for_all(combatant_id, state["target_id"])
                    continue

        rt_seconds = calculate_roundtime(attacker.get("stats", {}).get("AGI", 50))
        data = world.get_combat_state(combatant_id)
        if data:
            data["next_action_time"] = current_time + rt_seconds
            data["duration"] = rt_seconds
            world.set_combat_state(combatant_id, data)

# --- SHARED COMBAT SYSTEMS ---

def trigger_social_aggro(world: 'World', room: Any, target_monster_data: dict, player: Player):
    """
    Causes monsters of the same faction in the room to attack the player.
    """
    target_faction = target_monster_data.get("faction")
    if not target_faction:
        return

    target_uid = target_monster_data.get("uid")
    player_id = player.name.lower()
    current_time = time.time()

    for obj in room.objects:
        if obj.get("uid") == target_uid:
            continue
        if not (obj.get("is_monster") or obj.get("is_npc")):
            continue
        if obj.get("faction") != target_faction:
            continue

        mob_uid = obj.get("uid")
        combat_state = world.get_combat_state(mob_uid)
        if combat_state and combat_state.get("state_type") == "combat":
            continue

        monster_name = obj.get("name", "A creature")
        player.send_message(f"The {monster_name} comes to the aid of its kin!")
        world.broadcast_to_room(room.room_id, f"The {monster_name} joins the fight!", "combat_broadcast", skip_sid=player.uid)

        monster_agi = obj.get("stats", {}).get("AGI", 50)
        monster_rt = calculate_roundtime(monster_agi)

        world.set_combat_state(mob_uid, {
            "state_type": "combat",
            "target_id": player_id,
            "next_action_time": current_time + (monster_rt / 2),
            "current_room_id": room.room_id
        })
        if world.get_monster_hp(mob_uid) is None:
            world.set_monster_hp(mob_uid, obj.get("max_hp", 50))

def calculate_combat_xp(present_group_members: List[Player], monster_level: int) -> int:
    """
    Calculates XP share for a group killing a monster.
    """
    # Use the highest level member to calculate base XP to prevent power-leveling exploits
    if not present_group_members:
        return 0
        
    max_level = max(p.level for p in present_group_members)
    level_diff = max_level - monster_level
    
    nominal_xp = 0
    if level_diff >= 10:
        nominal_xp = 0
    elif 1 <= level_diff <= 9:
        nominal_xp = 100 - (10 * level_diff)
    elif level_diff == 0:
        nominal_xp = 100
    elif -4 <= level_diff <= -1:
        nominal_xp = 100 + (10 * abs(level_diff))
    elif level_diff <= -5:
        nominal_xp = 150
    nominal_xp = max(0, nominal_xp)

    if nominal_xp > 0:
        member_count = len(present_group_members)
        # Group Bonus: 10% bonus per extra person
        bonus_multiplier = 1.0 + (0.1 * (member_count - 1)) if member_count > 1 else 1.0
        total_xp = nominal_xp * bonus_multiplier
        
        # Split XP evenly
        share_xp = int(total_xp / member_count)
        return share_xp
    
    return 0

def handle_monster_death(world: 'World', player: Player, target_monster_data: dict, room: Any) -> List[str]:
    """
    Centralized handler for monster death.
    Handles: Treasure system, Quests, XP, Faction, Corpses, Respawn.
    Returns: A list of result strings to display.
    """
    messages = []
    monster_uid = target_monster_data.get("uid")
    
    # 1. Treasure System
    monster_id = target_monster_data.get("monster_id")
    if monster_id and hasattr(world, 'treasure_manager'):
        world.treasure_manager.register_kill(monster_id)

    # 2. Group Identification
    present_group_members = []
    if player.group_id:
        group_data = world.get_group(player.group_id)
        if group_data:
            for member_name in group_data.get("members", []):
                p_info = world.get_player_info(member_name)
                if p_info:
                    p_obj = p_info.get("player_obj")
                    # Only include members in the same room
                    if p_obj and p_obj.current_room_id == room.room_id:
                        present_group_members.append(p_obj)
    
    if not present_group_members:
        present_group_members = [player]

    # 3. Quest Counters (Shared)
    monster_family = target_monster_data.get("family")
    for member in present_group_members:
        if monster_id:
            key = f"{monster_id}_kills"
            member.quest_counters[key] = member.quest_counters.get(key, 0) + 1
        if monster_family:
            key = f"{monster_family}_kills"
            member.quest_counters[key] = member.quest_counters.get(key, 0) + 1

    # 4. XP Logic (Shared)
    monster_level = target_monster_data.get("level", 1)
    share_xp = calculate_combat_xp(present_group_members, monster_level)
    
    if share_xp > 0:
        member_count = len(present_group_members)
        for member in present_group_members:
            member.grant_experience(share_xp, source="combat")
            if member == player:
                if member_count > 1:
                    messages.append(f"Group kill! You share experience and gain {share_xp} XP.")
                else:
                    messages.append(f"You have gained {share_xp} experience from the kill.")
            else:
                member.send_message(f"Your group killed a {target_monster_data['name']}! You share experience and gain {share_xp} XP.")

    # 5. Faction Adjustments (Applied to killer only for now)
    monster_faction = target_monster_data.get("faction")
    if monster_faction:
        adjustments = faction_handler.get_faction_adjustments_on_kill(world, monster_faction)
        for fac_id, amount in adjustments.items():
            faction_handler.adjust_player_faction(player, fac_id, amount)

    # 6. Corpse Creation
    corpse_data = loot_system.create_corpse_object_data(
        target_monster_data, monster_uid, world.game_items, world.game_loot_tables, {}
    )
    room.objects.append(corpse_data)
    
    # 7. Removal & Cleanup
    if target_monster_data in room.objects:
        room.objects.remove(target_monster_data)

    world.save_room(room)
    world.unregister_mob(monster_uid)

    messages.append(f"The {corpse_data['name']} falls to the ground.")

    # 8. Respawn Scheduling
    respawn_time = target_monster_data.get("respawn_time_seconds", 300)
    respawn_chance = target_monster_data.get("respawn_chance_per_tick", getattr(config, "NPC_DEFAULT_RESPAWN_CHANCE", 0.2))

    world.set_defeated_monster(monster_uid, {
        "room_id": room.room_id,
        "template_key": target_monster_data.get("monster_id"),
        "type": "monster",
        "eligible_at": time.time() + respawn_time,
        "chance": respawn_chance,
        "faction": monster_faction
    })
    world.stop_combat_for_all(player.name.lower(), monster_uid)
    
    return messages