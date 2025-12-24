import json
import os
from django.conf import settings
from typeclasses.objects import Object
from evennia import create_object
from evennia.utils import utils

# Path to your configuration file
# Assuming your game directory structure places 'data' at the root or configured path
RESTOCK_CONFIG_PATH = os.path.join(settings.GAME_DIR, "data", "economy", "restock_pools.json")


class ShopCounter(Object):
    """
    A generic shop counter.
    It acts as a surface container where shopkeepers place orders.
    """

    def at_object_creation(self):
        """
        Called when the object is first created.
        """
        self.key = "counter"
        self.aliases = ["shop counter", "surface"]
        self.db.desc = "A sturdy counter used for trading."
        
        # Lock it down so it cannot be picked up
        self.locks.add("get:false()")
        
        # Configure as a container (surface)
        # This assumes your game supports a 'surface' container type in 'return_appearance'
        self.db.container_type = "surface"
        self.db.capacity = 50 
        
        # Ensure it is visible
        self.locks.add("view:all()")

    def return_appearance(self, looker, **kwargs):
        """
        Customizes the look description to show items 'on' it.
        """
        desc = super().return_appearance(looker, **kwargs)
        
        contents = self.contents
        if contents:
            desc += "\n\nOn the counter, you see:"
            for item in contents:
                desc += f"\n  {item.get_display_name(looker)}"
        else:
            desc += "\n\nThe counter is currently empty."
            
        return desc


class ShopBag(Object):
    """
    A generic temporary container for items when hands are full.
    Strictly holds 1 item.
    """

    def at_object_creation(self):
        """
        Called when the object is first created.
        """
        self.key = "bag"
        self.db.desc = "A container for your order."
        
        # Configure as a container
        self.db.container_type = "bag"
        self.db.capacity = 1 
        
        # Standard locks
        self.locks.add("get:true()")

    def configure_bag(self, name_template, desc_template, player_name):
        """
        Customizes the bag based on store configuration.
        
        Args:
            name_template (str): e.g., "{player}'s order bag"
            desc_template (str): e.g., "A greasy paper bag labeled '{player}'."
            player_name (str): The name of the customer.
        """
        try:
            self.key = name_template.format(player=player_name)
            self.db.desc = desc_template.format(player=player_name)
        except (KeyError, ValueError):
            # Fallback if formatting fails
            self.key = f"{player_name}'s bag"
            self.db.desc = "A bag containing a purchase."


def _load_store_config(store_key):
    """
    Internal helper to load specific store configuration from JSON.
    """
    if not os.path.exists(RESTOCK_CONFIG_PATH):
        # Return default fallback if file is missing
        return _get_default_config()

    try:
        with open(RESTOCK_CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Look for the specific store configuration
        store_config = data.get(store_key)
        
        if not store_config:
            return _get_default_config()
            
        return store_config

    except (json.JSONDecodeError, OSError):
        return _get_default_config()


def _get_default_config():
    """
    Returns a generic fallback configuration if specific store data is missing.
    """
    return {
        "bag_name": "{player}'s order bag",
        "bag_desc": "A simple bag with '{player}' written on it.",
        "bagging_emote": "{npc} puts the {item} into a bag and sets it on the counter.",
        "counter_key": "counter"
    }


def fulfill_shop_order(npc, player, item_prototype, cost, store_key=None):
    """
    Handles the purchase logic with data-driven ambient flair.
    
    Args:
        npc (Object): The shopkeeper.
        player (Object): The purchasing character.
        item_prototype (str or dict): The prototype key to spawn.
        cost (int): The cost in silver.
        store_key (str, optional): The key used to look up config in restock_pools.json.
                                   Defaults to npc.key.lower() if not provided.
    """
    
    # 1. Determine Store Config Key
    if not store_key:
        store_key = npc.key.lower().replace(" ", "_")

    config = _load_store_config(store_key)

    # 2. Transaction Logic
    current_money = player.db.money or 0
    if current_money < cost:
        npc.msg(f"You cannot afford that. It costs {cost} silver.")
        return

    # Deduct money
    player.db.money = current_money - cost
    
    # 3. Spawn the Item
    # Spawn in None location first to prepare it
    new_item = create_object(
        item_prototype,
        key=item_prototype, # Assuming prototype key serves as name here
        location=None
    )

    # 4. Check Player's Hands
    # Logic: If both left and right hand slots are occupied, hands are full.
    left_hand = player.db.left_hand
    right_hand = player.db.right_hand
    
    hands_full = False
    if left_hand and right_hand:
        hands_full = True

    # 5. Handle Transfer
    if not hands_full:
        # --- SCENARIO A: HANDS FREE ---
        new_item.location = player
        
        # Auto-equip logic
        if not right_hand:
            player.db.right_hand = new_item
        elif not left_hand:
            player.db.left_hand = new_item
            
        # Generic transfer message
        npc.location.msg_contents(
            f"{npc.key} takes {cost} silver and hands {new_item.key} to {player.key}.",
            exclude=[player]
        )
        player.msg(f"{npc.key} takes your {cost} silver and hands you the {new_item.key}.")
        
    else:
        # --- SCENARIO B: HANDS FULL (BAGGING) ---
        
        # Immediate Transaction Feedback
        npc.location.msg_contents(
            f"{npc.key} takes {cost} silver from {player.key}."
        )
        
        # Dialogue
        npc.msg(f"I see your hands are full, {player.key}. Let me bag that up for you.")
        
        # Find the counter based on config
        target_counter_key = config.get("counter_key", "counter")
        counter = npc.location.search(target_counter_key)
        
        if not counter:
            # Fallback: Use the room itself if specific counter is missing
            counter = npc.location

        # Create the Bag
        bag = create_object(
            typeclass=ShopBag,
            key="bag",
            location=None
        )
        
        # Configure Bag Visuals from JSON
        bag.configure_bag(
            name_template=config.get("bag_name", "{player}'s bag"),
            desc_template=config.get("bag_desc", "A bag for {player}."),
            player_name=player.key
        )
        
        # Put item in bag
        new_item.location = bag
        
        # Create Ambient Emote
        # We use python's .format() to inject variables into the JSON string
        emote_template = config.get("bagging_emote", "{npc} bags the item.")
        
        emote_message = emote_template.format(
            npc=npc.key,
            player=player.key,
            item=new_item.key,
            bag=bag.key
        )
        
        # Send Emote
        npc.location.msg_contents(f"\n{emote_message}")
        
        # Place bag on the counter finally
        bag.location = counter