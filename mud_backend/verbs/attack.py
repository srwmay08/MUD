# mud_backend/verbs/attack.py
import time
from mud_backend.verbs.base_verb import BaseVerb

# --- Import our new game state ---
from mud_backend.core.game_state import RUNTIME_MONSTER_HP, DEFEATED_MONSTERS

# --- Import the legacy code ---
# (Assuming combat.py and loot_handler.py are in mud_backend/core/legacy/)
from mud_backend.core.legacy import combat
from mud_backend.core.legacy import loot_handler

# --- Mock data required by the legacy files ---
# We need to provide the global data these files expect
GAME_ITEMS = {
    "pelt_ruined": {
        "name": "a ruined pelt",
        "description": "A worthless, ruined pelt."
    },
    "monster_claw": {
        "name": "a monster claw",
        "description": "A sharp, wicked-looking claw."
    }
}
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

        # 5. Process the results from the player's attack
        # The combat function modifies RUNTIME_MONSTER_HP directly
        new_hp = RUNTIME_MONSTER_HP.get(monster_id, 0)
        
        if combat_results.get("defeated"):
            self.player.send_message(f"You have defeated the {target_monster_data['name']}!")
            DEFEATED_MONSTERS[monster_id] = time.time()
            
            # --- Loot Integration ---
            # Create a corpse object
            corpse_data = loot_handler.create_corpse_object_data(
                defeated_entity_template=target_monster_data,
                defeated_entity_runtime_id=monster_id,
                game_items_data=GAME_ITEMS,
                game_equipment_tables_data=GAME_EQUIPMENT_TABLES
            )
            
            # Add corpse to the room's objects list
            # Note: This is in-memory only!
            self.room.objects.append(corpse_data)
            # We also need to remove the monster object
            self.room.objects = [obj for obj in self.room.objects if obj.get("monster_id") != monster_id]
            
            self.player.send_message(f"The corpse of a {target_monster_data['name']} falls to the ground.")
            # We would need to save self.room here, but that's a later step
            
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
            
            if monster_attack_results.get("defender_defeated"):
                self.player.send_message("You have been defeated!")
                # Handle player death logic (e.g., move to death room)
                self.player.current_room_id = "town_square" # Send back to town for now
                self.player.hp = 1 # Heal 1 HP