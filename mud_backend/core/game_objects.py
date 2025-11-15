# mud_backend/core/game_objects.py
import math
import time
from mud_backend import config
from mud_backend.core.utils import calculate_skill_bonus, get_stat_bonus
from typing import Optional, List, Dict, Any, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

# === NEW: STAT MODIFIERS ===
# We should store stat modifiers here as well.
# This replaces the old RACE_MODIFIERS in utils.py
RACE_MODIFIERS = {
    "Human": {"STR": 5, "CON": 0, "DEX": 0, "AGI": 0, "LOG": 5, "INT": 5, "WIS": 0, "INF": 0, "ZEA": 5, "ESS": 0, "DIS": 0, "AUR": 0},
    "Wildborn": {"STR": 5, "CON": 5, "DEX": 5, "AGI": 0, "LOG": 5, "INT": 0, "WIS": 0, "INF": -5, "ZEA": 0, "ESS": 5, "DIS": 0, "AUR": 0},
    "High Elf": {"STR": 0, "CON": -5, "DEX": 10, "AGI": 15, "LOG": 0, "INT": 0, "WIS": 0, "INF": 5, "ZEA": 0, "ESS": 0, "DIS": -10, "AUR": 5},
    "Dwarf": {"STR": 10, "CON": 15, "DEX": 0, "AGI": -5, "LOG": 5, "INT": 0, "WIS": 0, "INF": -5, "ZEA": 5, "ESS": 0, "DIS": 15, "AUR": 0},
    "Gnome": {"STR": -5, "CON": 5, "DEX": 5, "AGI": 5, "LOG": 10, "INT": 10, "WIS": 0, "INF": 0, "ZEA": 0, "ESS": 0, "DIS": 5, "AUR": -5},
    "Halfling": {"STR": -10, "CON": 10, "DEX": 10, "AGI": 15, "LOG": 0, "INT": 0, "WIS": 0, "INF": 5, "ZEA": 0, "ESS": 0, "DIS": -5, "AUR": 0},
    "Dark Elf": {"STR": 0, "CON": -5, "DEX": 10, "AGI": 5, "LOG": 0, "INT": 5, "WIS": 5, "INF": -5, "ZEA": -5, "ESS": 0, "DIS": -10, "AUR": 10},
    "Dark Dwarf": {"STR": 5, "CON": 10, "DEX": 5, "AGI": -5, "LOG": 5, "INT": 0, "WIS": 5, "INF": -5, "ZEA": 0, "ESS": 0, "DIS": 10, "AUR": 0},
    "Troll": {"STR": 20, "CON": 20, "DEX": -10, "AGI": -10, "LOG": -10, "INT": -10, "WIS": 0, "INF": -5, "ZEA": 5, "ESS": 0, "DIS": 5, "AUR": -5},
    "Goblin": {"STR": -5, "CON": 5, "DEX": 10, "AGI": 10, "LOG": 0, "INT": 5, "WIS": -5, "INF": 5, "ZEA": 0, "ESS": 0, "DIS": 0, "AUR": -10}
}
DEFAULT_RACE_MODS = { stat: 0 for stat in RACE_MODIFIERS["Human"] }


RACE_DATA = {
    # === NEUTRALS ===
    "Human": {
        "faction": "Neutral",
        "base_hp_max": 140, "hp_gain_per_pf_rank": 5, "base_hp_regen": 2, "spirit_regen_tier": "Moderate",
        "stat_modifiers": RACE_MODIFIERS["Human"],
        "appearance_options": {
            "build": ["slender", "lithe", "lean", "lanky", "average", "athletic", "muscular", "broad", "burly", "stocky", "portly", "heavy-set"],
            "complexion": ["alabaster", "ivory", "porcelain", "pale", "fair", "olive", "tan", "sun-kissed", "ruddy", "bronze", "brown", "dark brown", "black"],
            "eye_color": ["blue", "steel blue", "sea green", "green", "grey", "hazel", "amber", "light brown", "brown", "dark brown", "violet", "black"],
            "hair_color": ["black", "dark brown", "chestnut", "auburn", "light brown", "golden blonde", "ash blonde", "platinum blonde", "fiery red", "strawberry blonde", "grey", "white"]
        }
    },

    "Wildborn": {
        "faction": "Neutral",
        "base_hp_max": 160, "hp_gain_per_pf_rank": 7, "base_hp_regen": 3, "spirit_regen_tier": "Moderate",
        "stat_modifiers": RACE_MODIFIERS["Wildborn"],
        "appearance_options": {
            "build": ["slender", "lithe", "lean", "lanky", "average", "athletic", "muscular", "broad", "burly", "stocky", "portly", "heavy-set"],
            "complexion": ["alabaster", "ivory", "porcelain", "pale", "fair", "olive", "tan", "sun-kissed", "ruddy", "bronze", "brown", "dark brown", "black"],
            "eye_color": ["blue", "steel blue", "sea green", "green", "grey", "hazel", "amber", "light brown", "brown", "dark brown", "violet", "black"],
            "hair_color": ["black", "dark brown", "chestnut", "auburn", "light brown", "golden blonde", "ash blonde", "platinum blonde", "fiery red", "strawberry blonde", "grey", "white"]
        }
    },

    # === THE CONCORDAT FACTION ===
    "High Elf": {
        "faction": "Concordat",
        "base_hp_max": 130, "hp_gain_per_pf_rank": 5, "base_hp_regen": 2, "spirit_regen_tier": "Very Low",
        "stat_modifiers": RACE_MODIFIERS["High Elf"],
        "appearance_options": {
            "build": ["slender", "lithe", "lean", "thin", "graceful", "willowy", "ethereal", "delicate", "statuesque", "lanky", "wiry", "average"],
            "complexion": ["alabaster", "ivory", "porcelain", "pale", "pearly", "fair", "sun-kissed", "faintly golden", "golden", "light bronze", "moonlit silver", "glowing"],
            "eye_color": ["sapphire blue", "bright blue", "emerald green", "deep green", "violet", "amethyst", "lilac", "silver", "moon grey", "golden", "pearly white", "starry black"],
            "hair_color": ["golden", "silver", "stark white", "moonlight white", "platinum blonde", "ash grey", "jet black", "deep blue", "chestnut brown", "dark brown", "auburn", "burnished bronze"]
        }
    },
    "Dwarf": {
        "faction": "Concordat",
        "base_hp_max": 170, "hp_gain_per_pf_rank": 5, "base_hp_regen": 3, "spirit_regen_tier": "High",
        "stat_modifiers": RACE_MODIFIERS["Dwarf"],
        "appearance_options": {
            "height": ["shorter than average", "stocky"],
            "build": ["stocky", "burly", "muscular", "broad-shouldered", "broad", "stout", "thick-set", "powerful", "barrel-chested", "compact", "rugged", "average"],
            "complexion": ["pale", "fair", "stony grey", "iron grey", "ruddy", "earthy tan", "weathered tan", "reddish-brown", "bronze", "deep brown", "mahogany", "coal-dark"],
            "eye_color": ["dark brown", "earthy brown", "brown", "light brown", "black", "obsidian", "steel grey", "iron grey", "hazel", "warm hazel", "amber", "deep blue"],
            "hair_color": ["black", "dark brown", "chestnut brown", "fiery red", "copper", "auburn", "brown", "grey", "ash grey", "steel grey", "silver", "white"]
        }
    },
    "Gnome": {
        "faction": "Concordat",
        "base_hp_max": 120, "hp_gain_per_pf_rank": 4, "base_hp_regen": 2, "spirit_regen_tier": "High",
        "stat_modifiers": RACE_MODIFIERS["Gnome"],
        "appearance_options": {
            "height": ["very short", "short"],
            "build": ["slender", "slight", "small", "nimble", "lean", "wiry", "lanky", "average", "plump", "rounded", "stocky", "compact"],
            "complexion": ["porcelain", "pale", "fair", "rosy", "ruddy", "warm beige", "sun-kissed", "earthy tan", "coppery", "light brown", "brown", "deep brown"],
            "eye_color": ["bright blue", "deep blue", "emerald green", "leaf green", "warm brown", "hazel", "black", "violet", "amethyst", "sparkling grey", "steel grey", "amber"],
            "hair_color": ["brown", "black", "blonde", "white", "grey", "silver", "red", "auburn", "pink", "green", "blue", "purple"]
        }
    },
    "Halfling": {
        "faction": "Concordat",
        "base_hp_max": 120, "hp_gain_per_pf_rank": 4, "base_hp_regen": 2, "spirit_regen_tier": "High",
        "stat_modifiers": RACE_MODIFIERS["Halfling"],
        "appearance_options": {
            "height": ["short", "shorter than average"],
            "build": ["slender", "slight", "lean", "nimble", "wiry", "average", "compact", "hearty", "plump", "rounded", "stocky", "stout"],
            "complexion": ["pale", "ivory", "fair", "rosy", "ruddy", "olive", "sun-kissed", "tan", "bronze", "brown", "dark brown", "mahogany"],
            "eye_color": ["brown", "warm brown", "light brown", "dark brown", "hazel", "amber", "blue", "bright blue", "green", "sea green", "grey", "steel grey"],
            "hair_color": ["black", "dark brown", "brown", "chestnut", "light brown", "auburn", "red", "strawberry blonde", "sandy blonde", "golden blonde", "grey", "white"]
        }
    },

    # === THE DOMINION FACTION ===
    "Dark Elf": {
        "faction": "Dominion",
        "base_hp_max": 120, "hp_gain_per_pf_rank": 6, "base_hp_regen": 2, "spirit_regen_tier": "Very Low",
        "stat_modifiers": RACE_MODIFIERS["Dark Elf"],
        "appearance_options": {
            "build": ["slender", "lithe", "lean", "wiry", "sinewy", "graceful", "athletic", "lanky", "thin", "spindly", "sharp", "gaunt"],
            "complexion": ["chalky white", "pale lavender", "ashen grey", "moon grey", "dusky grey", "storm grey", "violet", "deep purple", "indigo", "midnight blue", "ebony", "obsidian black"],
            "eye_color": ["fiery red", "blood red", "crimson", "glowing pink", "violet", "amethyst", "deep purple", "pale lilac", "pale silver", "glowing white", "solid black", "shadowy black"],
            "hair_color": ["stark white", "moonlight silver", "pale grey", "silver", "ash grey", "steel grey", "jet black", "obsidian black", "shadowy black", "midnight blue", "blood red"]
        }
    },
    "Dark Dwarf": {
        "faction": "Dominion",
        "base_hp_max": 165, "hp_gain_per_pf_rank": 5, "base_hp_regen": 2, "spirit_regen_tier": "Moderate",
        "stat_modifiers": RACE_MODIFIERS["Dark Dwarf"],
        "appearance_options": {
            "height": ["shorter than average", "stocky"],
            "build": ["stocky", "burly", "muscular", "broad", "dense", "stout", "thick-set", "rugged", "sinewy", "compact", "gaunt", "hollow"],
            "complexion": ["deathly pale", "chalk white", "ashen grey", "stony grey", "lead grey", "iron grey", "slate grey", "dull brown", "murky brown", "charcoal", "dark grey", "obsidian"],
            "eye_color": ["pale grey", "charcoal grey", "dull white", "milky white", "sightless white", "empty", "solid black", "obsidian", "dull red", "dark brown", "murky brown", "faded blue"],
            "hair_color": ["black", "jet black", "charcoal", "dull brown", "patchy brown", "steel grey", "ash grey", "patchy grey", "salt-and-pepper", "silver", "white", "stark white"]
        }
    },
    "Troll": {
        "faction": "Dominion",
        "base_hp_max": 190, "hp_gain_per_pf_rank": 7, "base_hp_regen": 6, "spirit_regen_tier": "Very Low",
        "stat_modifiers": RACE_MODIFIERS["Troll"],
        "appearance_options": {
            "height": ["taller than average", "towering", "massive"],
            "build": ["burly", "massive", "towering", "hulking", "muscle-bound", "broad-shouldered", "pot-bellied", "knotted", "gaunt", "lanky", "spindly", "wiry"],
            "complexion": ["pale grey", "rocky grey", "sickly grey-green", "blotchy blue-grey", "damp blue", "dull green", "mossy green", "warty green", "swampy green", "forest green", "dark olive", "dark brown"],
            "eye_color": ["dull yellow", "pale yellow", "milky white", "bloodshot red", "dull orange", "orange", "fiery orange", "glowing green", "solid black", "beady black", "murky brown", "muddy brown"],
            "hair_color": ["none", "coarse black", "greasy black", "patchy black", "mangy brown", "dull brown", "clumpy brown", "patchy grey", "stringy grey", "mossy green", "swampy green", "tufts of moss"]
        }
    },
    "Goblin": {
        "faction": "Dominion",
        "base_hp_max": 110, "hp_gain_per_pf_rank": 5, "base_hp_regen": 3, "spirit_regen_tier": "Moderate",
        "stat_modifiers": RACE_MODIFIERS["Goblin"],
        "appearance_options": {
            "height": ["very short", "short"],
            "build": ["slender", "gaunt", "wiry", "scrawny", "spindly", "lanky", "small", "nimble", "twitchy", "bow-legged", "pot-bellied", "hunched"],
            "complexion": ["pale green", "sickly green", "yellowish-green", "jaundiced yellow", "dull yellow", "olive green", "grey-green", "blotchy green", "dark green", "dull grey", "muddy brown", "murky brown"],
            "eye_color": ["beady yellow", "pale yellow", "sickly yellow", "bloodshot red", "glowing red", "solid black", "beady black", "glowing orange", "dull orange", "bright green", "murky brown"],
            "hair_color": ["none", "greasy black", "coarse black", "dull black", "patchy black", "mangy brown", "muddy brown", "patchy grey", "stringy grey", "tufts of grey", "dull red", "scabby"]
        }
    }
}

class Player:
    # --- REFACTORED: Add 'world' to __init__ ---
    def __init__(self, world: 'World', name: str, current_room_id: str, db_data: Optional[dict] = None):
        self.world = world # Store the world reference
        # --- END REFACTOR ---
        
        self.name = name
        self.current_room_id = current_room_id
        self.db_data = db_data if db_data is not None else {}
        self.messages = [] 
        
        self._id = self.db_data.get("_id") 
        
        # --- NEW: Store the account username ---
        self.account_username: str = self.db_data.get("account_username", "")
        # --- END NEW ---

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
        
        # --- THIS IS THE FIX: Define skills *before* vitals that depend on it ---
        self.skills: Dict[str, int] = self.db_data.get("skills", {})
        # --- END FIX ---
        
        # ---
        # --- NEW: Skill Learning (LBD) Progress
        # ---
        self.skill_learning_progress: Dict[str, int] = self.db_data.get("skill_learning_progress", {})
        # --- END NEW ---
        
        # --- HEALTH, MANA, STAMINA, SPIRIT ---
        # Get from DB first
        self.hp: int = self.db_data.get("hp", 100)
        self.mana: int = self.db_data.get("mana", 100)
        self.stamina: int = self.db_data.get("stamina", 100)
        self.spirit: int = self.db_data.get("spirit", 10)
        
        # --- THIS IS THE FIX: Clamp current vitals to max vitals on load ---
        self.hp = min(self.hp, self.max_hp)
        self.mana = min(self.mana, self.max_mana)
        self.stamina = min(self.stamina, self.max_stamina)
        self.spirit = min(self.spirit, self.max_spirit)
        # --- END FIX ---

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
        self.posture: str = self.db_data.get("posture", "standing")
        
        self.status_effects: List[str] = self.db_data.get("status_effects", [])
        self.next_action_time: float = self.db_data.get("next_action_time", 0.0)

        self.deaths_recent: int = self.db_data.get("deaths_recent", 0)
        self.death_sting_points: int = self.db_data.get("death_sting_points", 0)
        self.con_lost: int = self.db_data.get("con_lost", 0)
        self.con_recovery_pool: int = self.db_data.get("con_recovery_pool", 0)
        
        # --- NEW: Add wound tracking ---
        self.wounds: Dict[str, int] = self.db_data.get("wounds", {})
        # --- END NEW ---

        # --- NEW: Vitals Ability Tracking ---
        self.next_mana_pulse_time: float = self.db_data.get("next_mana_pulse_time", 0.0)
        self.mana_pulse_used: bool = self.db_data.get("mana_pulse_used", False)
        self.last_spellup_use_time: float = self.db_data.get("last_spellup_use_time", 0.0)
        self.spellup_uses_today: int = self.db_data.get("spellup_uses_today", 0)
        self.last_second_wind_time: float = self.db_data.get("last_second_wind_time", 0.0)
        self.stamina_burst_pulses: int = self.db_data.get("stamina_burst_pulses", 0) # > 0 is buff, < 0 is debuff
        # --- REMOVED: next_spirit_regen_time ---
        # --- END NEW ---
        
        # ---
        # --- NEW: Magic Properties
        # ---
        self.prepared_spell: Optional[Dict] = self.db_data.get("prepared_spell", None)
        self.buffs: Dict[str, Dict] = self.db_data.get("buffs", {})
        # --- END NEW ---
        
        # --- NEW: Learned Abilities ---
        self.known_spells: List[str] = self.db_data.get("known_spells", [])
        self.known_maneuvers: List[str] = self.db_data.get("known_maneuvers", [])
        self.completed_quests: List[str] = self.db_data.get("completed_quests", [])
        # --- END NEW ---
        
        # ---
        # --- NEW: Faction Standings
        # ---
        self.factions: Dict[str, int] = self.db_data.get("factions", {})
        # --- END NEW ---

        # --- NEW: Quest Trackers ---
        self.quest_trip_counter: int = self.db_data.get("quest_trip_counter", 0)
        # --- END NEW ---

        # ---
        # --- NEW: Map Tracking ---
        self.visited_rooms: List[str] = self.db_data.get("visited_rooms", [])
        # --- END NEW ---

        # ---
        # --- NEW: GOTO Flag ---
        self.is_goto_active: bool = self.db_data.get("is_goto_active", False)
        # --- END NEW ---


    @property
    def con_bonus(self) -> int:
        # This is the stat *bonus* (e.g., 70 CON -> 10 bonus)
        return get_stat_bonus(self.stats.get("CON", 50), "CON", self.race)
        
    @property
    def race(self) -> str:
        return self.appearance.get("race", "Human")
        
    @property
    def race_data(self) -> dict:
        # --- THIS IS THE FIX ---
        # Update this property to use the new RACE_DATA dict
        return RACE_DATA.get(self.race, RACE_DATA["Human"])
        # --- END FIX ---

    @property
    def base_hp(self) -> int:
        # Per user spec: Base HP = trunc((Strength statistic + Constitution statistic) / 10)
        return math.trunc((self.stats.get("STR", 0) + self.stats.get("CON", 0)) / 10)

    @property
    def max_hp(self) -> int:
        # --- THIS IS THE NEW FORMULA ---
        # Maximum Health = ((STR stat + CON stat) / 10) + (Physical Fitness ranks * Health Point gain rate based on Race)
        
        # self.base_hp is already ((STR + CON) / 10)
        base_hp_val = self.base_hp
        pf_ranks = self.skills.get("physical_fitness", 0)
        hp_gain_rate = self.race_data.get("hp_gain_per_pf_rank", 6)
        
        return base_hp_val + (pf_ranks * hp_gain_rate)
        # --- END NEW FORMULA ---

    @property
    def hp_regeneration(self) -> int:
        # User formula: 2 + (Physical Fitness ranks / 20)
        pf_ranks = self.skills.get("physical_fitness", 0)
        
        # --- THIS IS THE FIX ---
        # Use a static '2' as the base, per user's new formula
        base_regen = 2
        # --- END FIX ---
        
        regen = base_regen + math.trunc(pf_ranks / 20)
        if self.death_sting_points > 0:
            regen = math.trunc(regen * 0.5)
        return max(0, regen)
        
    # ---
    # --- NEW VITALS PROPERTIES ---
    # ---
    
    @property
    def max_mana(self) -> int:
        # Max Mana = INT Bonus + ((LOG Bonus + WIS bonus + INF bonus)/3) + (Harness Power skill bonus / 4) + (Mana Control skill bonus / 3)
        int_b = get_stat_bonus(self.stats.get("INT", 50), "INT", self.race)
        log_b = get_stat_bonus(self.stats.get("LOG", 50), "LOG", self.race)
        wis_b = get_stat_bonus(self.stats.get("WIS", 50), "WIS", self.race)
        inf_b = get_stat_bonus(self.stats.get("INF", 50), "INF", self.race)
        
        hp_ranks = self.skills.get("harness_power", 0)
        mc_ranks = self.skills.get("mana_control", 0)
        
        hp_bonus = calculate_skill_bonus(hp_ranks)
        mc_bonus = calculate_skill_bonus(mc_ranks)
        
        stat_avg = math.trunc((log_b + wis_b + inf_b) / 3)
        hp_avg = math.trunc(hp_bonus / 4)
        mc_avg = math.trunc(mc_bonus / 3)
        
        return int_b + stat_avg + hp_avg + mc_avg
    
    @property
    def max_stamina(self) -> int:
        # Max Stamina = CON bonus + ((STR bonus + AGI bonus + DIS bonus)/3) + (Physical Fitness skill bonus / 3)
        con_b = get_stat_bonus(self.stats.get("CON", 50), "CON", self.race)
        str_b = get_stat_bonus(self.stats.get("STR", 50), "STR", self.race)
        agi_b = get_stat_bonus(self.stats.get("AGI", 50), "AGI", self.race)
        dis_b = get_stat_bonus(self.stats.get("DIS", 50), "DIS", self.race)
        
        pf_ranks = self.skills.get("physical_fitness", 0)
        pf_bonus = calculate_skill_bonus(pf_ranks)
        
        stat_avg = math.trunc((str_b + agi_b + dis_b) / 3)
        pf_avg = math.trunc(pf_bonus / 3)
        
        return con_b + stat_avg + pf_avg

    @property
    def stamina_regen_per_pulse(self) -> int:
        # SR = 20 + trunc(CON bonus / 4.5) + Bonus
        con_b = get_stat_bonus(self.stats.get("CON", 50), "CON", self.race)
        bonus = 0
        if self.posture in ["sitting", "kneeling", "prone"]:
            if self.worn_items.get("mainhand") is None:
                bonus = 5
        
        sr_percent = 20 + math.trunc(con_b / 4.5) + bonus
        
        # Stamina gained per pulse = round(Maximum Stamina * (SR / 100)) + Enhancive Bonus
        enhancive_bonus = 0
        if self.stamina_burst_pulses > 0:
            enhancive_bonus = 15
        elif self.stamina_burst_pulses < 0:
            enhancive_bonus = -15
            
        gain = round(self.max_stamina * (sr_percent / 100.0)) + enhancive_bonus
        return int(gain)

    @property
    def max_spirit(self) -> int:
        # Max Spirit = ESS Bonus + ((ZEA Bonus + WIS Bonus + LOG Bonus)/3) + (Harness Power skill bonus / 4) + (Spirit Control skill bonus / 3)
        # NOTE: "Spirit Control" skill not found, using "spiritual_lore" as the logical equivalent.
        
        ess_b = get_stat_bonus(self.stats.get("ESS", 50), "ESS", self.race)
        zea_b = get_stat_bonus(self.stats.get("ZEA", 50), "ZEA", self.race)
        wis_b = get_stat_bonus(self.stats.get("WIS", 50), "WIS", self.race)
        log_b = get_stat_bonus(self.stats.get("LOG", 50), "LOG", self.race)
        
        hp_ranks = self.skills.get("harness_power", 0)
        sc_ranks = self.skills.get("spiritual_lore", 0) # Using spiritual_lore
        
        hp_bonus = calculate_skill_bonus(hp_ranks)
        sc_bonus = calculate_skill_bonus(sc_ranks)
        
        stat_avg = math.trunc((zea_b + wis_b + log_b) / 3)
        hp_avg = math.trunc(hp_bonus / 4)
        sc_avg = math.trunc(sc_bonus / 3)
        
        # Using 10 base spirit from original implementation
        return 10 + ess_b + stat_avg + hp_avg + sc_avg

    # ---
    # --- NEW REGEN PROPERTIES (from user Option 2) ---
    # ---
    
    @property
    def mana_regeneration_per_pulse(self) -> int:
        # MR = 10 + trunc(INT bonus / 4.5) + (Harness Power skill bonus / 20) + Bonus
        int_b = get_stat_bonus(self.stats.get("INT", 50), "INT", self.race)
        hp_ranks = self.skills.get("harness_power", 0)
        hp_bonus = calculate_skill_bonus(hp_ranks)
        bonus = 0 # TODO: Add bonus for meditating, etc.
        
        mr_percent = 10 + math.trunc(int_b / 4.5) + math.trunc(hp_bonus / 20) + bonus
        
        # Mana gained per pulse = round(Maximum Mana * (MR / 100)) + Enhancive Bonus
        enhancive_bonus = 0 # TODO: Add enhancives
        gain = round(self.max_mana * (mr_percent / 100.0)) + enhancive_bonus
        return int(gain)

    @property
    def spirit_regeneration_per_pulse(self) -> int:
        # SPR = 10 + trunc(ESS bonus / 4.5) + (Harness Power skill bonus / 20) + Bonus
        ess_b = get_stat_bonus(self.stats.get("ESS", 50), "ESS", self.race)
        hp_ranks = self.skills.get("harness_power", 0)
        hp_bonus = calculate_skill_bonus(hp_ranks)
        bonus = 0 # TODO: Add bonus
        
        spr_percent = 10 + math.trunc(ess_b / 4.5) + math.trunc(hp_bonus / 20) + bonus
        
        # Spirit gained per pulse = round(Maximum Spirit * (SPR / 100)) + Enhancive Bonus
        enhancive_bonus = 0 # TODO: Add enhancives
        gain = round(self.max_spirit * (spr_percent / 100.0)) + enhancive_bonus
        return int(gain)

    # ---
    # --- REMOVED OLD REGEN PROPERTIES ---
    # ---
    
    @property
    def effective_mana_control_ranks(self) -> int:
        # Placeholder: Assumes a single-sphere caster
        # TODO: Check profession and hybrid status
        mc_ranks = self.skills.get("elemental_lore", 0) # Just guessing one
        return mc_ranks

    # ---
    # --- END VITALS PROPERTIES ---
    # ---

    @property
    def armor_rt_penalty(self) -> float:
        """
        Calculates the final armor roundtime penalty after
        applying reduction from Armor Use skill bonus.
        """
        # --- FIX: Removed local import ---
        # from mud_backend.core.skill_handler import calculate_skill_bonus 

        armor_id = self.worn_items.get("torso")
        if not armor_id:
            return 0.0
            
        # --- REFACTORED: Get item data from self.world ---
        armor_data = self.world.game_items.get(armor_id)
        # --- END REFACTOR ---
        if not armor_data:
            return 0.0
            
        base_rt = armor_data.get("armor_rt", 0)
        if base_rt == 0:
            return 0.0
            
        armor_use_ranks = self.skills.get("armor_use", 0)
        skill_bonus = calculate_skill_bonus(armor_use_ranks)
        
        if skill_bonus < 10:
            return base_rt
            
        penalty_removed = 1 + math.floor(max(0, skill_bonus - 10) / 20)
        
        final_penalty = max(0.0, base_rt - penalty_removed)
        return final_penalty

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
        # --- REFACTORED: Get level table from self.world ---
        table = self.world.game_level_table
        # --- END REFACTOR ---
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

    def get_equipped_item_data(self, slot: str) -> Optional[dict]:
        """Gets the item data for an equipped item."""
        item_id = self.worn_items.get(slot) 
        if item_id:
            # --- REFACTORED: Get item data from self.world ---
            return self.world.game_items.get(item_id)
            # --- END REFACTOR ---
        return None

    def get_armor_type(self) -> str:
        DEFAULT_UNARMORED_TYPE = "unarmed" # Corrected from "unarmored"
        armor_data = self.get_equipped_item_data("torso")
        if armor_data and armor_data.get("type") == "armor":
            return armor_data.get("armor_type", DEFAULT_UNARMORED_TYPE)
        return DEFAULT_UNARMORED_TYPE
    
    def _stop_combat(self):
        """Stops any combat the player is involved in."""
        player_id = self.name.lower()
        
        # --- REFACTORED: Use world methods ---
        combat_data = self.world.get_combat_state(player_id)
        
        # --- THIS IS THE FIX ---
        # Only proceed if combat_data exists AND is of type "combat"
        if combat_data and combat_data.get("state_type") == "combat":
        # --- END FIX ---
            target_id = combat_data.get("target_id")
            # ---
            # --- THIS IS THE FIX ---
            # ---
            target_name = target_id # Default to UID
            
            # Try to find the target to get its name
            target_obj = self.world.get_player_obj(target_id) # Is it a player?
            if not target_obj:
                # Not a player, search all rooms for an NPC/monster with this UID
                for room in self.world.game_rooms.values():
                    for obj in room.get("objects", []):
                        if obj.get("uid") == target_id:
                            target_obj = obj
                            break
                    if target_obj: break
            
            if target_obj:
                target_name = target_obj.get("name", target_id) if isinstance(target_obj, dict) else target_obj.name
            # ---
            # --- END FIX ---

            self.world.stop_combat_for_all(player_id, target_id)
            self.send_message(f"You flee from the {target_name}!")
        # --- END REFACTORED ---
    
    def move_to_room(self, target_room_id: str, move_message: str):
        """
        Handles all logic for moving a player to a new room.
        Stops combat, updates state, and sends messages.
        """
        from mud_backend.core.room_handler import show_room_to_player

        # --- REFACTORED: Use world methods ---
        new_room_data = self.world.get_room(target_room_id)
        # --- END REFACTOR ---

        if not new_room_data or new_room_data.get("room_id") == "void":
            self.send_message("You try to move, but find only an endless void. You quickly scramble back.")
            return

        new_room = Room(
            room_id=new_room_data["room_id"],
            name=new_room_data["name"],
            description=new_room_data["description"],
            db_data=new_room_data
        )

        self._stop_combat()
        self.current_room_id = target_room_id

        # ---
        # --- NEW: Add to visited rooms list
        if target_room_id not in self.visited_rooms:
            self.visited_rooms.append(target_room_id)
        # --- END NEW ---

        self.send_message(move_message)
        show_room_to_player(self, new_room) # show_room_to_player also needs refactoring

    def to_dict(self) -> dict:
        """Converts player state to a dictionary ready for MongoDB insertion/update."""
        
        self.strength = self.stats.get("STR", self.strength)
        self.agility = self.stats.get("AGI", self.agility)
        
        data = {
            **self.db_data,
            "name": self.name,
            # --- NEW: Save account_username ---
            "account_username": self.account_username,
            # --- END NEW ---
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
            # --- MODIFIED: Save Mana, Stamina, Spirit ---
            # "max_mana": self.max_mana, # Removed, is calculated
            "mana": self.mana,
            # Max stamina is calculated, not stored
            "stamina": self.stamina,
            # Max spirit is calculated, not stored
            "spirit": self.spirit,
            # --- END MODIFIED ---
            "skills": self.skills,
            # ---
            # --- NEW: Save LBD progress
            # ---
            "skill_learning_progress": self.skill_learning_progress,
            # --- END NEW ---
            "inventory": self.inventory,
            "worn_items": self.worn_items,
            "wealth": self.wealth, 
            "ptps": self.ptps,
            "mtps": self.mtps,
            "stps": self.stps,
            "ranks_trained_this_level": self.ranks_trained_this_level,
            "stance": self.stance,
            "posture": self.posture,
            "status_effects": self.status_effects,
            "next_action_time": self.next_action_time,
            "deaths_recent": self.deaths_recent,
            "death_sting_points": self.death_sting_points,
            "con_lost": self.con_lost,
            "con_recovery_pool": self.con_recovery_pool,
            "wounds": self.wounds, # <-- ADD THIS
            # --- NEW: Save Vitals Ability Tracking ---
            "next_mana_pulse_time": self.next_mana_pulse_time,
            "mana_pulse_used": self.mana_pulse_used,
            "last_spellup_use_time": self.last_spellup_use_time,
            "spellup_uses_today": self.spellup_uses_today,
            "last_second_wind_time": self.last_second_wind_time,
            "stamina_burst_pulses": self.stamina_burst_pulses,
            # --- REMOVED: next_spirit_regen_time ---
            # --- END NEW ---
            
            # ---
            # --- NEW: Save Magic Properties
            # ---
            "prepared_spell": self.prepared_spell,
            "buffs": self.buffs,
            # --- END NEW ---
            
            # --- NEW: Save Learned Abilities ---
            "known_spells": self.known_spells,
            "known_maneuvers": self.known_maneuvers,
            "completed_quests": self.completed_quests,
            # --- END NEW ---
            
            # ---
            # --- NEW: Save Factions
            # ---
            "factions": self.factions,
            # --- END NEW ---
            
            # --- NEW: Save Quest Trackers ---
            "quest_trip_counter": self.quest_trip_counter,
            # --- END NEW ---

            # ---
            # --- NEW: Save Map Tracking ---
            "visited_rooms": self.visited_rooms,
            # --- END NEW ---

            # ---
            # --- NEW: Save GOTO Flag ---
            "is_goto_active": self.is_goto_active
            # --- END NEW ---
        }
        
        if self._id:
            data["_id"] = self._id
            
        return data

    # ---
    # --- MODIFIED: get_vitals method
    # ---
    def get_vitals(self) -> Dict[str, Any]:
        """
        Gathers all vital player stats for the GUI and returns them in a dict.
        Includes HP, Mana, Stamina, Spirit, Posture, Status, and Roundtime.
        """
        
        # --- 1. Get Experience Data ---
        exp_label = ""
        exp_to_next = 0
        exp_percent = 0.0
        
        if self.level < 100:
            exp_label = "until next level"
            exp_to_next = self.level_xp_target - self.experience
            
            # Calculate total exp for this level
            last_level_target = self._get_xp_target_for_level(self.level - 1)
            total_exp_for_level = self.level_xp_target - last_level_target
            exp_gained_this_level = self.experience - last_level_target
            
            if total_exp_for_level > 0:
                exp_percent = (exp_gained_this_level / total_exp_for_level) * 100
            
        else: # Level 100+
            exp_label = "to next TP"
            exp_to_next = self.level_xp_target - self.experience
            
            # For post-cap, show progress towards the 2500 chunk
            total_exp_for_level = 2500 # This is the chunk size
            exp_gained_this_level = 2500 - exp_to_next
            
            if total_exp_for_level > 0:
                exp_percent = (exp_gained_this_level / total_exp_for_level) * 100
        
        
        # --- 2. Get Worn Items Data ---
        worn_data = {}
        for slot_id, slot_name in config.EQUIPMENT_SLOTS.items():
            item_id = self.worn_items.get(slot_id)
            if item_id:
                item_data = self.world.game_items.get(item_id)
                if item_data:
                    # Send the data the client needs
                    worn_data[slot_id] = {
                        "name": item_data.get("name", "an item"),
                        "slot_display": slot_name
                    }
        
        # --- 3. Get Vitals ---
        vitals = {
            "health": self.hp,
            "max_health": self.max_hp,
            "mana": self.mana,
            "max_mana": self.max_mana,
            "stamina": self.stamina,
            "max_stamina": self.max_stamina,
            "spirit": self.spirit,
            "max_spirit": self.max_spirit,
            "current_room_id": self.current_room_id, # <-- NEW: Added for map
            # --- NEW: Add Stance ---
            "stance": self.stance,
            # --- NEW: Add Wounds ---
            "wounds": self.wounds,
            # --- NEW: Add Experience ---
            "exp_to_next": exp_to_next,
            "exp_label": exp_label,
            "exp_percent": exp_percent,
            # --- NEW: Add Worn Items ---
            "worn_items": worn_data
        }

        # 4. Get Posture and Status Effects
        vitals["posture"] = self.posture.capitalize()
        vitals["status_effects"] = self.status_effects # This is a list

        # 5. Get Roundtime
        rt_data = self.world.get_combat_state(self.name.lower()) # Use self.world
        rt_end_time_ms = 0
        rt_duration_ms = 0
        rt_type = "hard" # Default to hard
        
        if rt_data:
            rt_end_time_sec = rt_data.get("next_action_time", 0)
            rt_type = rt_data.get("rt_type", "hard") # <-- NEW
            current_time = time.time() # Need current time
            if rt_end_time_sec > current_time:
                rt_end_time_ms = int(rt_end_time_sec * 1000)
                rt_duration_ms = int((rt_end_time_sec - current_time) * 1000)

        vitals["rt_end_time_ms"] = rt_end_time_ms
        vitals["rt_duration_ms"] = rt_duration_ms
        vitals["rt_type"] = rt_type # <-- NEW

        return vitals
    # --- END NEW METHOD ---

    def __repr__(self):
        return f"<Player: {self.name}>"


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