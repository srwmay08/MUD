# mud_backend/verbs/attack.py
import time
from mud_backend.verbs.base_verb import BaseVerb

# --- Import our new game state ---
from mud_backend.core.game_state import RUNTIME_MONSTER_HP, DEFEATED_MONSTERS

# --- Import the legacy code ---
# We must place combat.py and loot_handler.py inside a folder
# that Python can see. Let's assume we place them in a new
# 'mud_backend/legacy/' folder.
#
# To make this work, you must:
# 1. Create a folder: `mud_backend/legacy/`
# 2. Place `combat.py`, `loot_handler.py`, etc., inside it.
# 3. Create an empty `mud_backend/legacy/__init__.py` file.
#
# For now, I will assume these files are in `mud_backend/core/`
# for simplicity, but a `legacy` folder is cleaner.
#
# Let's adjust the imports in the legacy files to be relative
# (This is tricky, a better way is to make them part of the package)

# --- A Better Way: Let's treat them as part of our package ---
# 1. Place `combat.py`, `loot_handler.py`, `environment.py`, 
#    and `monster_respawn.py` into `mud_backend/core/`
#
# 2. We will have to edit combat.py to import Player from game_objects
#    (I'll skip that for now and assume the MOCK player is fine)

from mud_backend.core.legacy import combat
from mud_backend.core.legacy import loot_handler

# --- Mock data required by the legacy files ---
# We need to provide the global data these files expect
GAME_ITEMS = {} # We'll need to create this later
GAME_LOOT_TABLES = {
    "well_monster_loot": [
        {"item_id": "pelt_ruined", "chance": 0.5, "quantity": 1},
        {"item_id": "monster_claw", "chance": 0.8, "quantity": [1, 2]}
    ]
}
GAME_EQUIPMENT_TABLES = {}
# --- End Mock Data ---

# --- Monkey-patch the global data into the legacy modules ---
# This is how we give them the data they need
loot_handler.GAME_LOOT_TABLES = GAME_LOOT_TABLES
# (We'd also patch GAME_ITEMS once we have them)


class Attack(BaseVerb):
    """Handles the 'attack' command."""
    
    def execute(self):
        if not self.args:
            self.player.send_message("Attack what?")
            return

        target_name = " ".join(self.args).lower()
        
        # 1. Find the target in the room
        target_monster_data = next((obj for obj in self.room.objects 
                                    if obj['name'].lower() == target_name and obj.get("is_monster")), None)

        if not target_monster_data:
            self.player.send_message(f"You don't see a **{target_name}** here to attack.")
            return

        monster_id = target_monster_data.get("monster_id")
        if not monster_id:
            self.player.send_message("That creature cannot be attacked.")
            return

        # 2. Check if monster is already dead
        if monster_id in DEFEATED_MONSTERS:
            self.player.send_message(f"The {target_monster_data['name']} is already dead.")
            return

        # 3. Get monster's current HP from our new game_state
        if monster_id not in RUNTIME_MONSTER_HP:
            RUNTIME_MONSTER_HP[monster_id] = target_monster_data.get("max_hp", 1)
            
        current_hp = RUNTIME_MONSTER_HP[monster_id]
        
        # 4. Call the legacy combat function
        # We pass our Player object and the monster's data dictionary
        combat_results = combat.handle_player_attack(
            player=self.player,
            target_data=target_monster_data,
            target_type="monster",
            target_name_raw_from_player=target_name,
            game_items_global=GAME_ITEMS,
            monster_runtime_id=monster_id
        )

        # 5. Process the results
        new_hp = RUNTIME_MONSTER_HP.get(monster_id)
        
        if combat_results.get("defeated"):
            self.player.send_message(f"You have defeated the {target_monster_data['name']}!")
            DEFEATED_MONSTERS[monster_id] = time.time()
            
            # --- Loot Integration ---
            # Create a corpse object
            corpse_data = loot_handler.create_corpse_object_data(
                defeated_entity_template=target_monster_data,
                defeated_entity_runtime_id=monster_id,
                game_items_data=GAME_ITEMS, # Still empty, but passed
                game_equipment_tables_data=GAME_EQUIPMENT_TABLES
            )
            
            # Add corpse to the room's objects list
            # Note: This is in-memory only! We need to save the room state.
            self.room.objects.append(corpse_data)
            # We also need to remove the monster object
            self.room.objects = [obj for obj in self.room.objects if obj.get("monster_id") != monster_id]
            
            self.player.send_message(f"The corpse of a {target_monster_data['name']} falls to the ground.")
            # We would need to save self.room here
            
        else:
            # Monster is still alive, update its HP in our state
            RUNTIME_MONSTER_HP[monster_id] = new_hp
            self.player.send_message(f"The {target_monster_data['name']} has {new_hp} HP remaining.")

        # 6. Monster Retaliation (Simple version)
        if self.player.hp > 0 and not combat_results.get("defeated"):
            self.player.send_message(f"The {target_monster_data['name']} attacks you back!")
            
            # Call the *other* combat function
            monster_attack_results = combat.handle_entity_attack(
                attacker_entity_data=target_monster_data,
                attacker_entity_type="monster",
                attacker_runtime_id=monster_id,
                defender_player=self.player,
                game_items_global=GAME_ITEMS
            )
            
            # (We would process player death here)
            if monster_attack_results.get("defender_defeated"):
                self.player.send_message("You have been defeated!")
                # (Handle player death logic)