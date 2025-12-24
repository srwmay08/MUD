# mud_backend/verbs/shop.py
from mud_backend.verbs.base_verb import BaseVerb
import uuid
import copy
from mud_backend.core.registry import VerbRegistry
from mud_backend.core.shop_system import get_or_create_shop_controller, get_shop_flavor
from mud_backend.core.economy import get_item_buy_price, sync_shop_data_to_storage, get_shop_data

def deliver_purchase(verb, item, keeper_name):
    """
    Delivers items to player, prioritizing Hands -> Bag on Counter -> Bag on Floor.
    UPDATES room.data directly to ensure persistence through re-hydration.
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
    bag_name = flavor.get("bag_name", "{player}'s bag").format(player=player.name)
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
    
    # 3. Find Counter (IN PERSISTENT DATA)
    # We must find the stub in room.data to update persistence
    counter_stub = None
    target_name = "the floor"
    
    if "objects" in room.data:
        for obj in room.data["objects"]:
            nm = obj.get("name", "").lower()
            kw = obj.get("keywords", [])
            # Check for counter-like objects
            if "counter" in nm or "counter" in kw:
                counter_stub = obj
                target_name = obj.get("name")
                break
    
    if counter_stub:
        if "container_storage" not in counter_stub:
            counter_stub["container_storage"] = {}
        if "on" not in counter_stub["container_storage"]:
            counter_stub["container_storage"]["on"] = []
            
        counter_stub["container_storage"]["on"].append(bag)
        emote = f"{keeper_name} places {item_name} into a bag and sets it on the {target_name}."
    else:
        # Fallback to floor in persistent data
        if "objects" not in room.data: room.data["objects"] = []
        room.data["objects"].append(bag)
        emote = f"{keeper_name} places {item_name} into a bag and sets it on the floor."

    # Save changes to DB immediately
    verb.world.save_room(room)

    player.send_message(emote)
    
    # Manual Broadcast (Exclude player)
    for sid, p_info in verb.world.get_all_players_info():
        if p_info["current_room_id"] == room.room_id:
            if p_info["player_name"].lower() != player.name.lower():
                verb.world.send_message_to_player(p_info["player_name"], emote, "general")


@VerbRegistry.register(["list"])
class List(BaseVerb):
    def execute(self):
        controller = get_or_create_shop_controller(self.room, self.world)
        
        # Strategy 1: Controller
        if controller:
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
            return

        # Strategy 2: Legacy
        shop_data = get_shop_data(self.room)
        if not shop_data:
            self.player.send_message("You can't seem to shop here.")
            return
        
        inventory = shop_data.get("inventory", [])
        self.player.send_message("--- Items for Sale ---")
        game_items = self.world.game_items
        count = 0
        for item_ref in inventory:
            if count > 15: break
            if isinstance(item_ref, dict): name = item_ref.get("name")
            else: name = game_items.get(item_ref, {}).get("name", "An item")
            
            price = get_item_buy_price(item_ref, game_items, shop_data)
            self.player.send_message(f"- {name:<30} {price} silver")
            count += 1

@VerbRegistry.register(["order"])
class Order(BaseVerb):
    def execute(self):
        if not self.args:
            # FIX: Argument order (world, player, room, args)
            List(self.world, self.player, self.room, self.args).execute()
            return

        controller = get_or_create_shop_controller(self.room, self.world)
        if controller:
            target = self.args[0]
            qty = 1
            item_idx = -1
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
                self.player.send_message("Please order by item number.")
                return

            items, msg = controller.buy_item(item_idx, qty, self.player)
            if not items:
                self.player.send_message(msg)
                return
            self.player.send_message(msg)
            for item in items:
                deliver_purchase(self, item, controller.get_keeper_name())
            return
        
        # Legacy Fallback
        List(self.world, self.player, self.room, self.args).execute()

@VerbRegistry.register(["buy"])
class Buy(BaseVerb):
    def execute(self):
        if not self.args:
            self.player.send_message("What do you want to buy?")
            return

        controller = get_or_create_shop_controller(self.room, self.world)
        arg_str = " ".join(self.args).lower()
        
        # PATH A: Controller
        if controller:
            if self.args[0].isdigit():
                Order(self.world, self.player, self.room, self.args).execute()
                return

            cat_idx = controller.find_item_index_by_keyword(arg_str)
            if cat_idx != -1:
                items, msg = controller.buy_item(cat_idx, 1, self.player)
                if items:
                    self.player.send_message(msg)
                    for item in items:
                        deliver_purchase(self, item, controller.get_keeper_name())
                    return
                if "afford" in msg or "stock" in msg:
                    self.player.send_message(msg)
                    return

        # PATH B: Physical
        item_to_buy = None
        source_container_view = None
        item_index = -1
        game_items = self.world.game_items

        for obj in self.room.objects:
            if obj.get("is_dynamic_display"):
                storage = obj.get("container_storage", {}).get("in", [])
                for i, item_ref in enumerate(storage):
                    if isinstance(item_ref, dict): item_data = item_ref
                    else: item_data = game_items.get(item_ref, {})
                    
                    if item_data:
                        if (arg_str == item_data.get("name", "").lower() or
                                arg_str in item_data.get("keywords", [])):
                            item_to_buy = item_ref
                            item_index = i
                            source_container_view = obj
                            break
                if item_to_buy: break
        
        if not item_to_buy:
            self.player.send_message("That item is not for sale here.")
            return

        dummy_shop_data = {"markdown": 0.5, "markup": 1.2}
        keeper_name = controller.get_keeper_name() if controller else "The Shopkeeper"
        
        price = get_item_buy_price(item_to_buy, game_items, dummy_shop_data)
        if self.player.wealth.get("silvers", 0) < price:
            self.player.send_message("You can't afford that.")
            return

        self.player.wealth["silvers"] -= price
        
        if isinstance(item_to_buy, dict): new_item = item_to_buy
        else:
            new_item = copy.deepcopy(game_items.get(item_to_buy))
            new_item["uid"] = uuid.uuid4().hex
        
        deliver_purchase(self, new_item, keeper_name)

        if source_container_view:
            # We must also update persistence for physical items
            # Find matching stub in room.data
            for stub in self.room.data.get("objects", []):
                if stub.get("uid") == source_container_view.get("uid"):
                    if "container_storage" in stub and "in" in stub["container_storage"]:
                         if len(stub["container_storage"]["in"]) > item_index:
                             stub["container_storage"]["in"].pop(item_index)
                             break
            self.world.save_room(self.room)