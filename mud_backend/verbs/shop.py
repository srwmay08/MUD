# mud_backend/verbs/shop.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core.shop_system import get_or_create_shop_controller
from mud_backend.core.economy import get_item_buy_price, get_shop_data
import copy
import uuid

@VerbRegistry.register(["list"])
class List(BaseVerb):
    def execute(self):
        controller = get_or_create_shop_controller(self.room, self.world)
        
        # PATH A: Modern Shop Controller
        if controller:
            lines = controller.get_formatted_inventory()
            for line in lines:
                self.player.send_message(line)
            return

        # PATH B: Legacy Fallback (Preserving for older rooms)
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
        # Redirect arguments if user typed 'buy 1' into order
        if not self.args:
            List(self.world, self.player, self.room, self.args).execute()
            return

        controller = get_or_create_shop_controller(self.room, self.world)
        if not controller:
            # Fallback for legacy
            List(self.world, self.player, self.room, self.args).execute()
            return

        target = self.args[0]
        qty = 1
        item_idx = -1
        
        # Handle "order 5 of 1" syntax
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
            self.player.send_message("Please order by item number from the list.")
            return

        items, msg = controller.buy_item(item_idx, qty, self.player)
        self.player.send_message(msg)
        
        if items:
            for item in items:
                controller.deliver_item_to_player(self.player, item)

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
            # Support "buy 1" as "order 1"
            if self.args[0].isdigit():
                Order(self.world, self.player, self.room, self.args).execute()
                return

            cat_idx = controller.find_item_index_by_keyword(arg_str)
            if cat_idx != -1:
                items, msg = controller.buy_item(cat_idx, 1, self.player)
                self.player.send_message(msg)
                if items:
                    for item in items:
                        controller.deliver_item_to_player(self.player, item)
                return
                
            # If not in catalog, fall through to check physical room (display cases)

        # PATH B: Physical / Legacy Room objects
        item_to_buy = None
        source_container_view = None
        item_index = -1
        game_items = self.world.game_items

        # Scan room objects (including display cases)
        for obj in self.room.objects:
            if obj.get("is_dynamic_display") or obj.get("is_container"):
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

        # Determine Price
        dummy_shop_data = {"markdown": 0.5, "markup": 1.2}
        price = get_item_buy_price(item_to_buy, game_items, dummy_shop_data)
        
        if self.player.wealth.get("silvers", 0) < price:
            self.player.send_message("You can't afford that.")
            return

        # Transact
        self.player.wealth["silvers"] -= price
        
        if isinstance(item_to_buy, dict): new_item = item_to_buy
        else:
            new_item = copy.deepcopy(game_items.get(item_to_buy))
            new_item["uid"] = uuid.uuid4().hex
        
        # Delivery
        if controller:
            controller.deliver_item_to_player(self.player, new_item)
        else:
            # Minimal fallback if no controller exists
            self.player.worn_items["mainhand"] = new_item["uid"]
            self.world.game_items[new_item["uid"]] = new_item
            self.player.send_message(f"You buy {new_item.get('name')} for {price}s.")

        # Update Persistence (Remove from Physical Container)
        if source_container_view:
            for stub in self.room.data.get("objects", []):
                if stub.get("uid") == source_container_view.get("uid"):
                    if "container_storage" in stub and "in" in stub["container_storage"]:
                         if len(stub["container_storage"]["in"]) > item_index:
                             stub["container_storage"]["in"].pop(item_index)
                             break
            self.world.save_room(self.room)