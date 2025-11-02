# core/game_objects.py
from typing import Optional, List, Dict, Any, Tuple
import math
from mud_backend.core import game_state

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
        
        self.hp: int = self.db_data.get("hp", 100)
        self.max_hp: int = self.db_data.get("max_hp", 100)
        self.skills: Dict[str, int] = self.db_data.get("skills", {})
        self.equipped_items: Dict[str, str] = self.db_data.get("equipped_items", {"mainhand": None, "offhand": None, "torso": None})

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

    # --- Add to Field Exp (with diminishing returns) ---
    def add_field_exp(self, nominal_amount: int):
        """
        Adds experience to the field pool, applying diminishing returns.
        """
        pool_cap = self.field_exp_capacity
        current_pool = self.unabsorbed_exp
        
        if current_pool >= pool_cap:
            self.send_message("Your mind is completely saturated. You can learn no more.")
            return

        # Accrual Decline Rate = N * (1 - .05 * ⌊InBucket/100⌋)
        accrual_decline_factor = 1.0 - (0.05 * math.floor(current_pool / 100.0))
        actual_gained = math.trunc(nominal_amount * accrual_decline_factor)
        
        if actual_gained <= 0:
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

    # --- Absorb from Field Exp (on tick) ---
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
            "max_hp": self.max_hp,
            "skills": self.skills,
            "equipped_items": self.equipped_items,
            
            "ptps": self.ptps,
            "mtps": self.mtps,
            "stps": self.stps,
            
            # --- NEW: Save ranks trained ---
            "ranks_trained_this_level": self.ranks_trained_this_level,
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