# mud_backend/core/combat_system.py
import random
import re
import math
import time
import copy
from typing import Dict, Any, Optional, TYPE_CHECKING, List

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

from mud_backend.core.game_objects import Player
from mud_backend.core.db import save_game_state
from mud_backend.core import loot_system
from mud_backend.core.utils import calculate_skill_bonus
from mud_backend import config

from mud_backend.core.utils import get_stat_bonus, RACE_MODIFIERS, DEFAULT_RACE_MODS
from mud_backend.core import faction_handler
from mud_backend.core.skill_handler import attempt_skill_learning


# --- CONSTANTS & DATA ---

STANCE_MODIFIERS = {
    "offensive": {"as_mod": 1.15, "ds_mod": 0.70},
    "advance":   {"as_mod": 1.10, "ds_mod": 0.80},
    "forward":   {"as_mod": 1.05, "ds_mod": 0.90},
    "neutral":   {"as_mod": 1.00, "ds_mod": 1.00},
    "guarded":   {"as_mod": 0.90, "ds_mod": 1.10},
    "defensive": {"as_mod": 0.75, "ds_mod": 1.25},
    "creature":  {"as_mod": 1.00, "ds_mod": 1.00}
}

POSTURE_MODIFIERS = {
    "standing":  {"as_mod": 1.0, "ds_mod": 1.0},
    "sitting":   {"as_mod": 0.5, "ds_mod": 0.5},
    "kneeling":  {"as_mod": 0.75, "ds_mod": 0.75},
    "prone":     {"as_mod": 0.3, "ds_mod": 0.9}
}

POSTURE_PERCENTAGE = {
    "standing":  1.00,
    "sitting":   0.50,
    "kneeling":  0.75,
    "prone":     0.90
}

SHIELD_DATA = {
    "small_wooden_shield": {
        "size": "small",
        "factor": 1.0,
        "size_penalty_melee": 0,
        "size_mod_melee": 1.0,
        "size_mod_ranged": 1.2,
        "size_bonus_ranged": 10
    }
}
DEFAULT_SHIELD_DATA = SHIELD_DATA["small_wooden_shield"]

HIT_LOCATIONS = [
    "head", "neck", "chest", "abdomen", "back", "right_eye", "left_eye",
    "right_leg", "left_leg", "right_arm", "left_arm", "right_hand", "left_hand"
]


# --- COMBAT LOG BUILDER ---

class CombatLogBuilder:
    """
    Handles the generation of combat messages for different perspectives
    (Attacker, Defender, Room/Observer).
    """
    
    PLAYER_MISS_MESSAGES = [
        "   A clean miss.",
        "   You miss {defender} completely.",
        "   {defender} avoids the attack!",
        "   An awkward miss.",
        "   Your attack goes wide."
    ]
    
    MONSTER_MISS_MESSAGES = [
        "   A clean miss.",
        "   {attacker} misses {defender} completely.",
        "   {defender} avoids the attack!",
        "   An awkward miss.",
        "   The attack goes wide."
    ]

    def __init__(self, attacker_name: str, defender_name: str, weapon_name: str, verb: str):
        self.attacker = attacker_name
        self.defender = defender_name
        self.weapon = weapon_name
        self.verb = verb
        self.verb_npc = self._conjugate(verb)

    def _conjugate(self, verb: str) -> str:
        """Conjugates a verb for 3rd person (e.g., slash -> slashes)."""
        if verb.endswith(('s', 'sh', 'ch', 'x', 'o')):
            return verb + "es"
        return verb + "s"

    def get_attempt_message(self, perspective: str) -> str:
        """
        Returns the 'X attacks Y' message based on who is viewing it.
        perspective: 'attacker' (You...), 'defender' (He...), 'room' (Bob...)
        """
        if perspective == 'attacker':
            return f"You {self.verb} {self.weapon} at {self.defender}!"
        elif perspective == 'defender':
            return f"{self.attacker} {self.verb_npc} {self.weapon} at you!"
        else: # room/observer
            return f"{self.attacker} {self.verb_npc} {self.weapon} at {self.defender}!"

    def get_hit_result_message(self, total_damage: int) -> str:
        """Returns the specific damage string appended to the attempt."""
        return f"   ... and hits for {total_damage} points of damage!"

    def get_broadcast_hit_message(self, perspective: str, total_damage: int) -> str:
        """Returns the full sentence hit message for the room/logs."""
        if perspective == 'attacker':
            return f"You hit {self.defender} for {total_damage} points of damage!"
        else: # room/defender view of attacker
            return f"{self.attacker} hits {self.defender} for {total_damage} points of damage!"

    def get_miss_message(self, perspective: str) -> str:
        """Returns a randomized miss message."""
        if perspective == 'attacker':
            return random.choice(self.PLAYER_MISS_MESSAGES).format(defender=self.defender)
        elif perspective == 'defender':
            # Swap names for the perspective of the defender reading "Attacker misses You"
            # But the template usually says "{attacker} misses {defender}"
            # We need to ensure the template makes sense.
            # Current templates: "{attacker} misses {defender} completely."
            # If perspective is defender, we want: "Goblin misses You completely."
            msg = random.choice(self.MONSTER_MISS_MESSAGES)
            return msg.format(attacker=self.attacker, defender="you")
        else: # room
            msg = random.choice(self.MONSTER_MISS_MESSAGES)
            return msg.format(attacker=self.attacker, defender=self.defender)

    def get_broadcast_miss_message(self, perspective: str) -> str:
        """Returns the simple broadcast miss string."""
        if perspective == 'attacker':
            return f"You miss {self.defender}."
        else:
            return f"{self.attacker} misses {self.defender}."


# --- HELPER FUNCTIONS ---

def _get_weighted_attack(attack_list: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Selects a random attack from a list based on weighted chances.
    """
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

def get_entity_race(entity: Any) -> str:
    if isinstance(entity, Player):
        return entity.appearance.get("race", "Human")
    elif isinstance(entity, dict):
        return entity.get("race", "Human")
    return "Human"

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

def _get_random_hit_location() -> str:
    return random.choice(HIT_LOCATIONS)

def _get_entity_critical_divisor(entity: Any, armor_data: Optional[Dict]) -> int:
    if armor_data:
        return armor_data.get("critical_divisor", 11) 
    if isinstance(entity, dict):
        return entity.get("critical_divisor", 5) 
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
    """
    Finds a player object or a MERGED monster/NPC dictionary.
    """
    player_info = world.get_player_info(entity_id.lower())
    if player_info: return player_info.get("player_obj")

    for room in world.game_rooms.values():
        for obj_stub in room.get("objects", []):
            if obj_stub.get("uid") == entity_id:
                monster_id = obj_stub.get("monster_id")
                if monster_id:
                    template = world.game_monster_templates.get(monster_id)
                    if template:
                        merged_obj = copy.deepcopy(template)
                        merged_obj.update(obj_stub)
                        return merged_obj
                    else:
                        return obj_stub
                elif obj_stub.get("is_npc"):
                    return obj_stub
                else:
                    return None 
    return None

def _get_critical_result(world: 'World', damage_type: str, location: str, rank: int) -> Dict[str, Any]:
    if rank <= 0:
        return {"message": "", "extra_damage": 0, "wound_rank": 0}

    if damage_type not in world.game_criticals:
        damage_type = "slash"
        
    crit_table = world.game_criticals[damage_type]
    
    if location not in crit_table:
        available_locations = list(crit_table.keys())
        if available_locations:
            location = available_locations[0] 
        else:
            return {"message": "A solid hit!", "extra_damage": 1, "wound_rank": 1}
            
    location_table = crit_table[location]
    rank_str = str(min(rank, max(int(k) for k in location_table.keys())))
    result = location_table.get(rank_str, {"message": "A solid hit!", "extra_damage": 1, "wound_rank": 1})
    result.setdefault("stun", False)
    result.setdefault("fatal", False)
    return result


# --- CALCULATION LOGIC ---

def calculate_attack_strength(attacker_name: str, attacker_stats: dict, attacker_skills: dict,
                              weapon_item_data: dict | None, target_armor_type: str,
                              attacker_posture: str, attacker_stance: str, attacker_race: str) -> int:
    as_val = 0
    strength_stat = attacker_stats.get("STR", 50)
    str_bonus = get_stat_bonus(strength_stat, "STR", attacker_race)
    as_val += str_bonus

    if not weapon_item_data or weapon_item_data.get("item_type") != "weapon": 
        brawling_skill_rank = attacker_skills.get("brawling", 0)
        brawling_bonus = calculate_skill_bonus(brawling_skill_rank)
        as_val += brawling_bonus
        base_barehanded_as = getattr(config, 'BAREHANDED_BASE_AS', 0)
        as_val += base_barehanded_as
    else:
        weapon_skill_name = weapon_item_data.get("skill")
        if weapon_skill_name:
            skill_rank = attacker_skills.get(weapon_skill_name, 0)
            skill_bonus = calculate_skill_bonus(skill_rank)
            as_val += skill_bonus

        avd_mods = weapon_item_data.get("avd_modifiers", {})
        avd_bonus = avd_mods.get(target_armor_type, avd_mods.get(config.DEFAULT_UNARMORED_TYPE, 0))
        as_val += avd_bonus

    cman_ranks = attacker_skills.get("combat_maneuvers", 0)
    cman_bonus = math.floor(cman_ranks / 2)
    as_val += cman_bonus

    posture_mod = POSTURE_MODIFIERS.get(attacker_posture, POSTURE_MODIFIERS["standing"])["as_mod"]
    as_val = int(as_val * posture_mod)

    stance_data = STANCE_MODIFIERS.get(attacker_stance, STANCE_MODIFIERS["creature"])
    stance_mod = stance_data["as_mod"]
    final_as = int(as_val * stance_mod)

    return final_as

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
        shield_props = SHIELD_DATA.get("small_wooden_shield", DEFAULT_SHIELD_DATA)
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
    shield_props = SHIELD_DATA.get("small_wooden_shield", DEFAULT_SHIELD_DATA)
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
    
    buff_bonus = 0
    if isinstance(defender, Player):
        if "spirit_shield" in defender.buffs:
            buff_data = defender.buffs["spirit_shield"]
            if time.time() < buff_data.get("expires_at", 0):
                buff_bonus = buff_data.get("ds_bonus", 0)
            else:
                defender.buffs.pop("spirit_shield", None) 

    base_ds = evade_ds + block_ds + parry_ds + buff_bonus

    stance_data = STANCE_MODIFIERS.get(defender_stance, STANCE_MODIFIERS["creature"])
    stance_mod = stance_data["ds_mod"]
    final_ds = int(base_ds * stance_mod)

    return final_ds

def calculate_roundtime(agility: int) -> float:
    return max(3.0, 5.0 - ((agility - 50) / 25))


# --- MAIN COMBAT RESOLUTION ---

def resolve_attack(world: 'World', attacker: Any, defender: Any, game_items_global: dict) -> dict:
    is_attacker_player = isinstance(attacker, Player)
    attacker_name = attacker.name if is_attacker_player else attacker.get("name", "Creature")
    attacker_stats = attacker.stats if is_attacker_player else attacker.get("stats", {})
    attacker_skills = attacker.skills if is_attacker_player else attacker.get("skills", {})
    attacker_posture = attacker.posture if is_attacker_player else attacker.get("posture", "standing")
    attacker_race = get_entity_race(attacker)
    attacker_stance = attacker.stance if is_attacker_player else attacker.get("stance", "creature")

    is_defender_player = isinstance(defender, Player)
    defender_name = defender.name if is_defender_player else defender.get("name", "Creature")
    defender_stance = defender.stance if is_defender_player else defender.get("stance", "creature")
    
    # --- Possessive Names ---
    attacker_name_possessive = f"{attacker_name}'s" if not attacker_name.endswith('s') else f"{attacker_name}'"
    defender_name_possessive = f"{defender_name}'s" if not defender_name.endswith('s') else f"{defender_name}'"

    # --- Gear Check ---
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
    if defender_offhand_data and defender_offhand_data.get("item_type") == "shield": 
        defender_offhand_data = None
        
    # --- Attack Selection & Data Gathering ---
    selected_attack: Optional[Dict[str, Any]] = None
    attack_list: List[Dict[str, Any]] = []
    attacker_weapon_data: Optional[Dict[str, Any]] = None
    
    if is_attacker_player:
        # LBD Skill Gain
        attacker_weapon_data = attacker.get_equipped_item_data("mainhand")
        weapon_skill_to_learn = "brawling"
        if attacker_weapon_data:
            weapon_skill_to_learn = attacker_weapon_data.get("skill", "brawling")
        attempt_skill_learning(attacker, weapon_skill_to_learn)
        
        if attacker_weapon_data:
            attack_list = attacker_weapon_data.get("attacks", [])
        else:
            attack_list = [{ "verb": "punch", "damage_type": "crush", "weapon_name": "your fist", "chance": 1.0 }]
    else:
        mainhand_id = attacker.get("equipped", {}).get("mainhand")
        attacker_weapon_data = game_items_global.get(mainhand_id) if mainhand_id else None
        if attacker_weapon_data:
            attack_list = attacker_weapon_data.get("attacks", [])
        else:
            attack_list = attacker.get("attacks", [])
        
    if not attack_list:
        attack_list = [{ "verb": "attack", "damage_type": "crush", "weapon_name": "something", "chance": 1.0 }]

    selected_attack = _get_weighted_attack(attack_list)
    if not selected_attack:
        selected_attack = attack_list[0]

    attack_verb = selected_attack.get("verb", "attack")
    weapon_damage_type = selected_attack.get("damage_type", "crush")
    
    weapon_damage_factor = 0.100
    broadcast_weapon_display = "" 

    if attacker_weapon_data:
        weapon_damage_factor = attacker_weapon_data.get("damage_factors", {}).get(defender_armor_type_str, 0.100)
        if is_attacker_player:
            broadcast_weapon_display = f"your {attacker_weapon_data.get('name', 'weapon')}"
        else:
            broadcast_weapon_display = f"{attacker_name_possessive} {attacker_weapon_data.get('name', 'weapon')}"
    else:
        # Natural / Unarmed
        if is_attacker_player:
             broadcast_weapon_display = "your fist"
        else:
             broadcast_weapon_display = selected_attack.get("weapon_name", f"{attacker_name_possessive} fist")
        
        damage_factors = attacker.get("damage_factors", {}) if not is_attacker_player else {}
        weapon_damage_factor = damage_factors.get(defender_armor_type_str, 0.100)

    # --- Roll Calculation ---
    attacker_weapon_type = _get_weapon_type(attacker_weapon_data)
    is_ranged_attack = attacker_weapon_type in ["bow"]

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
    
    # --- Initialize CombatLogBuilder ---
    log_builder = CombatLogBuilder(attacker_name, defender_name, broadcast_weapon_display, attack_verb)

    results = {
        'hit': False, 'damage': 0, 
        'attempt_msg': "",          # Message sent to the entity executing the logic (Attacker if Player)
        'defender_attempt_msg': "", # Message sent to the target (Defender if Player)
        'broadcast_attempt_msg': "",# Message sent to room
        'roll_string': roll_string, 
        'result_msg': "",           
        'broadcast_result_msg': "", 
        'critical_msg': "",         
        'is_fatal': False
    }

    # --- Generate Attempt Messages ---
    if is_attacker_player:
        results['attempt_msg'] = log_builder.get_attempt_message('attacker')
        results['broadcast_attempt_msg'] = log_builder.get_attempt_message('room')
    else:
        # If attacker is monster, 'attempt_msg' is what the Player (defender) sees
        results['attempt_msg'] = log_builder.get_attempt_message('defender')
        results['broadcast_attempt_msg'] = log_builder.get_attempt_message('room')

    # --- Resolve Hit/Miss ---
    if combat_roll_result > config.COMBAT_HIT_THRESHOLD:
        results['hit'] = True
        
        endroll_success_margin = combat_roll_result - config.COMBAT_HIT_THRESHOLD
        raw_damage = max(1, endroll_success_margin * weapon_damage_factor) 
        
        critical_divisor = _get_entity_critical_divisor(defender, defender_armor_data)
        base_crit_rank = math.trunc(raw_damage / critical_divisor)
        final_crit_rank = _get_randomized_crit_rank(base_crit_rank)
        hit_location = _get_random_hit_location()
        
        crit_result = _get_critical_result(world, weapon_damage_type, hit_location, final_crit_rank)
        
        extra_damage = crit_result["extra_damage"]
        total_damage = math.trunc(raw_damage) + extra_damage
        results['damage'] = total_damage
        results['is_fatal'] = crit_result.get("fatal", False)
        
        wound_rank = crit_result.get("wound_rank", 0)
        if is_defender_player and wound_rank > 0:
            existing_wound = defender.wounds.get(hit_location, 0)
            if wound_rank > existing_wound:
                defender.wounds[hit_location] = wound_rank
        
        # --- Generate Hit Messages ---
        results['result_msg'] = log_builder.get_hit_result_message(total_damage)
        
        if is_attacker_player:
            results['broadcast_result_msg'] = log_builder.get_broadcast_hit_message('attacker', total_damage)
        else:
            results['broadcast_result_msg'] = log_builder.get_broadcast_hit_message('room', total_damage)
        
        crit_msg = crit_result.get("message", "").format(defender=defender_name)
        if crit_msg:
            results['critical_msg'] = f"   {crit_msg}"
        
    else:
        # --- Generate Miss Messages ---
        results['hit'] = False
        if is_attacker_player:
            results['result_msg'] = log_builder.get_miss_message('attacker')
            results['broadcast_result_msg'] = log_builder.get_broadcast_miss_message('attacker')
        else:
            # Attacker is monster, so 'result_msg' is for the defender (Player)
            results['result_msg'] = log_builder.get_miss_message('defender')
            results['broadcast_result_msg'] = log_builder.get_broadcast_miss_message('room')

    return results

def stop_combat(world: 'World', combatant_id: str, target_id: str):
    world.stop_combat_for_all(combatant_id, target_id)

def process_combat_tick(world: 'World', broadcast_callback, send_to_player_callback, send_vitals_callback):
    """
    Main automated combat loop.
    Typically handles Monsters attacking Players/NPCs, as Players attack via Commands.
    """
    current_time = time.time()
    combatant_list = world.get_all_combat_states()

    for combatant_id, state in combatant_list:
        if state.get("state_type") != "combat": continue
        
        with world.combat_lock:
             if combatant_id not in world.combat_state: continue
        
        if current_time < state["next_action_time"]: continue

        attacker = _find_combatant(world, combatant_id)
        defender = _find_combatant(world, state["target_id"])
        
        attacker_room_id = state.get("current_room_id")

        if not attacker or not defender or not attacker_room_id:
            world.stop_combat_for_all(combatant_id, state["target_id"])
            continue

        # Skip if attacker is a player (players rely on input commands)
        if isinstance(attacker, Player): continue 

        is_defender_player = isinstance(defender, Player)
        
        defender_room_id = None
        if is_defender_player:
            defender_room_id = defender.current_room_id
        else:
            defender_state = world.get_combat_state(state["target_id"])
            if defender_state:
                defender_room_id = defender_state.get("current_room_id")
            else:
                for room_id, room in world.game_rooms.items():
                    for obj in room.get("objects", []):
                        if obj.get("uid") == state["target_id"]:
                            defender_room_id = room_id
                            break
                    if defender_room_id: break

        if attacker_room_id != defender_room_id:
            world.remove_combat_state(combatant_id) 
            continue

        attack_results = resolve_attack(world, attacker, defender, game_items_global=world.game_items)

        sid_to_skip = None
        if is_defender_player:
            # Send detailed attempt/roll/result to the defender (Player)
            send_to_player_callback(defender.name, attack_results['attempt_msg'], "message")
            send_to_player_callback(defender.name, attack_results['roll_string'], "message")
            send_to_player_callback(defender.name, attack_results['result_msg'], "message")
            if attack_results['hit'] and attack_results['critical_msg']:
                 send_to_player_callback(defender.name, attack_results['critical_msg'], "message")
            
            defender_info = world.get_player_info(defender.name.lower())
            if defender_info: sid_to_skip = defender_info.get("sid")
        
        # Broadcast to room (skipping the defender if they are a player, as they got detailed msgs)
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
                    
                    defender.move_to_room(
                        config.PLAYER_DEATH_ROOM_ID, 
                        "You have been slain... You awaken on a cold stone altar, feeling weak."
                    )
                    
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
                # NPC Defender
                defender_uid = defender.get("uid")
                new_hp = world.modify_monster_hp(
                    defender_uid,
                    defender.get("max_hp", 1),
                    damage
                )
                
                if new_hp <= 0 or is_fatal:
                    consequence_msg = f"**The {defender['name']} has been DEFEATED!**"
                    broadcast_callback(attacker_room_id, consequence_msg, "combat_death", skip_sid=sid_to_skip)
                    
                    corpse_data = loot_system.create_corpse_object_data(
                        defeated_entity_template=defender, 
                        defeated_entity_runtime_id=defender_uid, 
                        game_items_data=world.game_items,
                        game_loot_tables=world.game_loot_tables,
                        game_equipment_tables_data={} 
                    )
                    
                    with world.room_lock:
                        room_data = world.game_rooms.get(attacker_room_id)
                        if room_data:
                            room_data["objects"].append(corpse_data)
                            if defender in room_data["objects"]:
                                room_data["objects"].remove(defender)
                    
                    broadcast_callback(attacker_room_id, f"The {corpse_data['name']} falls to the ground.", "ambient")
                    
                    respawn_time = defender.get("respawn_time_seconds", 300)
                    respawn_chance = defender.get(
                        "respawn_chance_per_tick", 
                        getattr(config, "NPC_DEFAULT_RESPAWN_CHANCE", 0.2)
                    )
                    
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
        with world.combat_lock:
            if combatant_id in world.combat_state:
                 world.combat_state[combatant_id]["next_action_time"] = current_time + rt_seconds