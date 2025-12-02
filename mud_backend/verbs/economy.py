# mud_backend/verbs/economy.py
import time
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core import db
from mud_backend.verbs.item_actions import _find_item_in_inventory, _get_item_data

@VerbRegistry.register(["auction"])
class AuctionVerb(BaseVerb):
    def execute(self):
        # Restriction: Must be in same room as Auctioneer
        # (Assuming 'auctioneer' keyword on NPC in room)
        has_auctioneer = False
        for obj in self.room.objects:
            if "auctioneer" in obj.get("keywords", []):
                has_auctioneer = True
                break
        
        if not self.args:
            self.player.send_message("Usage: AUCTION LIST, AUCTION BID <id> <amount>, AUCTION SELL <item> <price>")
            return
            
        sub = self.args[0].lower()
        
        if sub == "list":
            if not has_auctioneer:
                self.player.send_message("You need to find an Auctioneer to see the listings.")
                return

            auctions = db.get_active_auctions()
            if not auctions:
                self.player.send_message("No active auctions.")
                return
            
            self.player.send_message(f"{'ID':<5} {'Item':<25} {'Bid':<10} {'Time Left'}")
            self.player.send_message("-" * 55)
            now = time.time()
            for auc in auctions:
                short_id = auc['uid'][-4:]
                name = auc['item_data'].get('name', 'Unknown')
                price = auc['current_bid'] if auc['current_bid'] > 0 else auc['start_price']
                mins_left = int((auc['end_time'] - now) / 60)
                self.player.send_message(f"{short_id:<5} {name:<25} {price:<10} {mins_left}m")

        elif sub == "bid":
            if not has_auctioneer:
                self.player.send_message("You need to find an Auctioneer to bid.")
                return
            if len(self.args) < 3:
                self.player.send_message("Usage: AUCTION BID <id> <amount>")
                return
            
            target_id_short = self.args[1]
            try:
                amount = int(self.args[2])
            except ValueError:
                self.player.send_message("Invalid amount.")
                return

            # Find full ID
            auctions = db.get_active_auctions()
            full_auc = next((a for a in auctions if a['uid'].endswith(target_id_short)), None)
            
            if not full_auc:
                self.player.send_message("Auction not found.")
                return

            result = self.world.auction_manager.place_bid(self.player, full_auc['uid'], amount)
            self.player.send_message(result)

        elif sub == "sell":
            if not has_auctioneer:
                self.player.send_message("You need to find an Auctioneer to sell items.")
                return
            # Syntax: AUCTION SELL <item> <price>
            # Needs parsing logic to separate item name from price
            if len(self.args) < 3:
                self.player.send_message("Usage: AUCTION SELL <item> <start_price>")
                return
            
            try:
                price = int(self.args[-1])
                item_name = " ".join(self.args[1:-1])
            except ValueError:
                self.player.send_message("Price must be a number.")
                return

            item_id = _find_item_in_inventory(self.player, self.world.game_items, item_name)
            if not item_id:
                self.player.send_message(f"You don't have '{item_name}'.")
                return

            # Remove item (handle dict vs str ID)
            item_data = None
            if isinstance(item_id, dict):
                item_data = item_id
                self.player.inventory.remove(item_id)
            else:
                item_data = self.world.game_items.get(item_id)
                self.player.inventory.remove(item_id)
            
            self.world.auction_manager.create_auction(self.player, item_data, price)
            self.player.send_message("Auction created!")

@VerbRegistry.register(["locker"])
class LockerVerb(BaseVerb):
    def execute(self):
        # Check room flag "LOCKER" or "BANK"
        # For prototype, assume room name contains 'Bank' or 'Town Hall'
        room_name = self.room.name.lower()
        if "bank" not in room_name and "hall" not in room_name:
             self.player.send_message("You must be at the bank or town hall to access your locker.")
             return
             
        if not self.args:
            self.player.send_message("Usage: LOCKER LIST, LOCKER GET <item>, LOCKER PUT <item>")
            return
            
        sub = self.args[0].lower()
        locker = self.player.locker
        
        if sub == "list":
            items = locker.get("items", [])
            capacity = locker.get("capacity", 50)
            self.player.send_message(f"--- Your Locker ({len(items)}/{capacity}) ---")
            for item in items:
                self.player.send_message(f"- {item['name']}")
                
        elif sub == "put":
            target = " ".join(self.args[1:])
            if len(locker["items"]) >= locker["capacity"]:
                self.player.send_message("Your locker is full.")
                return
                
            item_id = _find_item_in_inventory(self.player, self.world.game_items, target)
            if not item_id:
                self.player.send_message("You don't have that.")
                return
                
            # Move to locker
            item_data = _get_item_data(item_id, self.world.game_items)
            locker["items"].append(item_data)
            self.player.inventory.remove(item_id)
            
            db.update_player_locker(self.player.name, locker)
            self.player.send_message(f"You put {item_data['name']} in your locker.")

        elif sub == "get":
            target = " ".join(self.args[1:]).lower()
            found_item = None
            found_idx = -1
            
            for i, item in enumerate(locker["items"]):
                if target in item["name"].lower() or target in item.get("keywords", []):
                    found_item = item
                    found_idx = i
                    break
            
            if not found_item:
                self.player.send_message("You don't see that in your locker.")
                return
            
            # Weight Check
            weight = found_item.get("weight", 1)
            if self.player.current_encumbrance + weight > self.player.max_carry_weight:
                self.player.send_message("That is too heavy for you to carry right now.")
                return
                
            locker["items"].pop(found_idx)
            self.player.inventory.append(found_item) # Add as dynamic object
            db.update_player_locker(self.player.name, locker)
            self.player.send_message(f"You get {found_item['name']} from your locker.")

@VerbRegistry.register(["collect", "interact"])
class CollectVerb(BaseVerb):
    def execute(self):
        # Interaction with Courier
        found_courier = False
        for obj in self.room.objects:
            if obj.get("is_courier") and obj.get("target_player") == self.player.name:
                self.world.mail_manager.collect_mail(self.player, obj)
                found_courier = True
                return
        if not found_courier:
            self.player.send_message("There is no courier here for you.")