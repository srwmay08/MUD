# mud_backend/verbs/attack.py
import time
from mud_backend.verbs.base_verb import BaseVerb

# --- NEW, CLEAN IMPORTS ---
from mud_backend.core.game_state import RUNTIME_MONSTER_HP, DEFEATED_MONSTERS
from mud_backend.core import combat_system
from mud_backend.core import loot_system
# ---

# --- Mock data required by the new systems ---
# Eventually, this data should be loaded globally,
# but for now, the verb can provide it.
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


class Attack(BaseVerb):
    """
    Handles the 'attack' command.
    This verb acts as a controller, calling on combat_system and loot_system
    to perform game logic, and updating core.game_state.
    """
    
    def execute(self):
        if not self.args:
            self.player.send_message("Attack what?")
            return

        target_name = " ".join(self.args).lower()
        
        # 1. Find the target in the room
        # We must find the *actual object data* from the room
        target_monster_data = next((obj for obj in self.room.objects 
                                    if obj['name'].lower() == target_name and obj.get("is_monster")), None)

        if not target_monster_data:
            self.player.send_message(f"You don't see a **{target_name}** here to attack.")
            return

        monster_id = target_monster_data.get("monster_id")
        if not monster_id:
            self.player.send_message("That creature cannot be attacked.")
            return

        # 2. Check if monster is already dead (from central state)
        if monster_id in DEFEATED_MONSTERS:
            self.player.send_message(f"The {target_monster_data['name']} is already dead.")
            return

        # 3. Get monster's current HP from our new game_state
        if monster_id not in RUNTIME_MONSTER_HP:
            RUNTIME_MONSTER_HP[monster_id] = target_monster_data.get("max_hp", 1)
            
        current_hp = RUNTIME_MONSTER_HP[monster_id]
        
        # ---
        # 4. PLAYER ATTACKS MONSTER
        # ---
        attack_results = combat_system.resolve_attack(
            attacker=self.player,
            defender=target_monster_data,
            game_items_global=GAME_ITEMS
        )
        
        # Send messages from the attack
        self.player.send_message(attack_results['attacker_msg'])
        self.player.send_message(attack_results['roll_string'])
        # We would also send broadcast_msg to the room here

        if attack_results['hit']:
            # 5. Process damage and check for defeat
            new_hp = current_hp - attack_results['damage']
            
            if new_hp <= 0:
                # --- MONSTER IS DEFEATED ---
                self.player.send_message(f"You have defeated the {target_monster_data['name']}!")
                
                # Update central state
                RUNTIME_MONSTER_HP[monster_id] = 0
                DEFEATED_MONSTERS[monster_id] = time.time()
                
                # --- Loot Integration ---
                corpse_data = loot_system.create_corpse_object_data(
                    defeated_entity_template=target_monster_data,
                    defeated_entity_runtime_id=monster_id,
                    game_items_data=GAME_ITEMS,
                    game_loot_tables=GAME_LOOT_TABLES,
                    game_equipment_tables_data=GAME_EQUIPMENT_TABLES
                )
                
                # Add corpse to the room's objects list (in-memory)
                self.room.objects.append(corpse_data)
                
                # Remove the live monster from the room's objects list (in-memory)
                self.room.objects = [obj for obj in self.room.objects if obj.get("monster_id") != monster_id]
                
                self.player.send_message(f"The {corpse_data['name']} falls to the ground.")
                return # Stop combat
                
            else:
                # Monster is still alive, update its HP in central state
                RUNTIME_MONSTER_HP[monster_id] = new_hp
                self.player.send_message(f"The {target_monster_data['name']} has {new_hp} HP remaining.")
        
        # ---
        # 6. MONSTER RETALIATES (if not dead)
        # ---
        if self.player.hp <= 0:
             return # Player was already dead?
             
        self.player.send_message(f"The {target_monster_data['name']} attacks you back!")
        
        retaliation_results = combat_system.resolve_attack(
            attacker=target_monster_data,
            defender=self.player,
            game_items_global=GAME_ITEMS
        )
        
        # Send messages to the player
        self.player.send_message(retaliation_results['defender_msg'])
        self.player.send_message(retaliation_results['roll_string'])

        if retaliation_results['hit']:
            # 7. Process damage to player
            self.player.hp -= retaliation_results['damage']
            
            if self.player.hp <= 0:
                # --- PLAYER IS DEFEATED ---
                self.player.hp = 0
                self.player.send_message("You have been defeated!")
                # Handle player death logic
                self.player.current_room_id = "town_square" # Send back to town
                self.player.hp = 1 # Heal 1 HP so they aren't dead on arrival
                # We would also need to show the new room, but we'll skip for now
            else:
                self.player.send_message(f"You have {self.player.hp}/{self.player.max_hp} HP remaining.")