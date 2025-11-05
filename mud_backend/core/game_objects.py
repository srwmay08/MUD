# core/game_objects.py
from typing import Optional, List, Dict, Any, Tuple
import math
from mud_backend.core import game_state
# --- NEW IMPORT ---
from mud_backend import config
# --- REMOVED IMPORT: This was causing the circular dependency ---
# from mud_backend.core.skill_handler import calculate_skill_bonus 
# ---

# --- (RACE_DATA dictionary is unchanged) ---
RACE_DATA = {
    "Human": {
        "base_hp_max": 150,
        "hp_gain_per_pf_rank": 6,
        "base_hp_regen": 2
    },
    "Elf": {
        "base_hp_max": 130,
        "hp_gain_per_pf_rank": 5,
        "base_hp_regen": 1
    },
    "Dwarf": {
        "base_hp_max": 140,
        "hp_gain_per_pf_rank": 6,
        "base_hp_regen": 3
    },
    "Dark Elf": {
        "base_hp_max": 120,
        "hp_gain_per_pf_rank": 5,
        "base_hp_regen": 1
    }
}


# --- (Player class __init__ is unchanged) ---
class Player:
    def __init__(self, name: str, current_room_id: str, db_data: Optional[dict] = None):
        # ... (init unchanged) ...
        self.name = name
        self.current_room_id = current_room_id
        self.db_data = db_data if db_data is not None else {}
        self.messages = [] 
        
        self._id = self.db_data.get("_id") 

        self.experience: int = self.db_data.get("experience", 0)
        self.unabsorbed_exp: int = self.db_data.get("unabsorbed_exp", 0)
        self.level: int = self.db_data.get("level", 0)
        self.stats: Dict[str, int] = self.db_data.get("stats", {})
        self.current_stat_pool: List[int] = self.db_data.get("current_stat_pool", [])
        self.best_stat_pool: List[int] = self.db_data.get("best_stat_pool", [])
        self.stats_to_assign: List[int] = self.db_data.get("stats_to_assign", [])
        self.level_xp_target: int = self._get_xp_target_for_level(self.level)
        self.ptps: int = self.db_data.get("ptps", 0)
        self.mtps: int = self.db_data.get("mtps", 0)
        self.stps: int = self.db_data.get("stps", 0)
        self.ranks_trained_this_level: Dict[str, int] = self.db_data.get("ranks_trained_this_level", {})
        self.strength = self.stats.get("STR", 10)
        self.agility = self.stats.get("AGI", 10)
        self.game_state: str = self.db_data.get("game_state", "playing")
        self.chargen_step: int = self.db_data.get("chargen_step", 0)
        self.appearance: Dict[str, str] = self.db_data.get("appearance", {})
        self.hp: int = self.db_data.get("hp", 100)
        self.skills: Dict[str, int] = self.db_data.get("skills", {})

        self.inventory: List[str] = self.db_data.get("inventory", [])
        self.worn_items: Dict[str, Optional[str]] = self.db_data.get("worn_items", {})
        for slot_key in config.EQUIPMENT_SLOTS.keys():
            if slot_key not in self.worn_items:
                self.worn_items[slot_key] = None

        self.wealth: Dict[str, Any] = self.db_data.get("wealth", {
            "silvers": 0,
            "notes": [], 
            "bank_silvers": 0 
        })

        self.stance: str = self.db_data.get("stance", "neutral")
        self.deaths_recent: int = self.db_data.get("deaths_recent", 0)
        self.death_sting_points: int = self.db_data.get("death_sting_points", 0)
        self.con_lost: int = self.db_data.get("con_lost", 0)
        self.con_recovery_pool: int = self.db_data.get("con_recovery_pool", 0)
        
        self.status_effects: List[str] = self.db_data.get("status_effects", [])

    @property
    def con_bonus(self) -> int:
        return (self.stats.get("CON", 50) - 50)
        
    @property
    def race(self) -> str:
        return self.appearance.get("race", "Human")
        
    @property
    def race_data(self) -> dict:
        return RACE_DATA.get(self.race, RACE_DATA["Human"])

    @property
    def base_hp(self) -> int:
        return math.trunc((self.stats.get("STR", 0) + self.stats.get("CON", 0)) / 10)

    @property
    def max_hp(self) -> int:
        pf_ranks = self.skills.get("physical_fitness", 0)
        racial_base_max = self.race_data.get("base_hp_max", 150)
        con_bonus = self.con_bonus
        hp_gain_rate = self.race_data.get("hp_gain_per_pf_rank", 6)
        pf_bonus_per_rank = hp_gain_rate + math.trunc(con_bonus / 10)
        hp_from_pf = pf_ranks * pf_bonus_per_rank
        return self.base_hp + con_bonus + hp_from_pf

    @property
    def hp_regeneration(self) -> int:
        pf_ranks = self.skills.get("physical_fitness", 0)
        base_regen = self.race_data.get("base_hp_regen", 2)
        regen = base_regen + math.trunc(pf_ranks / 20)
        if self.death_sting_points > 0:
            regen = math.trunc(regen * 0.5)
        return max(0, regen)
        
    # ---
    # --- MODIFIED PROPERTY: armor_rt_penalty ---
    # ---
    @property
    def armor_rt_penalty(self) -> float:
        """
        Calculates the final armor roundtime penalty after
        applying reduction from Armor Use skill bonus.
        """
        # --- THIS IS THE FIX ---
        # Import here to avoid circular dependency
        from mud_backend.core.skill_handler import calculate_skill_bonus
        # --- END FIX ---

        armor_id = self.worn_items.get("torso")
        if not armor_id:
            return 0.0
            
        armor_data = game_state.GAME_ITEMS.get(armor_id)
        if not armor_data:
            return 0.0
            
        base_rt = armor_data.get("armor_rt", 0)
        if base_rt == 0:
            return 0.0
            
        # Get Armor Use skill bonus
        armor_use_ranks = self.skills.get("armor_use", 0)
        skill_bonus = calculate_skill_bonus(armor_use_ranks)
        
        # Each 20 bonus points removes 1s, but the first is removed at 10.
        if skill_bonus < 10:
            return base_rt
            
        # At 10 bonus, 1s is removed.
        # At 30 bonus, 2s are removed.
        # At 50 bonus, 3s are removed.
        # Formula: 1 + floor((bonus - 10) / 20)
        penalty_removed = 1 + math.floor(max(0, skill_bonus - 10) / 20)
        
        # TODO: Add Dex/Agi offsets
        
        final_penalty = max(0.0, base_rt - penalty_removed)
        return final_penalty
    # ---
    # --- END MODIFIED PROPERTY ---
    # ---

    @property
    def field_exp_capacity(self) -> int:
        return 800 + self.stats.get("LOG", 0) + self.stats.get("DIS", 0)

    @property
    def mind_status(self) -> str:
        if self.unabsorbed_exp <= 0:
            return "clear as a bell"
        capacity = self.field_exp_capacity
        if capacity == 0:
            return "completely saturated"
        saturation = self.unabsorbed_exp / capacity
        if saturation > 1.0: return "completely saturated"
        if saturation > 0.9: return "must rest"
        if saturation > 0.75: return "numbed"
        if saturation > 0.62: return "becoming numbed"
        if saturation > 0.5: return "muddled"
        if saturation > 0.25: return "clear"
        return "fresh and clear"

    def add_field_exp(self, nominal_amount: int):
        if self.death_sting_points > 0:
            original_nominal = nominal_amount
            nominal_amount = math.trunc(original_nominal * 0.25)
            points_worked_off = original_nominal - nominal_amount
            old_sting = self.death_sting_points
            self.death_sting_points -= points_worked_off
            if self.death_sting_points <= 0:
                self.death_sting_points = 0
                if old_sting > 0:
                    self.send_message("You feel the last of death's sting fade.")
            else:
                 self.send_message(f"(You work off {points_worked_off} of death's sting.)")

        pool_cap = self.field_exp_capacity
        current_pool = self.unabsorbed_exp
        if current_pool >= pool_cap:
            self.send_message("Your mind is completely saturated. You can learn no more.")
            return
        accrual_decline_factor = 1.0 - (0.05 * math.floor(current_pool / 100.0))
        actual_gained = math.trunc(nominal_amount * accrual_decline_factor)
        if actual_gained <= 0:
            if nominal_amount > 0:
                self.send_message("Your mind is too full to learn from this.")
            else:
                self.send_message("You learn nothing new from this.")
            return
        if current_pool + actual_gained > pool_cap:
            actual_gained = pool_cap - current_pool
            self.unabsorbed_exp = pool_cap
            self.send_message(f"Your mind is saturated! You only gain {actual_gained} experience.")
        else:
            self.unabsorbed_exp += actual_gained
            self.send_message(f"You gain {actual_gained} field experience. ({self.mind_status})")

    def absorb_exp_pulse(self, room_type: str = "other") -> bool:
        if self.unabsorbed_exp <= 0:
            return False
        base_rate = 19
        logic_divisor = 7
        if room_type == "on_node":
            base_rate = 25
            logic_divisor = 5
        elif room_type == "in_town":
            base_rate = 22
            logic_divisor = 5
        logic_bonus = math.floor(self.stats.get("LOG", 0) / logic_divisor)
        pool_bonus = min(10, math.floor(self.unabsorbed_exp / 200.0))
        group_bonus = 0
        amount_to_absorb = int(base_rate + logic_bonus + pool_bonus + group_bonus)
        amount_to_absorb = min(self.unabsorbed_exp, amount_to_absorb)
        if amount_to_absorb <= 0:
            return False
        self.unabsorbed_exp -= amount_to_absorb
        self.experience += amount_to_absorb
        self.send_message(f"You absorb {amount_to_absorb} experience. ({self.unabsorbed_exp} remaining)")
        if self.con_lost > 0:
            self.con_recovery_pool += amount_to_absorb
            points_to_regain = self.con_recovery_pool // 2000
            if points_to_regain > 0:
                regained = min(points_to_regain, self.con_lost)
                self.stats["CON"] = self.stats.get("CON", 50) + regained
                self.con_lost -= regained
                self.con_recovery_pool -= (regained * 2000)
                self.send_message(f"You feel some of your vitality return! (Recovered {regained} CON)")
        self._check_for_level_up()
        return True

    def _get_xp_target_for_level(self, level: int) -> int:
        table = game_state.GAME_LEVEL_TABLE
        if not table:
            return (level + 1) * 1000
        if level < 0: return 0
        if level >= 100:
            return self.experience + 2500 
        if level < len(table):
            return table[level]
        else:
             return self.experience + 999999

    def _calculate_tps_per_level(self) -> Tuple[int, int, int]:
        s = self.stats
        hybrid_bonus = (s.get("AUR", 0) + s.get("DIS", 0)) / 2
        mtp_calc = 25 + ((s.get("LOG", 0) + s.get("INT", 0) + s.get("WIS", 0) + s.get("INF", 0) + hybrid_bonus) / 20)
        ptp_calc = 25 + ((s.get("STR", 0) + s.get("CON", 0) + s.get("DEX", 0) + s.get("AGI", 0) + hybrid_bonus) / 20)
        stp_calc = 25 + ((s.get("WIS", 0) + s.get("INF", 0) + s.get("ZEA", 0) + s.get("ESS", 0) + hybrid_bonus) / 20)
        return int(ptp_calc), int(mtp_calc), int(stp_calc)

    def _check_for_level_up(self):
        if self.level_xp_target == 0:
           self.level_xp_target = self._get_xp_target_for_level(self.level)
        while self.experience >= self.level_xp_target:
            if self.level >= 100:
                ptps, mtps = 1, 1
                self.ptps += ptps
                self.mtps += mtps
                self.send_message(f"**You gain 1 MTP and 1 PTP from post-cap experience!**")
                self.level_xp_target = self.experience + 2500
                if self.level_xp_target <= self.experience:
                    self.level_xp_target = self.experience + 1
            else:
                self.level += 1
                ptps, mtps, stps = self._calculate_tps_per_level()
                self.ptps += ptps
                self.mtps += mtps
                self.stps += stps
                self.ranks_trained_this_level.clear()
                self.send_message(f"**CONGRATULATIONS! You have advanced to Level {self.level}!**")
                self.send_message(f"You gain: {ptps} PTPs, {mtps} MTPs, {stps} STPs.")
                self.send_message("Your skill training limits have been reset for this level.")
                self.level_xp_target = self._get_xp_target_for_level(self.level)

    def send_message(self, message: str):
        self.messages.append(message)

    def get_equipped_item_data(self, slot: str, game_items_global: dict) -> Optional[dict]:
        item_id = self.worn_items.get(slot) 
        if item_id:
            return game_items_global.get(item_id)
        return None

    def get_armor_type(self, game_items_global: dict) -> str:
        DEFAULT_UNARMORED_TYPE = "unarmored" 
        armor_data = self.get_equipped_item_data("torso", game_items_global)
        if armor_data and armor_data.get("type") == "armor":
            return armor_data.get("armor_type", DEFAULT_UNARMORED_TYPE)
        return DEFAULT_UNARMORED_TYPE
    
    def to_dict(self) -> dict:
        """Converts player state to a dictionary ready for MongoDB insertion/update."""
        
        self.strength = self.stats.get("STR", self.strength)
        self.agility = self.stats.get("AGI", self.agility)
        
        data = {
            **self.db_data,
            "name": self.name,
            "current_room_id": self.current_room_id,
            "experience": self.experience, 
            "unabsorbed_exp": self.unabsorbed_exp,
            "level": self.level,           
            "strength": self.strength,
            "agility": self.agility,
            "stats": self.stats,
            "current_stat_pool": self.current_stat_pool,
            "best_stat_pool": self.best_stat_pool,
            "stats_to_assign": self.stats_to_assign,
            "game_state": self.game_state,
            "chargen_step": self.chargen_step,
            "appearance": self.appearance,
            "hp": self.hp,
            "skills": self.skills,
            "inventory": self.inventory,
            "worn_items": self.worn_items,
            "wealth": self.wealth, 
            "ptps": self.ptps,
            "mtps": self.mtps,
            "stps": self.stps,
            "ranks_trained_this_level": self.ranks_trained_this_level,
            "stance": self.stance,
            "deaths_recent": self.deaths_recent,
            "death_sting_points": self.death_sting_points,
            "con_lost": self.con_lost,
            "con_recovery_pool": self.con_recovery_pool,
            "status_effects": self.status_effects,
        }
        
        if self._id:
            data["_id"] = self._id
            
        return data

    def __repr__(self):
        return f"<Player: {self.name}>"


# --- (Room class is unchanged) ---
class Room:
    def __init__(self, room_id: str, name: str, description: str, db_data: Optional[dict] = None):
        self.room_id = room_id
        self.name = name
        self.description = description
        self.db_data = db_data if db_data is not None else {}
        self._id = self.db_data.get("_id") 
        self.unabsorbed_social_exp = self.db_data.get("unabsorbed_social_exp", 0) 
        self.objects: List[Dict[str, Any]] = self.db_data.get("objects", []) 
        self.exits: Dict[str, str] = self.db_data.get("exits", {})

    def to_dict(self) -> dict:
        data = {
            **self.db_data,
            "room_id": self.room_id,
            "name": self.name,
            "description": self.description,
            "unabsorbed_social_exp": self.unabsorbed_social_exp,
            "objects": self.objects,
            "exits": self.exits,
        }
        
        if self._id:
            data["_id"] = self._id

        return data

    def __repr__(self):
        return f"<Room: {self.name}>"