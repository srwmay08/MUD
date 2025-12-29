# mud_backend/verbs/consumables.py
import random
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core.item_utils import find_item_in_hands, get_item_data, find_item_in_inventory

class ConsumableSystem:
    """
    A system class to handle the logic of consuming items, specifically herbs,
    potions, and foods defined in items_plants.json.
    """

    # Expanded BODY_GROUPS to catch variations in wound keys (e.g. lefteye vs left_eye)
    BODY_GROUPS = {
        "head_neck": [
            "head", "neck", "face", "skull", "jaw", "throat"
        ],
        "torso_eyes": [
            "chest", "abdomen", "back", "torso", "gut", "stomach", "ribs",
            "right_eye", "left_eye", "righteye", "lefteye", "eye_right", "eye_left", "eyes"
        ],
        "arms_legs": [
            "right_arm", "left_arm", "right_hand", "left_hand", "right_leg", "left_leg",
            "rightarm", "leftarm", "righthand", "lefthand", "rightleg", "leftleg",
            "arm_right", "arm_left", "hand_right", "hand_left", "leg_right", "leg_left",
            "arms", "legs", "hands", "feet"
        ],
        "nervous_system": [
            "nerves", "nervous_system", "spine", "spirit"
        ]
    }

    @staticmethod
    def consume_item(player, item_data):
        """
        Main entry point for consuming an item.
        
        Args:
            player: The player object.
            item_data: The dictionary representing the item from items_plants.json.
        """
        effect = item_data.get("effect_on_use")
        
        if not effect:
            verb = item_data.get("use_verb", "use")
            player.send_message(f"You {verb} the {item_data['name']}, but nothing happens.")
            return

        verb = item_data.get("use_verb", "consume")

        # 1. Handle HP Healing (Supports fixed int or [min, max] list)
        if "heal_hp" in effect:
            val = effect["heal_hp"]
            if isinstance(val, list) and len(val) == 2:
                amount = random.randint(val[0], val[1])
            else:
                amount = int(val)
            
            ConsumableSystem._apply_hp_healing(player, amount, item_data['name'], verb)

        # 2. Handle Wound Healing
        elif "heal_injury" in effect:
            location = effect["heal_injury"]["location"]
            rank = effect["heal_injury"]["rank"]
            ConsumableSystem._apply_wound_healing(player, location, rank, item_data['name'], verb)

        # 3. Handle Scar Healing
        elif "heal_scar" in effect:
            location = effect["heal_scar"]["location"]
            rank = effect["heal_scar"]["rank"]
            ConsumableSystem._apply_scar_healing(player, location, rank, item_data['name'], verb)
            
        else:
            player.send_message(f"You {verb} the {item_data['name']} with no discernible result.")

    @staticmethod
    def _apply_hp_healing(player, amount, item_name, verb):
        current = player.hp
        maximum = player.max_hp
        
        if current >= maximum:
            player.send_message(f"You {verb} the {item_name}, but you are already at full health.")
            return

        new_hp = current + amount
        if new_hp > maximum:
            new_hp = maximum
            
        healed_amount = new_hp - current
        player.hp = new_hp
        
        player.send_message(f"You {verb} the {item_name}. A wave of warmth spreads through you, restoring {healed_amount} health.")

    @staticmethod
    def _apply_wound_healing(player, target_location, item_rank, item_name, verb):
        """
        Logic for healing fresh wounds with group support.
        """
        # Determine actual body parts to check
        possible_parts = ConsumableSystem.BODY_GROUPS.get(target_location, [target_location])
        
        best_candidate = None
        highest_rank_found = 0

        # Find the most severe wound in the target group
        for part in possible_parts:
            w_rank = player.wounds.get(part, 0)
            if w_rank > 0:
                # Prioritize the highest rank wound we can find
                if w_rank > highest_rank_found:
                    highest_rank_found = w_rank
                    best_candidate = part
        
        if not best_candidate:
            human_loc = target_location.replace("_", " ")
            player.send_message(f"You {verb} the {item_name}. It tastes medicinal, but you have no injuries to your {human_loc}.")
            return

        # Check potency: Item Rank must be >= Wound Rank
        if item_rank >= highest_rank_found:
            del player.wounds[best_candidate]
            if best_candidate in player.bandages:
                del player.bandages[best_candidate]
            
            player.mark_dirty()
            msg = ConsumableSystem._get_healing_flavor_text(best_candidate, False)
            player.send_message(f"You {verb} the {item_name}. {msg}")
        else:
            human_loc = best_candidate.replace("_", " ")
            player.send_message(f"You {verb} the {item_name}. It eases the pain slightly, but is not potent enough to heal the severe wound on your {human_loc}.")

    @staticmethod
    def _apply_scar_healing(player, target_location, item_rank, item_name, verb):
        """
        Logic for healing old scars with group support.
        """
        possible_parts = ConsumableSystem.BODY_GROUPS.get(target_location, [target_location])
        
        best_candidate = None
        highest_rank_found = 0

        for part in possible_parts:
            s_rank = player.scars.get(part, 0)
            if s_rank > 0:
                if s_rank > highest_rank_found:
                    highest_rank_found = s_rank
                    best_candidate = part

        if not best_candidate:
            human_loc = target_location.replace("_", " ")
            player.send_message(f"You {verb} the {item_name}. It tingles, but you have no scar tissue on your {human_loc}.")
            return

        if item_rank >= highest_rank_found:
            del player.scars[best_candidate]
            player.mark_dirty()
            msg = ConsumableSystem._get_healing_flavor_text(best_candidate, True)
            player.send_message(f"You {verb} the {item_name}. {msg}")
        else:
            human_loc = best_candidate.replace("_", " ")
            player.send_message(f"You {verb} the {item_name}. Your {human_loc} itches, but the deep scarring remains.")

    @staticmethod
    def _get_healing_flavor_text(location, is_scar):
        # Normalize location for text check
        loc_str = location.lower()
        
        if is_scar:
            if any(x in loc_str for x in ["nerve", "spine", "spirit"]):
                return "Your hands stop shaking as the nerve damage is repaired. You feel steady again."
            elif any(x in loc_str for x in ["head", "neck", "face", "jaw"]):
                return "The tightness in your face relaxes. Old scar tissue softens and fades away completely."
            elif any(x in loc_str for x in ["chest", "abdomen", "back", "eye", "gut", "stomach", "torso"]):
                return "You take a deep, clean breath. The restricting internal scarring and tissue damage dissolves."
            elif any(x in loc_str for x in ["arm", "leg", "hand", "foot", "feet"]):
                return "A prickling sensation runs through your limbs. The stiffness in your joints melts away."
            else:
                return "The old wounds fade, leaving your skin unblemished."
        else:
            # Fresh Injuries
            if any(x in loc_str for x in ["nerve", "spine", "spirit"]):
                return "A soothing numbness washes over you. The violent tremors and pain in your nerves cease."
            elif any(x in loc_str for x in ["head", "neck", "face", "jaw"]):
                return "A loud *pop* echoes in your ears. Your vision clears and the pounding headache vanishes."
            elif any(x in loc_str for x in ["chest", "abdomen", "back", "eye", "gut", "stomach", "torso"]):
                return "The sharp pain in your gut subsides. You feel your internal organs and tissues knitting back together."
            elif any(x in loc_str for x in ["arm", "leg", "hand", "foot", "feet"]):
                return "You hear a wet crunching sound as bones snap back into place and torn muscle rebinds."
            else:
                return "The wound closes rapidly, leaving only faint skin behind."

@VerbRegistry.register(["eat", "consume"])
class Eat(BaseVerb):
    def execute(self):
        if not self.args:
            self.player.send_message("Eat what?")
            return

        target_name = " ".join(self.args)
        item_ref = None
        hand_slot = None
        
        # ID MATCHING
        if target_name.startswith("#"):
            target_uid = target_name[1:]
            
            # Check Hands
            for slot in ["mainhand", "offhand"]:
                item = self.player.worn_items.get(slot)
                if item:
                    i_uid = item.get("uid") if isinstance(item, dict) else item
                    if str(i_uid) == target_uid:
                        item_ref = item
                        hand_slot = slot
                        break
            
            # Check Inventory
            if not item_ref:
                for item in self.player.inventory:
                    i_uid = item.get("uid") if isinstance(item, dict) else item
                    if str(i_uid) == target_uid:
                        item_ref = item
                        hand_slot = "inventory"
                        break
        
        # NAME MATCHING (Fallback)
        if not item_ref:
            # 1. Try to find item in hands first
            item_ref, hand_slot = find_item_in_hands(self.player, self.world.game_items, target_name)
            
            # 2. If not in hands, try inventory
            if not item_ref:
                item_ref = find_item_in_inventory(self.player, self.world.game_items, target_name)
                hand_slot = "inventory"

        if not item_ref:
            self.player.send_message(f"You don't have '{target_name}'.")
            return

        item_data = get_item_data(item_ref, self.world.game_items)
        if not item_data:
            self.player.send_message("That item seems to be glitched.")
            return

        if item_data.get("item_type") not in ["herb", "food", "potion"]:
            if not item_data.get("effect_on_use"):
                self.player.send_message(f"You cannot eat {item_data['name']}.")
                return

        ConsumableSystem.consume_item(self.player, item_data)

        if hand_slot == "inventory":
            self.player.inventory.remove(item_ref)
        else:
            self.player.worn_items[hand_slot] = None
        
        self.player.mark_dirty()

@VerbRegistry.register(["drink", "quaff", "sip"])
class Drink(BaseVerb):
    def execute(self):
        if not self.args:
            self.player.send_message("Drink what?")
            return

        target_name = " ".join(self.args)
        item_ref = None
        hand_slot = None

        # ID MATCHING
        if target_name.startswith("#"):
            target_uid = target_name[1:]
            for slot in ["mainhand", "offhand"]:
                item = self.player.worn_items.get(slot)
                if item:
                    i_uid = item.get("uid") if isinstance(item, dict) else item
                    if str(i_uid) == target_uid:
                        item_ref = item
                        hand_slot = slot
                        break
        
        # NAME MATCHING (Fallback)
        if not item_ref:
            item_ref, hand_slot = find_item_in_hands(self.player, self.world.game_items, target_name)
        
        if not item_ref:
            self.player.send_message("You must be holding the potion to drink it.")
            return

        item_data = get_item_data(item_ref, self.world.game_items)
        if not item_data: return

        if item_data.get("item_type") not in ["potion", "drink", "herb"]:
             if not item_data.get("effect_on_use"):
                self.player.send_message(f"You cannot drink {item_data['name']}.")
                return

        ConsumableSystem.consume_item(self.player, item_data)
        self.player.worn_items[hand_slot] = None
        self.player.mark_dirty()