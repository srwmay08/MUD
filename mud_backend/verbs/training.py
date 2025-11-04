# mud_backend/verbs/training.py
import time
import random 
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.game_objects import Room
from mud_backend.core.db import fetch_room_data
from mud_backend.core.room_handler import show_room_to_player
from mud_backend import config
# --- THIS IS THE FIX ---
from mud_backend.core import game_state 
# --- END FIX ---
from mud_backend.core.skill_handler import (
    show_skill_list, 
    train_skill,
    _perform_conversion_and_train
)

# --- NEW: Starter Equipment Mappings ---
SKILL_TO_ITEM_MAP = {
    # Armor
    "armor_use": "starter_leather_armor",
    "shield_use": "starter_small_shield",
    # Weapons
    "brawling": "knuckle_dusters",
    "small_edged": "starter_dagger",
    "edged_weapons": "starter_short_sword",
    "two_handed_edged": "starter_bastard_sword",
    "small_blunt": "starter_club",
    "blunt_weapons": "starter_mace",
    "two_handed_blunt": "starter_greatclub",
    "polearms": "starter_spear",
    "bows": "starter_bow",
    "crossbows": "starter_crossbow",
    "small_thrown": "starter_throwing_knife",
    "large_thrown": "starter_javelin",
    "slings": "starter_sling",
    "staves": "starter_staff"
}

WEAPON_SKILL_LIST = [
    "brawling", "small_edged", "edged_weapons", "two_handed_edged",
    "small_blunt", "blunt_weapons", "two_handed_blunt", "polearms",
    "bows", "crossbows", "small_thrown", "large_thrown", "slings", "staves"
]
# --- END NEW ---


class CheckIn(BaseVerb):
# ... (class body unchanged) ...
    """
    Handles the 'check in' command at the inn.
    Enters the 'training' game state.
    """
    def execute(self):
        if self.room.room_id != config.CHARGEN_START_ROOM:
            self.player.send_message("You can only check in at the inn.")
            return
        self.player.game_state = "training"
        self.player.send_message("You approach the front desk to review your skills...")
        show_skill_list(self.player, "all")
        
        

class List(BaseVerb):
# ... (class body unchanged) ...
    """
    Handles the 'list' command *while in the training state*.
    """
    def execute(self):
        if self.player.game_state != "training":
            self.player.send_message("You can only do that while you are training.")
            return
        if not self.args:
            category = "categories"
        else:
            category = " ".join(self.args)
        show_skill_list(self.player, category)
        

class Train(BaseVerb):
# ... (class body unchanged) ...
    """
    Handles the 'train' command *while in the training state*.
    Now handles conversion confirmation.
    """
    def execute(self):
        if self.player.game_state != "training":
            self.player.send_message("You can only do that while you are training.")
            return

        pending_training = self.player.db_data.get('_pending_training')
        
        if pending_training:
            action = self.args[0].lower() if self.args else ""
            if action == "confirm":
                self.player.send_message("> TRAIN CONFIRM")
                _perform_conversion_and_train(self.player, pending_training)
            elif action == "cancel":
                self.player.send_message("> TRAIN CANCEL")
                self.player.send_message("Training cancelled.")
                self.player.db_data.pop('_pending_training', None)
                show_skill_list(self.player, "all")
            else:
                self.player.send_message(f"You must confirm or cancel the pending training. (TRAIN CONFIRM/TRAIN CANCEL)")
                self.player.send_message(pending_training['conversion_data']['msg'])
                self.player.send_message("Type '<span class='keyword' data-command='train CONFIRM'>TRAIN CONFIRM</span>' to proceed with the conversion and training.")
                self.player.send_message("Type '<span class='keyword' data-command='train CANCEL'>TRAIN CANCEL</span>' to abort.")
            return

        if not self.args or len(self.args) < 2:
            self.player.send_message("Usage: TRAIN <skill name> <ranks> or TRAIN CONFIRM/CANCEL")
            return
            
        try:
            ranks_to_train = int(self.args[-1])
            skill_name = " ".join(self.args[:-1])
        except ValueError:
            ranks_to_train = 1
            skill_name = " ".join(self.args)
            
        if ranks_to_train <= 0:
            ranks_to_train = 1
            
        train_skill(self.player, skill_name, ranks_to_train)

class Done(BaseVerb):
    """
    Handles the 'done' command *while in the training state*.
    Exits training and returns to the appropriate room.
    """
    def execute(self):
        if self.player.game_state != "training":
            self.player.send_message("You are not currently training.")
            return
            
        # Check if this was the *first* training (at chargen)
        if (self.player.current_room_id == config.CHARGEN_START_ROOM and
            self.player.chargen_step >= 99): # 99 is the "completed" step
            
            # --- NEW: Grant starter items ---
            given_items_msg = []
            
            # 1. Give Armor
            if self.player.skills.get("armor_use", 0) > 0:
                self.player.worn_items["torso"] = "starter_leather_armor"
                given_items_msg.append("a suit of leather armor")
                
            # 2. Give Shield
            if self.player.skills.get("shield_use", 0) > 0:
                self.player.worn_items["offhand"] = "starter_small_shield"
                given_items_msg.append("a small wooden shield")
                
            # 3. Find and give best weapon
            best_weapon_skill = None
            max_rank = 0
            for skill_id in WEAPON_SKILL_LIST:
                rank = self.player.skills.get(skill_id, 0)
                if rank > max_rank:
                    max_rank = rank
                    best_weapon_skill = skill_id
                    
            if best_weapon_skill:
                item_id = SKILL_TO_ITEM_MAP.get(best_weapon_skill)
                if item_id:
                    # Put it in their main hand
                    self.player.worn_items["mainhand"] = item_id
                    item_data = game_state.GAME_ITEMS.get(item_id, {})
                    given_items_msg.append(item_data.get("name", "a weapon"))

            # 4. Give backpack
            self.player.worn_items["back"] = "starter_backpack"
            given_items_msg.append("a starter backpack")
            
            # 5. Give Gold
            gold_amount = random.randint(700, 1000)
            self.player.wealth["silvers"] = self.player.wealth.get("silvers", 0) + gold_amount
            given_items_msg.append(f"{gold_amount} silver coins")
            
            # Send the confirmation message
            self.player.send_message("\nA guild attendant provides you with your starting gear:")
            for item_name in given_items_msg:
                self.player.send_message(f"- {item_name}")
            # --- END NEW ---
            
            # This is the end of chargen!
            self.player.game_state = "playing"
            self.player.current_room_id = config.CHARGEN_COMPLETE_ROOM
            
            self.player.send_message("\nYou have finalized your training.")
            self.player.send_message("You feel the dream fade...")
            self.player.send_message("You open your eyes and find yourself in...")
            
            town_square_data = fetch_room_data(config.CHARGEN_COMPLETE_ROOM)
            new_room = Room(
                room_id=town_square_data.get("room_id"),
                name=town_square_data.get("name"),
                description=town_square_data.get("description"),
                db_data=town_square_data
            )
            show_room_to_player(self.player, new_room)
            
        else:
            # This was a normal training session
            self.player.game_state = "playing"
            self.player.send_message("You check out from the front desk and head back into the inn.")
            show_room_to_player(self.player, self.room)