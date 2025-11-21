# mud_backend/verbs/training.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.skill_handler import (
    show_skill_list, 
    train_skill, 
    _perform_conversion_and_train
)
from mud_backend import config
import re

# --- NEW: Map of skill_ids to their corresponding starter item_ids ---
# (Item IDs are from data/items.json)
SKILL_TO_WEAPON_MAP = {
    "brawling": "knuckle_dusters",
    "small_edged": "starter_dagger",
    "edged_weapons": "starter_short_sword",
    "two_handed_edged": "starter_bastard_sword",
    "small_blunt": "starter_club",
    "blunt_weapons": "starter_mace",
    "two_handed_blunt": "starter_greatclub",
    "polearms": "starter_spear",
    "staves": "starter_staff",
    "bows": "starter_bow",
    "crossbows": "starter_crossbow",
    "slings": "starter_sling",
    "small_thrown": "starter_throwing_knife",
    "large_thrown": "starter_javelin"
}
# --- END NEW ---

@VerbRegistry.register(["check", "checkin"]) 
@VerbRegistry.register(["train"]) 
@VerbRegistry.register(["done"]) 
@VerbRegistry.register(["train_list"])

class CheckIn(BaseVerb):
    """
    Handles the 'checkin' command.
    Allows a player to enter the training state.
    """
    def execute(self):
        if self.room.room_id not in ["inn_front_desk"]:
            self.player.send_message("You must be at the inn to check in for training.")
            return

        self.player.send_message("You check in at the inn, ready to train.")
        self.player.game_state = "training"
        
        # Show the full skill list by default
        show_skill_list(self.player, "all")

class List(BaseVerb):
    """
    Handles the 'list' command *during training*.
    """
    def execute(self):
        category = " ".join(self.args).lower()
        if not category:
            category = "all"
        
        show_skill_list(self.player, category)

class Train(BaseVerb):
    """
    Handles the 'train' command *during training*.
    """
    def execute(self):
        if not self.args:
            self.player.send_message("Usage: TRAIN <skill name> <ranks> (e.g., TRAIN ARMOR USE 1)")
            return

        args_str = " ".join(self.args).lower()

        # 1. Handle CONFIRM/CANCEL
        pending_training = self.player.db_data.get('_pending_training')
        
        if args_str == "confirm":
            if not pending_training:
                self.player.send_message("You have no pending training to confirm.")
                return
            
            _perform_conversion_and_train(self.player, pending_training)
            return
            
        elif args_str == "cancel":
            if not pending_training:
                self.player.send_message("You have no pending training to cancel.")
                return
            
            self.player.db_data.pop('_pending_training', None)
            self.player.send_message("Pending training canceled.")
            return
        
        # 2. Handle a new training request
        if pending_training:
            self.player.send_message("You have pending training. Please 'TRAIN CONFIRM' or 'TRAIN CANCEL' first.")
            return

        # 3. Parse the command (e.g., "train armor use 1")
        ranks_to_train = 1
        skill_name = args_str
        
        # Find if the last argument is a number
        match = re.search(r'(\d+)$', args_str)
        if match:
            try:
                ranks_to_train = int(match.group(1))
                # Get the skill name, which is everything *before* the number
                skill_name = args_str[:match.start()].strip()
            except ValueError:
                ranks_to_train = 1 # Not a valid number, assume 1
                skill_name = args_str
        
        if not skill_name:
            self.player.send_message("Usage: TRAIN <skill name> <ranks> (e.g., TRAIN ARMOR USE 1)")
            return

        # 4. Call the skill_handler function
        train_skill(self.player, skill_name, ranks_to_train)

class Done(BaseVerb):
    """
    Handles the 'done' command *during training*.
    Moves the player out of chargen/training and into the game.
    """
    def execute(self):
        self.player.send_message("You finish your training and head out into the world.")
        self.player.game_state = "playing"
        
        # ---
        # --- THIS IS THE FIX: Set all vitals to max
        # ---
        self.player.hp = self.player.max_hp
        self.player.mana = self.player.max_mana
        self.player.stamina = self.player.max_stamina
        self.player.spirit = self.player.max_spirit
        # --- END FIX ---
        
        # --- THIS IS THE UPDATED LOGIC ---
        
        # 1. Grant standard gear (backpack, armor, silver)
        if not self.player.worn_items.get("back"):
            self.player.worn_items["back"] = "starter_backpack"
            
        if not self.player.worn_items.get("torso"):
            self.player.worn_items["torso"] = "starter_leather_armor"

        if self.player.wealth.get("silvers", 0) == 0:
            self.player.wealth["silvers"] = 500 # Grant 500 silver
            
        # 2. Grant best weapon based on trained skills
        # ---
        # --- MODIFICATION: Put weapon in inventory, not hand
        # ---
        if not self.player.worn_items.get("mainhand") and not any(self.world.game_items.get(item_id, {}).get("item_type") == "weapon" for item_id in self.player.inventory):
            best_skill_id = None
            max_rank = 0
            
            # Find the highest-ranked weapon skill the player trained
            for skill_id, rank in self.player.skills.items():
                if skill_id in SKILL_TO_WEAPON_MAP and rank > max_rank:
                    max_rank = rank
                    best_skill_id = skill_id
            
            # Grant the corresponding weapon
            if best_skill_id:
                weapon_to_grant = SKILL_TO_WEAPON_MAP[best_skill_id]
                self.player.inventory.append(weapon_to_grant)
            else:
                # Default to a dagger if no weapon skills were trained
                self.player.inventory.append("starter_dagger")
        # ---
        # --- END MODIFICATION
        # ---
        
        self.player.send_message("You are given some starting gear to help you on your way.")
        # --- END UPDATED LOGIC ---
        
        # ---
        # --- THIS IS THE FIX (Bug 2: Wrong room)
        # ---
        # Move player back to the inn lobby
        # (This also handles broadcasting their arrival)
        self.player.move_to_room("inn_front_desk", "You finish your training and head back to the common room.")
        # ---
        # --- END FIX
        # ---