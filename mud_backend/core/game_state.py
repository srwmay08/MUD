# mud_backend/core/game_state.py
# This file will hold all "live" game data that needs to persist in memory
# between commands. This is our bridge to a "stateful" server.

# Holds the current, non-max HP of all active monsters
# Key: "unique_monster_id" (e.g., "well_bottom_stirring_monster")
# Value: current_hp
RUNTIME_MONSTER_HP = {}

# Holds the "dead" status of monsters
# Key: "unique_monster_id"
# Value: timestamp of death
DEFEATED_MONSTERS = {}