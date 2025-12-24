# mud_backend/config.py
"""
Central configuration file for the MUD.
All game tuning, constants, and hard-coded values should be stored here.
"""
import os

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "data")
ASSETS_PATH = os.path.join(BASE_DIR, "data", "assets")

# --- System & Debug ---
DEBUG_MODE = True
DEBUG_COMBAT_ROLLS = True
DEBUG_GAME_TICK_RESPAWN_PHASE = True

# --- Access Control ---
# Usernames (lowercase) that automatically get admin privileges on all their characters
ADMIN_ACCOUNTS = ["sevax"] 

# --- Database ---
MONGO_URI = "mongodb://127.0.0.1:27017/"
DATABASE_NAME = "MUD_Dev"

# --- Game Loop & State ---
TICK_INTERVAL_SECONDS = 30    
MONSTER_TICK_INTERVAL_SECONDS = 10 
PLAYER_TIMEOUT_SECONDS = 600 

# --- Player & Chargen ---
CHARGEN_START_ROOM = "inn_room"
CHARGEN_COMPLETE_ROOM = "town_square"
PLAYER_DEATH_ROOM_ID = "temple_of_light"

# --- Healing & Regeneration ---
WOUND_HEAL_TIME_SECONDS = 60      # Time for bandaged Rank 1 wound to scar (Non-Trolls)
TROLL_REGEN_INTERVAL_SECONDS = 60 # Time for Troll natural regeneration tick

# --- Combat System ---
STAT_BONUS_BASELINE = 50          
BAREHANDED_FLAT_DAMAGE = 1
DEFAULT_UNARMORED_TYPE = "unarmored"

# Attack Strength (AS)
MELEE_AS_STAT_BONUS_DIVISOR = 20  
WEAPON_SKILL_AS_BONUS_DIVISOR = 50 
BAREHANDED_BASE_AS = 0

# Defense Strength (DS)
MELEE_DS_STAT_BONUS_DIVISOR = 10  
UNARMORED_BASE_DS = 0
SHIELD_SKILL_DS_BONUS_DIVISOR = 10 

# Combat Rolls
COMBAT_ADVANTAGE_FACTOR = 40      
COMBAT_HIT_THRESHOLD = 100        
COMBAT_DAMAGE_MODIFIER_DIVISOR = 10 

# Roundtime
ROUNDTIME_DEFAULTS = {
    'roundtime_attack': 3.0,
    'roundtime_look': 0.2
}

# --- Loot & Corpses ---
CORPSE_DECAY_TIME_SECONDS = 300   
DEFAULT_DROP_EQUIPPED_CHANCE = 1.0
DEFAULT_DROP_CARRIED_CHANCE = 1.0
NPC_DEFAULT_RESPAWN_CHANCE = 0.2
SKINNING_BASE_RT = 5.0           

# --- Environment ---
TIME_CHANGE_INTERVAL_TICKS = 2
WEATHER_CHANGE_INTERVAL_TICKS = 1
WEATHER_SEVERITY_ORDER = [
    "clear", "light clouds", "overcast", "fog",
    "light rain", "rain", "heavy rain", "storm"
]
WEATHER_STAY_CLEAR_BASE_CHANCE = 0.50
WEATHER_WORSEN_FROM_CLEAR_START_CHANCE = 0.20
WEATHER_WORSEN_ESCALATION = 0.05
WEATHER_MAX_WORSEN_FROM_CLEAR_CHANCE = 0.85
WEATHER_IMPROVE_BASE_CHANCE = 0.25
WEATHER_STAY_SAME_BAD_CHANCE = 0.50

# --- Game Objects & Inventory ---
EQUIPMENT_SLOTS = {
    "mainhand": "Right Hand",
    "offhand": "Left Hand",
    "torso": "Torso",
    "head": "Head",
    "legs_pulled": "Legs (pulled over)",
    "feet_put_on": "Feet (put on)",
    "shoulders_draped": "Shoulders (draped)",
    "back": "Back",
    "waist": "Waist",
    "belt": "Belt",
    "neck": "Neck",
    "wrist_right": "Right Wrist",
    "wrist_left": "Left Wrist",
    "finger_right": "Right Finger",
    "finger_left": "Left Finger",
    "arms": "Arms",
    "legs_attached": "Legs (attached)",
    "earlobe_right": "Right Earlobe",
    "earlobe_left": "Left Earlobe",
    "ankle_right": "Right Ankle",
    "ankle_left": "Left Ankle",
    "front": "Front",
    "hands": "Hands",
    "feet_slip_on": "Feet (slip on)",
    "hair": "Hair",
    "undershirt": "Undershirt",
    "leggings": "Leggings",
    "pin": "Pin (General)",
    "shoulder_slung": "Shoulder (Slung)"
}

# --- Rooms ---
TOWN_ROOM_IDS = [
    "town_square", "ts_south", "inn_room", "inn_front_desk", "ts_north", "ts_east", "ts_west", 
    "ts_northeast", "ts_northwest", "ts_southeast", "ts_southwest",
    "temple_of_light", "elementalist_study", "armory_shop", "furrier_shop",
    "bank_lobby", "town_hall", "apothecary_shop", "barracks",
    "library_archives", "theatre"
]
NODE_ROOM_IDS = ["town_square"] 

# --- Factions ---
FACTION_LEVELS = {
    "ally": 1051,
    "warmly": 701,
    "kindly": 451,
    "amiable": 51,
    "indifferent": -49,
    "apprehensive": -449,
    "dubious": -699,
    "threatening": -700, 
    "scowls": -1050
}

FACTION_NAME_MAP = {
    "townsfolk": "The Townsfolk of the City",
    "orcs": "The Orcs of the Forest"
}

FACTION_RELATIONSHIPS = {
    "orcs": {
        "townsfolk": -2000 
    },
    "townsfolk": {
        "orcs": -2000 
    }
}

# --- MOVED FROM COMMAND_EXECUTOR TO BREAK CIRCULAR IMPORT ---
DIRECTION_MAP = {
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
    "u": "up", "up": "up",         
    "d": "down", "down": "down",   
    "north": "north", "south": "south", "east": "east", "west": "west",
    "northeast": "northeast", "northwest": "northwest", "southeast": "southeast", "southwest": "southwest",
}