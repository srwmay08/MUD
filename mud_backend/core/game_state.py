# mud_backend/core/game_state.py
import time

# Holds the current, non-max HP of all active monsters
# Key: "unique_monster_id" (e.g., "well_bottom_stirring_monster")
# Value: current_hp
RUNTIME_MONSTER_HP = {}

# Holds the "dead" status of monsters
# Key: "unique_monster_id"
# Value: timestamp of death
DEFEATED_MONSTERS = {}

# --- NEW GLOBAL STATE ---

# Cache for all rooms, loaded from DB at startup.
# This is our "live world."
# Key: room_id, Value: room_data dictionary
GAME_ROOMS = {}

# Timestamp of the last time the global game loop ran
LAST_GAME_TICK_TIME = time.time()

# How many seconds must pass before the loop runs again
TICK_INTERVAL_SECONDS = 10