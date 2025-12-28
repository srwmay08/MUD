import random

class ConsumableSystem:
    """
    A system class to handle the logic of consuming items, specifically herbs,
    potions, and foods defined in items_plants.json.
    """

    @staticmethod
    def consume_item(player, item_data):
        """
        Main entry point for consuming an item.
        
        Args:
            player: The player object (must support wounds/scars dicts and send_message).
            item_data: The dictionary representing the item from items_plants.json.
        """
        # Extract the specific effect block
        effect = item_data.get("effect_on_use")
        
        # If the item has no defined effect, return early
        if not effect:
            verb = item_data.get("use_verb", "use")
            player.send_message(f"You {verb} the {item_data['name']}, but nothing happens.")
            return

        # Determine the action verb for messaging
        verb = item_data.get("use_verb", "consume")

        # 1. Handle HP Healing
        if "heal_hp" in effect:
            amount = effect["heal_hp"]
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
            # Fallback if effect key exists but is empty or unrecognized
            player.send_message(f"You {verb} the {item_data['name']} with no discernible result.")

    @staticmethod
    def _apply_hp_healing(player, amount, item_name, verb):
        """
        Restores HP to the player.
        """
        # Calculate healing
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
    def _apply_wound_healing(player, location, item_rank, item_name, verb):
        """
        Logic for healing fresh wounds.
        """
        # Check if player actually has a wound at this location
        # Matches player.wounds in game_objects.py
        current_wound_rank = player.wounds.get(location, 0)

        if current_wound_rank == 0:
            human_loc = location.replace("_", " ")
            player.send_message(f"You {verb} the {item_name}. It tastes medicinal, but you have no injuries to your {human_loc}.")
            return

        # Check potency: Item Rank must be >= Wound Rank
        if item_rank >= current_wound_rank:
            # Remove the wound entirely
            del player.wounds[location]
            
            # Send flavor text
            msg = ConsumableSystem._get_healing_flavor_text(location, False)
            player.send_message(f"You {verb} the {item_name}. {msg}")
        else:
            human_loc = location.replace("_", " ")
            player.send_message(f"You {verb} the {item_name}. It eases the pain slightly, but is not potent enough to heal the severe wound on your {human_loc}.")

    @staticmethod
    def _apply_scar_healing(player, location, item_rank, item_name, verb):
        """
        Logic for healing old scars.
        """
        # Check if player has a scar at this location
        # Matches player.scars in game_objects.py
        current_scar_rank = player.scars.get(location, 0)

        if current_scar_rank == 0:
            human_loc = location.replace("_", " ")
            player.send_message(f"You {verb} the {item_name}. It tingles, but you have no scar tissue on your {human_loc}.")
            return

        # Check potency: Item Rank must be >= Scar Rank
        if item_rank >= current_scar_rank:
            # Remove the scar entirely
            del player.scars[location]
            
            # Send flavor text
            msg = ConsumableSystem._get_healing_flavor_text(location, True)
            player.send_message(f"You {verb} the {item_name}. {msg}")
        else:
            human_loc = location.replace("_", " ")
            player.send_message(f"You {verb} the {item_name}. Your {human_loc} itches, but the deep scarring remains.")

    @staticmethod
    def _get_healing_flavor_text(location, is_scar):
        """
        Returns immersive text based on body location and whether it is a fresh injury or a scar.
        """
        if is_scar:
            if location == "nervous_system":
                return "Your hands stop shaking as the nerve damage is repaired. You feel steady again."
            elif location == "head_neck":
                return "The tightness in your face relaxes. Old scar tissue softens and fades away completely."
            elif location == "torso_eyes":
                return "You take a deep, clean breath. The restricting internal scarring in your chest dissolves."
            elif location == "arms_legs":
                return "A prickling sensation runs through your limbs. The stiffness in your joints melts away."
            else:
                return "The old wounds fade, leaving your skin unblemished."
        
        else:
            # Fresh Injuries
            if location == "nervous_system":
                return "A soothing numbness washes over you. The violent tremors and pain in your nerves cease."
            elif location == "head_neck":
                return "A loud *pop* echoes in your ears. Your vision clears and the pounding headache vanishes."
            elif location == "torso_eyes":
                return "The sharp pain in your gut subsides. You feel your internal organs knitting back together."
            elif location == "arms_legs":
                return "You hear a wet crunching sound as bones snap back into place and torn muscle rebinds."
            else:
                return "The wound closes rapidly, leaving only faint skin behind."