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
TICK_INTERVAL_SECONDS = 30    # How often the main game loop runs
PLAYER_TIMEOUT_SECONDS = 600 # 10 minutes

# --- Player & Chargen ---
CHARGEN_START_ROOM = "inn_room"
CHARGEN_COMPLETE_ROOM = "town_square"
PLAYER_DEATH_ROOM_ID = "town_square" # Room player respawns in

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
COMBAT_HIT_THRESHOLD = 0          # (AS - DS) + ADVANTAGE + d100 must be > this to hit
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

# --- Environment ---
TIME_CHANGE_INTERVAL_TICKS = 12
WEATHER_CHANGE_INTERVAL_TICKS = 10
WEATHER_SEVERITY_ORDER = [
    "clear", "light clouds", "overcast", "fog",
    "light rain", "rain", "heavy rain", "storm"
]

# Make it less likely to stay clear
WEATHER_STAY_CLEAR_BASE_CHANCE = 0.50 # (Was 0.65)

# Make the starting chance to worsen from clear higher
WEATHER_WORSEN_FROM_CLEAR_START_CHANCE = 0.20 # (Was 0.10)
WEATHER_WORSEN_ESCALATION = 0.05 # (Was 0.03)
WEATHER_MAX_WORSEN_FROM_CLEAR_CHANCE = 0.85 # (Was 0.75)

# --- This is the MOST IMPORTANT change ---
# Greatly reduce the chance to improve
WEATHER_IMPROVE_BASE_CHANCE = 0.25 # (Was 0.50)

# Increase the chance for bad weather to "stick"
WEATHER_STAY_SAME_BAD_CHANCE = 0.50 # (Was 0.40)

# (This implies a 1.0 - 0.25 - 0.50 = 0.25 chance to WORSEN)

# --- Game Objects ---
EQUIPMENT_SLOTS = {
    "torso": "Torso",
    "mainhand": "Main Hand",
    "offhand": "Off Hand"
}