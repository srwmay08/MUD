# mud_backend/core/game_state.py
import time
from mud_backend import config # <-- NEW IMPORT

# Holds the current, non-max HP of all active monsters
RUNTIME_MONSTER_HP = {}

# Holds the "dead" status of monsters
DEFEATED_MONSTERS = {}

# Cache for all rooms, loaded from DB at startup.
GAME_ROOMS = {}

# --- NEW: Global Data Dictionaries ---
GAME_MONSTER_TEMPLATES = {} # Key: monster_id, Value: monster_data dict
GAME_LOOT_TABLES = {}       # Key: loot_table_id, Value: loot_table list
GAME_ITEMS = {}             # Key: item_id, Value: item_data dict
GAME_LEVEL_TABLE = {}       # <-- NEW: Holds the XP totals for levels
# ---

# Timestamp of the last time the global game loop ran
LAST_GAME_TICK_TIME = time.time()

# How many seconds must pass before the loop runs again
TICK_INTERVAL_SECONDS = config.TICK_INTERVAL_SECONDS # <-- CHANGED

# Global tick counter
GAME_TICK_COUNTER = 0

# --- UPDATED: ACTIVE PLAYER SESSION HANDLER ---
# Key: player_name (lowercase)
# Value: {"sid": "...", "current_room_id": "...", "last_seen": ..., "player_obj": <Player>}
ACTIVE_PLAYERS = {}

# How long (in seconds) a player can be idle before
# being "pruned" from the active list.
PLAYER_TIMEOUT_SECONDS = config.PLAYER_TIMEOUT_SECONDS # <-- CHANGED

# --- NEW: COMBAT STATE TRACKER ---
# Key: combatant_id (player_name.lower() or monster_id)
# Value: {"target_id": "...", "next_action_time": 12345.67, "current_room_id": "..."}
COMBAT_STATE = {}