# mud_backend/config.py
"""
Central configuration file for the MUD.
All game tuning, constants, and hard-coded values should be stored here.
"""

# --- System & Debug ---
DEBUG_MODE = True
DEBUG_COMBAT_ROLLS = True
DEBUG_GAME_TICK_RESPAWN_PHASE = True

# --- Database ---
MONGO_URI = "mongodb://localhost:27017/"
DATABASE_NAME = "MUD_Dev"

# --- Game Loop & State ---
TICK_INTERVAL_SECONDS = 30    # Global tick: Regens, Env, Time, '>' prompt
MONSTER_TICK_INTERVAL_SECONDS = 10 # Independent monster movement tick
PLAYER_TIMEOUT_SECONDS = 600 # 10 minutes

# --- Player & Chargen ---
CHARGEN_START_ROOM = "inn_room"
CHARGEN_COMPLETE_ROOM = "town_square"
# --- MODIFIED: Player respawns in the new temple room ---
PLAYER_DEATH_ROOM_ID = "temple_of_light" # Was "town_square"
# --- END MODIFIED ---

# --- Combat System ---
STAT_BONUS_BASELINE = 50          # Stats below this give no bonus
BAREHANDED_FLAT_DAMAGE = 1
DEFAULT_UNARMORED_TYPE = "unarmored"

# Attack Strength (AS)
MELEE_AS_STAT_BONUS_DIVISOR = 20  # (STR - BASELINE) / 20
WEAPON_SKILL_AS_BONUS_DIVISOR = 50 # SKILL / 50
BAREHANDED_BASE_AS = 0

# Defense Strength (DS)
MELEE_DS_STAT_BONUS_DIVISOR = 10  # (AGI - BASELINE) / 10
UNARMORED_BASE_DS = 0
SHIELD_SKILL_DS_BONUS_DIVISOR = 10 # SKILL / 10

# Combat Rolls
COMBAT_ADVANTAGE_FACTOR = 40      # Base "hit chance" added to roll
COMBAT_HIT_THRESHOLD = 100        # (AS - DS) + ADVANTAGE + d100 must be > this to hit
COMBAT_DAMAGE_MODIFIER_DIVISOR = 10 # (ROLL_RESULT - THRESHOLD) / 10 = Bonus Damage

# Roundtime
ROUNDTIME_DEFAULTS = {
    'roundtime_attack': 3.0,
    'roundtime_look': 0.2
}

# --- Loot & Corpses ---
CORPSE_DECAY_TIME_SECONDS = 300   # 5 minutes
DEFAULT_DROP_EQUIPPED_CHANCE = 1.0
DEFAULT_DROP_CARRIED_CHANCE = 1.0
NPC_DEFAULT_RESPAWN_CHANCE = 0.2
# --- NEW: Config for skinning RT ---
SKINNING_BASE_RT = 5.0           # Base 15s for skinning, reduced by skill
# --- END NEW ---

# --- Environment ---
TIME_CHANGE_INTERVAL_TICKS = 12
WEATHER_CHANGE_INTERVAL_TICKS = 10
WEATHER_SEVERITY_ORDER = [
    "clear", "light clouds", "overcast", "fog",
    "light rain", "rain", "heavy rain", "storm"
]
# ... (Weather chances) ...
WEATHER_STAY_CLEAR_BASE_CHANCE = 0.50
WEATHER_WORSEN_FROM_CLEAR_START_CHANCE = 0.20
WEATHER_WORSEN_ESCALATION = 0.05
WEATHER_MAX_WORSEN_FROM_CLEAR_CHANCE = 0.85
WEATHER_IMPROVE_BASE_CHANCE = 0.25
WEATHER_STAY_SAME_BAD_CHANCE = 0.50

# --- NEW: Game Objects & Inventory ---
# This defines all wearable locations.
# key: slot_id, value: display_name
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

# --- NEW: EXP ABSORPTION ROOMS ---
# --- MODIFIED: Added new temple/study rooms to the town list ---
TOWN_ROOM_IDS = [
    "town_square", "ts_south", "inn_room", "ts_north", "ts_east", "ts_west", 
    "ts_northeast", "ts_northwest", "ts_southeast", "ts_southwest",
    "temple_of_light", "elementalist_study" # <-- NEW
]
# --- END MODIFIED ---
NODE_ROOM_IDS = ["town_square"] 
# ---