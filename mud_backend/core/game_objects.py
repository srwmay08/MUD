# core/game_objects.py
from typing import Optional, List, Dict, Any, Tuple
import math
from mud_backend.core import game_state

# --- NEW: Racial Data (based on GSIV tables) ---
# We'll use 'Human' as the default for calculations
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
# --- END NEW ---


class Player:
    def __init__(self, name: str, current_room_id: str, db_data: Optional[dict] = None):
        self.name = name
        self.current_room_id = current_room_id
        self.db_data = db_data if db_data is not None else {}
        self.messages = [] 
        
        self._id = self.db_data.get("_id") 

        # --- REFACTORED XP FIELDS ---
        self.experience: int = self.db_data.get("experience", 0)     # This is TOTAL absorbed XP
        self.unabsorbed_exp: int = self.db_data.get("unabsorbed_exp", 0) # This is the "Field Exp" pool
        self.level: int = self.db_data.get("level", 0) # <-- Default level is 0
        # --- END REFACTORED XP ---
        
        self.stats: Dict[str, int] = self.db_data.get("stats", {})
        
        # --- CHARGEN STAT FIELDS ---
        self.current_stat_pool: List[int] = self.db_data.get("current_stat_pool", [])
        self.best_stat_pool: List[int] = self.db_data.get("best_stat_pool", [])
        self.stats_to_assign: List[int] = self.db_data.get("stats_to_assign", [])
        # --- END CHARGEN STATS ---

        # --- Get XP target for next level ---
        self.level_xp_target: int = self._get_xp_target_for_level(self.level)
        
        # --- TP FIELDS ---
        self.ptps: int = self.db_data.get("ptps", 0) # Physical
        self.mtps: int = self.db_data.get("mtps", 0) # Mental
        self.stps: int = self.db_data.get("stps", 0) # Spiritual
        # --- END TP ---
        
        # --- NEW: Skill rank tracking for "per level" limits ---
        self.ranks_trained_this_level: Dict[str, int] = self.db_data.get("ranks_trained_this_level", {})
        # ---

        self.strength = self.stats.get("STR", 10)
        self.agility = self.stats.get("AGI", 10)
        
        self.game_state: str = self.db_data.get("game_state", "playing")
        self.chargen_step: int = self.db_data.get("chargen_step", 0)
        self.appearance: Dict[str, str] = self.db_data.get("appearance", {})
        
        # --- MODIFIED: HP is now dynamically calculated ---
        self.hp: int = self.db_data.get("hp", 100)
        # self.max_hp is now a @property (see below)
        # --- END MODIFIED ---
        
        self.skills: Dict[str, int] = self.db_data.get("skills", {})
        self.equipped_items: Dict[str, str] = self.db_data.get("equipped_items", {"mainhand": None, "offhand": None, "torso": None})

        # --- NEW: Stance and Death's Sting Fields ---
        self.stance: str = self.db_data.get("stance", "neutral") # offensive, forward, neutral, guarded, defensive
        self.deaths_recent: int = self.db_data.get("deaths_recent", 0)
        self.death_sting_points: int = self.db_data.get("death_sting_points", 0) # XP debt for 0.25x multiplier
        self.con_lost: int = self.db_data.get("con_lost", 0) # How many CON points are missing
        self.con_recovery_pool: int = self.db_data.get("con_recovery_pool", 0) # XP pool to regain CON
        # --- END NEW ---

    # --- NEW: Helper for CON bonus (GSIV style) ---
    @property
    def con_bonus(self) -> int:
        """
        Calculates the Constitution *bonus* (assuming 50 is baseline).
        This is for GSIV formulas, not combat.
        """
        return (self.stats.get("CON", 50) - 50)
        
    # --- NEW: Helper for Race ---
    @property
    def race(self) -> str:
        """Gets the player's race from appearance, default to Human."""
        return self.appearance.get("race", "Human")
        
    @property
    def race_data(self) -> dict:
        """Gets the data block for the player's race."""
        return RACE_DATA.get(self.race, RACE_DATA["Human"])

    # --- NEW: Base HP (Level 0) ---
    @property
    def base_hp(self) -> int:
        """GSIV-style Base HP (Level 0) = (STR + CON) / 10"""
        return math.trunc((self.stats.get("STR", 0) + self.stats.get("CON", 0)) / 10)

    # --- MODIFIED: Max HP is now a dynamic property ---
    @property
    def max_hp(self) -> int:
        """
        Calculates Max HP based on GSIV-style formula:
        Max = (Racial Max + CON Bonus + Bonus from PF)
        """
        pf_ranks = self.skills.get("physical_fitness", 0)
        
        # 1. Get Race Base Max HP
        racial_base_max = self.race_data.get("base_hp_max", 150)
        
        # 2. Get CON Bonus (adds directly, per GSIV)
        con_bonus = self.con_bonus
        
        # 3. Get HP from Physical Fitness
        # Formula: HP per PF rank = Race HP gain rate + trunc(Constitution bonus / 10)
        hp_gain_rate = self.race_data.get("hp_gain_per_pf_rank", 6)
        pf_bonus_per_rank = hp_gain_rate + math.trunc(con_bonus / 10)
        hp_from_pf = pf_ranks * pf_bonus_per_rank
        
        # Total
        # Note: We use self.base_hp (from STR/CON) instead of racial_base_max
        # to match the GSIV "Base HP" formula.
        return self.base_hp + con_bonus + hp_from_pf

    # --- NEW: HP Regeneration Property ---
    @property
    def hp_regeneration(self) -> int:
        """
        Calculates HP recovered per "pulse" (tick)
        Formula: Base Regen + trunc(PF ranks / 20)
        """
        pf_ranks = self.skills.get("physical_fitness", 0)
        base_regen = self.race_data.get("base_hp_regen", 2)
        
        regen = base_regen + math.trunc(pf_ranks / 20)
        
        # Apply death sting penalty (reduced recovery)
        if self.death_sting_points > 0:
            regen = math.trunc(regen * 0.5) # Example: 50% reduction
            
        return max(0, regen) # Ensure it's not negative

    # --- Field Exp Pool Properties ---
    @property
    def field_exp_capacity(self) -> int:
        """Calculates the max size of the field experience pool."""
        # Formula: 800 + LOG + DIS
        return 800 + self.stats.get("LOG", 0) + self.stats.get("DIS", 0)

    @property
    def mind_status(self) -> str:
        """Gets the mind status string based on pool saturation."""
        if self.unabsorbed_exp <= 0:
            return "clear as a bell"
        
        # Handle potential division by zero if capacity is somehow 0
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

    # --- MODIFIED: Add Field Exp (to handle Death's Sting) ---
    def add_field_exp(self, nominal_amount: int):
        """
        Adds experience to the field pool, applying diminishing returns
        and "Death's Sting" penalty.
        """
        
        # --- NEW: Apply Death's Sting 0.25x Multiplier ---
        if self.death_sting_points > 0:
            original_nominal = nominal_amount
            nominal_amount = math.trunc(original_nominal * 0.25)
            
            # The 75% that "vanished" is used to pay down the XP debt
            points_worked_off = original_nominal - nominal_amount
            
            old_sting = self.death_sting_points
            self.death_sting_points -= points_worked_off
            
            if self.death_sting_points <= 0:
                self.death_sting_points = 0
                if old_sting > 0: # Only show if it *just* got cleared
                    self.send_message("You feel the last of death's sting fade.")
            else:
                 self.send_message(f"(You work off {points_worked_off} of death's sting.)")
        # --- END NEW ---

        pool_cap = self.field_exp_capacity
        current_pool = self.unabsorbed_exp
        
        if current_pool >= pool_cap:
            self.send_message("Your mind is completely saturated. You can learn no more.")
            return

        # Accrual Decline Rate = N * (1 - .05 * ⌊InBucket/100⌋)
        accrual_decline_factor = 1.0 - (0.05 * math.floor(current_pool / 100.0))
        actual_gained = math.trunc(nominal_amount * accrual_decline_factor)
        
        if actual_gained <= 0:
            if nominal_amount > 0: # Check if we had points but DR reduced them
                self.send_message("Your mind is too full to learn from this.")
            else:
                self.send_message("You learn nothing new from this.")
            return

        # Check if the gain would oversaturate
        if current_pool + actual_gained > pool_cap:
            actual_gained = pool_cap - current_pool
            self.unabsorbed_exp = pool_cap
            self.send_message(f"Your mind is saturated! You only gain {actual_gained} experience.")
        else:
            self.unabsorbed_exp += actual_gained
            self.send_message(f"You gain {actual_gained} field experience. ({self.mind_status})")

    # --- MODIFIED: Absorb from Field Exp (to handle CON loss recovery) ---
    def absorb_exp_pulse(self, room_type: str = "other") -> bool:
        """
        Absorbs one pulse of experience from the field pool.
        This updates total experience and checks for level-ups.
        Returns True if absorption occurred, False otherwise.
        """
        if self.unabsorbed_exp <= 0:
            return False # Nothing to absorb

        # --- Calculate Absorption Rate based on Room Type ---
        base_rate = 19
        logic_divisor = 7
        
        if room_type == "on_node":
            base_rate = 25
            logic_divisor = 5
        elif room_type == "in_town":
            base_rate = 22
            logic_divisor = 5

        # Logic Bonus: (Logic / Divisor)
        logic_bonus = math.floor(self.stats.get("LOG", 0) / logic_divisor)
        
        # Pool Size Bonus: 1 per 200, max 10
        pool_bonus = min(10, math.floor(self.unabsorbed_exp / 200.0))
        
        # Group Bonus: (Skipping for now)
        group_bonus = 0
        
        amount_to_absorb = int(base_rate + logic_bonus + pool_bonus + group_bonus)
        
        # Ensure we don't absorb more than we have
        amount_to_absorb = min(self.unabsorbed_exp, amount_to_absorb)
        
        if amount_to_absorb <= 0:
            return False

        # --- Apply the absorption ---
        self.unabsorbed_exp -= amount_to_absorb
        self.experience += amount_to_absorb
        
        self.send_message(f"You absorb {amount_to_absorb} experience. ({self.unabsorbed_exp} remaining)")
        
        # --- NEW: Check for CON Recovery ---
        # GSIV: "it takes 2000 experience points to recover 1 point of constitution"
        if self.con_lost > 0:
            self.con_recovery_pool += amount_to_absorb
            points_to_regain = self.con_recovery_pool // 2000 # 2000 XP per CON point
            
            if points_to_regain > 0:
                regained = min(points_to_regain, self.con_lost)
                self.stats["CON"] = self.stats.get("CON", 50) + regained
                self.con_lost -= regained
                self.con_recovery_pool -= (regained * 2000)
                
                self.send_message(f"You feel some of your vitality return! (Recovered {regained} CON)")
        # --- END NEW ---
        
        # --- Check for Level Up ---
        self._check_for_level_up()
        return True # We successfully absorbed

    # --- Level Up Helper ---
    def _get_xp_target_for_level(self, level: int) -> int:
        """
        Gets the TOTAL experience required to have achieved a given level.
        """
        table = game_state.GAME_LEVEL_TABLE
        if not table:
            # Fallback to simple formula if table isn't loaded
            return (level + 1) * 1000 # Lvl 0 -> Lvl 1 = 1000
            
        if level < 0: return 0
        if level >= 100:
            # Post-cap: 2500 XP per TP cycle
            return self.experience + 2500 
            
        # List is 0-indexed:
        # To hit Lvl 1 (from Lvl 0), you need table[0] (2500)
        # To hit Lvl 2 (from Lvl 1), you need table[1] (7500)
        if level < len(table):
            return table[level]
        else:
            # Failsafe if table is shorter than 100
             return self.experience + 999999

    def _calculate_tps_per_level(self) -> Tuple[int, int, int]:
        """
        Calculates TPs gained for one level based on your formulas.
        """
        s = self.stats
        hybrid_bonus = (s.get("AUR", 0) + s.get("DIS", 0)) / 2
        
        # MTPs = 25 + [(LOG + INT + WIS + INF + ((AUR + DIS) / 2)) / 20]
        mtp_calc = 25 + ((s.get("LOG", 0) + s.get("INT", 0) + s.get("WIS", 0) + s.get("INF", 0) + hybrid_bonus) / 20)
        
        # PTPs = 25 + [(STR + CON + DEX + AGI + ((AUR + DIS) / 2)) / 20]
        ptp_calc = 25 + ((s.get("STR", 0) + s.get("CON", 0) + s.get("DEX", 0) + s.get("AGI", 0) + hybrid_bonus) / 20)
        
        # STPs = 25 + [(WIS + INF + FAITH + ESS + ((AUR + DIS) / 2)) / 20]
        # (Assuming FAITH = ZEA)
        stp_calc = 25 + ((s.get("WIS", 0) + s.get("INF", 0) + s.get("ZEA", 0) + s.get("ESS", 0) + hybrid_bonus) / 20)

        return int(ptp_calc), int(mtp_calc), int(stp_calc)

    def _check_for_level_up(self):
        """Checks if absorbed XP passes the next level's threshold."""
        
        # Update target just in case it's 0 (for a new Lvl 0 player)
        if self.level_xp_target == 0:
           self.level_xp_target = self._get_xp_target_for_level(self.level)
           
        # Use a while loop in case of multi-level gain
        while self.experience >= self.level_xp_target:
            if self.level >= 100:
                # --- Post-Cap TP Gain ---
                ptps, mtps = 1, 1 # Per wiki: 1 MTP, 1 PTP
                self.ptps += ptps
                self.mtps += mtps
                self.send_message(f"**You gain 1 MTP and 1 PTP from post-cap experience!**")
                
                # Set next target
                self.level_xp_target = self.experience + 2500
                if self.level_xp_target <= self.experience:
                    # Failsafe for very large XP gains
                    self.level_xp_target = self.experience + 1
            else:
                # --- Normal Level Up ---
                self.level += 1
                
                ptps, mtps, stps = self._calculate_tps_per_level()
                self.ptps += ptps
                self.mtps += mtps
                self.stps += stps
                
                # --- NEW: Reset ranks trained this level ---
                self.ranks_trained_this_level.clear()
                # ---
                
                self.send_message(f"**CONGRATULATIONS! You have advanced to Level {self.level}!**")
                self.send_message(f"You gain: {ptps} PTPs, {mtps} MTPs, {stps} STPs.")
                self.send_message("Your skill training limits have been reset for this level.")
                
                # Set new XP target
                self.level_xp_target = self._get_xp_target_for_level(self.level)

    def send_message(self, message: str):
        """Adds a message to the player's output queue."""
        self.messages.append(message)

    # --- COMBAT HELPER METHODS ---
    def get_equipped_item_data(self, slot: str, game_items_global: dict) -> Optional[dict]:
        """Gets the item data for an equipped item."""
        item_id = self.equipped_items.get(slot)
        if item_id:
            return game_items_global.get(item_id)
        return None

    def get_armor_type(self, game_items_global: dict) -> str:
        """Gets the player's current armor type from their torso slot."""
        DEFAULT_UNARMORED_TYPE = "unarmored" 
        
        armor_data = self.get_equipped_item_data("torso", game_items_global)
        if armor_data and armor_data.get("type") == "armor":
            return armor_data.get("armor_type", DEFAULT_UNARMORED_TYPE)
        return DEFAULT_UNARMORED_TYPE
    
    # --- END COMBAT HELPER METHODS ---

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
            # max_hp is not saved, it's calculated
            "skills": self.skills,
            "equipped_items": self.equipped_items,
            
            "ptps": self.ptps,
            "mtps": self.mtps,
            "stps": self.stps,
            
            "ranks_trained_this_level": self.ranks_trained_this_level,
            
            # --- NEW: Save stance and death penalties ---
            "stance": self.stance,
            "deaths_recent": self.deaths_recent,
            "death_sting_points": self.death_sting_points,
            "con_lost": self.con_lost,
            "con_recovery_pool": self.con_recovery_pool,
            # ---
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
        
        # This field is no longer used by the new XP system
        self.unabsorbed_social_exp = self.db_data.get("unabsorbed_social_exp", 0) 
        
        self.objects: List[Dict[str, Any]] = self.db_data.get("objects", []) 
        
        # Holds a dictionary of { "direction": "target_room_id" }
        self.exits: Dict[str, str] = self.db_data.get("exits", {})

    def to_dict(self) -> dict:
        """Converts room state to a dictionary ready for MongoDB update."""
        
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
            data["_id"] = self.to_dict
        return data

    def __repr__(self):
        return f"<Room: {self.name}>"