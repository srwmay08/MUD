# mud_backend/core/game_state.py
import time

# Holds the current, non-max HP of all active monsters
RUNTIME_MONSTER_HP = {}

# Holds the "dead" status of monsters
DEFEATED_MONSTERS = {}

# Cache for all rooms, loaded from DB at startup.
GAME_ROOMS = {}

# Timestamp of the last time the global game loop ran
LAST_GAME_TICK_TIME = time.time()

# How many seconds must pass before the loop runs again
TICK_INTERVAL_SECONDS = 10 

# Global tick counter
GAME_TICK_COUNTER = 0

# --- UPDATED: ACTIVE PLAYER SESSION HANDLER ---
# Holds the state of all currently "online" players
# Key: request.sid (session ID from Socket.IO)
# Value: {"player_name": "...", "current_room_id": "..."}
ACTIVE_PLAYERS = {}

# How long (in seconds) a player can be idle before
# being "pruned" from the active list. (This is now less critical)
PLAYER_TIMEOUT_SECONDS = 300 # 5 minutes