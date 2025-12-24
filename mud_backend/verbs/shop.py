# mud_backend/verbs/shop.py
from mud_backend.verbs.base_verb import BaseVerb
import uuid
import copy
from mud_backend.core.registry import VerbRegistry
from mud_backend.core.shop_system import get_or_create_shop_controller, get_shop_flavor
from mud_backend.core.economy import get_item_buy_price, sync_shop_data_to_storage

def deliver_purchase(verb, item, keeper_name):
    """
    Delivers items to player, prioritizing Hands -> Bag on Counter -> Bag on Floor.
    """
    player = verb.player
    room = verb.room
    item_name = item.get("name", "item")

    # 1. Try Hands
    if player.worn_items.get("mainhand") is None:
        player.worn_items["mainhand"] = item["uid"]
        verb.world.game_items[item["uid"]] = item
        player.send_message(f"{keeper_name} hands you {item_name}.")
        return

    if player.worn_items.get("offhand") is None:
        player.worn_items["offhand"] = item["uid"]
        verb.world.game_items[item["uid"]] = item
        player.send_message(f"{keeper_name} hands you {item_name}.")
        return

    # 2. Prepare Bag
    flavor = get_shop_flavor(keeper_name)
    bag_name = f"{player.name}'s shopping bag"
    bag_uid = uuid.uuid4().hex
    
    verb.world.game_items[item["uid"]] = item
    
    bag = {
        "uid": bag_uid,
        "name": bag_name,
        "description": f"A shopping bag belonging to {player.name}.",
        "keywords": ["bag", "sack"],
        "item_type": "container",
        "is_container": True,
        "container_storage": {
            "in": [item]
        },
        "capacity": 50,
        "weight": 0.5
    }
    
    # 3. Find Counter
    counter = None
    for obj in room.objects:
        if "counter" in obj.get("keywords", []) or "counter" in obj.get("name", "").lower():
            counter = obj
            break
            
    if counter:
        if "container_storage" not in counter:
            counter["container_storage"] = {}
        if "on" not in counter["container_storage"]:
            counter["container_storage"]["on"] = []
            
        counter["container_storage"]["on"].append(bag)
        location_name = counter.get("name")
        emote = f"{keeper_name} places {item_name} into a bag and sets it on the {location_name}."
    else:
        room.objects.append(bag)
        emote = f"{keeper_name} places {item_name} into a bag and sets it on the floor (No counter found)."

    player.send_message(emote)
    verb.world.broadcast_to_room(room, emote, exclude=[player])
    verb.world.save_room(room)

@VerbRegistry.register(["list"])
class List(BaseVerb):
    def execute(self):
        controller = get_or_create_shop_controller(self.room, self.world)
        if not controller:
            self.player.send_message("There is no shop here.")
            return

        inventory = controller.get_inventory()
        if not inventory:
            self.player.send_message("The shelves are bare.")
            return

        self.player.send_message(f"--- {controller.get_keeper_name()}'s Stock ---")
        for i, item in enumerate(inventory):
            name = item["name"]
            price = item["base_value"]
            qty = item["qty"]
            self.player.send_message(f"{i+1}. {name:<30} {price}s  (Qty: {qty})")
        
        self.player.send_message("\nType 'ORDER <#>' to buy.")

@VerbRegistry.register(["order"])
class Order(BaseVerb):
    """
    Handles ordering purely from the Catalog (Controller).
    """
    def execute(self):
        controller = get_or_create_shop_controller(self.room, self.world)
        if not controller:
            self.player.send_message("You cannot order here.")
            return

        if not self.args:
            List(self.player, self.room, self.world, self.args).execute()
            return

        target = self.args[0]
        qty = 1
        item_idx = -1

        # Handle "ORDER 1" or "ORDER 5 OF 1"
        if "of" in self.args:
            try:
                of_index = self.args.index("of")
                qty = int(self.args[of_index - 1])
                target = self.args[of_index + 1]
            except:
                self.player.send_message("Usage: ORDER <qty> OF <#>")
                return

        if target.isdigit():
            item_idx = int(target) - 1
        else:
            self.player.send_message("Please order by item number (use LIST to see numbers).")
            return

        items, msg = controller.buy_item(item_idx, qty, self.player)
        
        if not items:
            self.player.send_message(msg)
            return
            
        self.player.send_message(msg)
        for item in items:
            deliver_purchase(self, item, controller.get_keeper_name())

@VerbRegistry.register(["buy"])
class Buy(BaseVerb):
    """
    Handles buying from BOTH the Catalog (Controller) and Physical Displays (Pawnshop).
    """
    def execute(self):
        if not self.args:
            self.player.send_message("What do you want to buy?")
            return

        # Prepare context
        controller = get_or_create_shop_controller(self.room, self.world)
        arg_str = " ".join(self.args).lower()
        
        # --- PATH A: Controller/Catalog Buy ---
        if controller:
            # 1. Check if user typed a Number (Alias to Order)
            if self.args[0].isdigit() and len(self.args) == 1:
                Order(self.player, self.room, self.world, self.args).execute()
                return

            # 2. Check if user typed a Name that exists in Catalog
            cat_idx = controller.find_item_index_by_keyword(arg_str)
            if cat_idx != -1:
                items, msg = controller.buy_item(cat_idx, 1, self.player)
                if items:
                    self.player.send_message(msg)
                    for item in items:
                        deliver_purchase(self, item, controller.get_keeper_name())
                    return
                # If found but failed (e.g. no money), we stop here.
                # Only fall through if NOT found in catalog.
                if "afford" in msg or "stock" in msg:
                    self.player.send_message(msg)
                    return

        # --- PATH B: Physical/Pawnshop Buy (Dynamic Displays) ---
        # If we are here, the item wasn't found in the Controller Catalog.
        # We search physical tables/racks in the room.
        
        item_to_buy = None
        source_container_view = None
        item_index = -1
        game_items = self.world.game_items

        for obj in self.room.objects:
            if obj.get("is_dynamic_display"):
                storage = obj.get("container_storage", {}).get("in", [])
                for i, item_ref in enumerate(storage):
                    if isinstance(item_ref, dict):
                        item_data = item_ref
                    else:
                        item_data = game_items.get(item_ref, {})
                    
                    if item_data:
                        if (arg_str == item_data.get("name", "").lower() or
                                arg_str in item_data.get("keywords", [])):
                            item_to_buy = item_ref
                            item_index = i
                            source_container_view = obj
                            break
                if item_to_buy:
                    break
        
        if not item_to_buy:
            self.player.send_message("That item is not for sale here.")
            return

        # Calculate Price (Legacy/Physical Logic)
        # Use default shop_data dict if no controller exists
        dummy_shop_data = {"markdown": 0.5, "markup": 1.2}
        if controller:
            keeper_name = controller.get_keeper_name()
        else:
            # Try to find a generic NPC to attribute the sale to
            keeper_name = "The Shopkeeper"
            for obj in self.room.objects:
                if obj.get("is_npc") and obj.get("shop_data"):
                    dummy_shop_data = obj["shop_data"]
                    keeper_name = obj.get("name")
                    break

        price = get_item_buy_price(item_to_buy, game_items, dummy_shop_data)
        
        # Transact
        player_silver = self.player.wealth.get("silvers", 0)
        if player_silver < price:
            self.player.send_message(f"You can't afford that. It costs {price} silver and you have {player_silver}.")
            return

        self.player.wealth["silvers"] = player_silver - price

        # Give Item
        if isinstance(item_to_buy, dict):
            # It's a unique physical item, pass it directly
            new_item = item_to_buy
            deliver_purchase(self, new_item, keeper_name)
        else:
            # It's a reference ID (unlikely for dynamic displays but possible)
            new_item = copy.deepcopy(game_items.get(item_to_buy))
            new_item["uid"] = uuid.uuid4().hex
            deliver_purchase(self, new_item, keeper_name)

        # Remove from Physical Source (The Table)
        if source_container_view:
            source_container_view["container_storage"]["in"].pop(item_index)
            # Sync to world data to ensure persistence
            self.world.save_room(self.room)