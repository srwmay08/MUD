# mud_backend/verbs/economy.py
import time
import uuid
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core import db
from mud_backend.core.item_utils import find_item_in_inventory, find_item_in_hands

@VerbRegistry.register(["auction"])
class AuctionVerb(BaseVerb):
    def execute(self):
        # Restriction: Must be in same room as Auctioneer for ACTIONS, but LIST is global
        # Check keywords of objects in room
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
            # Global access allowed for listing
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

            auctions = db.get_active_auctions()
            # Simple suffix match for ID
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
            if len(self.args) < 3:
                self.player.send_message("Usage: AUCTION SELL <item> <start_price>")
                return
            
            try:
                price = int(self.args[-1])
                item_name = " ".join(self.args[1:-1])
            except ValueError:
                self.player.send_message("Price must be a number.")
                return

            # Check Hands FIRST
            item_id_hand, hand_slot = find_item_in_hands(self.player, self.world.game_items, item_name)
            item_id_inv = None
            
            item_source = None
            item_id = None
            
            if item_id_hand:
                item_id = item_id_hand
                item_source = "hand"
            else:
                item_id_inv = find_item_in_inventory(self.player, self.world.game_items, item_name)
                if item_id_inv:
                    item_id = item_id_inv
                    item_source = "inventory"

            if not item_id:
                self.player.send_message(f"You don't have '{item_name}' in your hands or inventory.")
                return

            # Handle item logic (dict vs str ID) and removal
            item_data = None
            
            if isinstance(item_id, dict):
                # Dynamic item
                item_data = item_id
                if item_source == "hand":
                    self.player.worn_items[hand_slot] = None
                else:
                    self.player.inventory.remove(item_id)
            else:
                # Static item ID - hydrate full data for auction storage
                template = self.world.game_items.get(item_id)
                if template:
                    item_data = template.copy()
                    # Ensure it has a unique ID if it didn't before
                    if "uid" not in item_data:
                        item_data["uid"] = uuid.uuid4().hex
                
                # Remove from source
                if item_source == "hand":
                    self.player.worn_items[hand_slot] = None
                else:
                    self.player.inventory.remove(item_id)
            
            if item_data:
                self.world.auction_manager.create_auction(self.player, item_data, price)
                self.player.send_message(f"You listed {item_data['name']} for {price} silver.")
            else:
                self.player.send_message("Error finding item data.")


@VerbRegistry.register(["collect", "interact"])
class CollectVerb(BaseVerb):
    def execute(self):
        # Interaction with Courier
        found_courier = False
        courier_obj = None
        for obj in self.room.objects:
            if obj.get("is_courier") and obj.get("target_player") == self.player.name:
                courier_obj = obj
                found_courier = True
                break
        
        if not found_courier:
            self.player.send_message("There is no courier here for you.")
            return

        # Parse Options (COLLECT BANK, COLLECT LOCKER)
        dest_gold = "wallet"
        dest_items = "inventory"
        
        args_str = " ".join(self.args).lower()
        if "bank" in args_str:
            dest_gold = "bank"
        if "locker" in args_str:
            dest_items = "locker"
            
        self.world.mail_manager.collect_mail(self.player, courier_obj, dest_gold, dest_items)


@VerbRegistry.register(["mail"])
class MailVerb(BaseVerb):
    """
    Handles player-to-player mail sending at a Post Office.
    States: draft_recipient, draft_body, etc. stored in player.temp_data
    """
    def execute(self):
        # Check if in post office (simple string match for prototype)
        if "post office" not in self.room.name.lower():
            self.player.send_message("You must be at a Post Office to send mail.")
            return

        # Initialize temp storage for draft if missing
        if not hasattr(self.player, "temp_data"): self.player.temp_data = {}
        
        if not self.args:
            self.player.send_message("Usage: MAIL SEND <player> <subject>, MAIL CHECK")
            return
            
        sub = self.args[0].lower()
        
        if sub == "check":
            # Check for inbox items in DB
            my_mail = db.get_player_mail(self.player.name)
            # Count undelivered mail
            unread = [m for m in my_mail if not m.get("delivered")]
            
            if not unread:
                self.player.send_message("You have no pending mail.")
            else:
                self.player.send_message(f"You have {len(unread)} pending parcels. A courier should find you soon in town.")
                
        elif sub == "send":
            if len(self.args) < 3:
                self.player.send_message("Usage: MAIL SEND <player_name> <subject>")
                return
            
            recipient = self.args[1]
            subject = " ".join(self.args[2:])
            
            # Verify recipient exists
            target_data = db.fetch_player_data(recipient)
            if not target_data:
                self.player.send_message(f"Player '{recipient}' not found.")
                return
                
            self.player.temp_data["mail_draft"] = {
                "recipient": target_data["name"], 
                "subject": subject,
                "body": "",
                "gold": 0,
                "items": []
            }
            self.player.send_message(f"Draft started for {target_data['name']}. Subject: {subject}")
            self.player.send_message("Use 'MAIL BODY <text>' to write, 'MAIL ATTACH <item>', 'MAIL COIN <amount>', and 'MAIL POST' to send.")

        elif sub == "body":
            if "mail_draft" not in self.player.temp_data:
                self.player.send_message("You have no draft open. Use MAIL SEND <player> <subject> first.")
                return
            body_text = " ".join(self.args[1:])
            self.player.temp_data["mail_draft"]["body"] = body_text
            self.player.send_message("Body text updated.")

        elif sub == "coin":
            if "mail_draft" not in self.player.temp_data:
                self.player.send_message("No draft open.")
                return
            try:
                amt = int(self.args[1])
                if amt > self.player.wealth["silvers"]:
                    self.player.send_message("You don't have that much silver.")
                    return
                self.player.temp_data["mail_draft"]["gold"] = amt
                self.player.send_message(f"Draft will enclose {amt} silver.")
            except:
                self.player.send_message("Invalid amount.")

        elif sub == "attach":
            if "mail_draft" not in self.player.temp_data:
                self.player.send_message("No draft open.")
                return
            item_name = " ".join(self.args[1:])
            
            # Check hands first, then inventory for attachments
            item_id_hand, hand_slot = find_item_in_hands(self.player, self.world.game_items, item_name)
            item_id_inv = None
            item_id = None
            item_source = None

            if item_id_hand:
                item_id = item_id_hand
                item_source = "hand"
            else:
                item_id_inv = find_item_in_inventory(self.player, self.world.game_items, item_name)
                if item_id_inv:
                    item_id = item_id_inv
                    item_source = "inventory"

            if not item_id:
                self.player.send_message("You don't have that.")
                return
            
            # Remove and Attach
            item_data = None
            if isinstance(item_id, dict):
                if "NO_PORTAL" in item_id.get("flags", []):
                     self.player.send_message(f"The {item_id['name']} refuses to leave your person.")
                     return
                item_data = item_id
            else:
                template = self.world.game_items.get(item_id)
                if template:
                    if "NO_PORTAL" in template.get("flags", []):
                         self.player.send_message(f"The {template['name']} refuses to leave your person.")
                         return
                    item_data = template.copy()
                    if "uid" not in item_data: item_data["uid"] = uuid.uuid4().hex

            # Remove from source
            if item_source == "hand":
                self.player.worn_items[hand_slot] = None
            else:
                self.player.inventory.remove(item_id)
            
            if item_data:
                self.player.temp_data["mail_draft"]["items"].append(item_data)
                self.player.send_message(f"Attached {item_data['name']}.")

        elif sub == "post":
            draft = self.player.temp_data.get("mail_draft")
            if not draft:
                self.player.send_message("No draft to post.")
                return
            
            if self.player.wealth["silvers"] < draft["gold"]:
                self.player.send_message(f"You don't have enough silver for the enclosure.")
                return
                
            # Deduct funds (Only the enclosed amount)
            self.player.wealth["silvers"] -= draft["gold"]
            
            # Send via manager
            self.world.mail_manager.send_system_mail(
                recipient_name=draft["recipient"],
                subject=f"From {self.player.name}: {draft['subject']}",
                body=draft["body"],
                gold=draft["gold"],
                items=draft["items"],
                flags=["System_Priority"] # Triggers courier
            )
            
            self.player.send_message("Mail sent successfully!")
            del self.player.temp_data["mail_draft"]

@VerbRegistry.register(["locker"])
class LockerVerb(BaseVerb):
    """
    Handles locker management.
    LOCKER LIST
    LOCKER UPGRADE / BUY
    """
    def execute(self):
        # Must be in locker room
        if "vault" not in self.room.name.lower() and "locker" not in self.room.name.lower():
             self.player.send_message("You must be at the Town Hall Vaults to access your locker.")
             return

        if not self.args:
             self._show_status()
             return
        
        sub = self.args[0].lower()
        
        if sub == "list":
            self._show_status()
        
        elif sub == "upgrade" or sub == "buy":
            cost = 1000
            upgrade_amount = 10
            
            if self.player.wealth["silvers"] < cost:
                self.player.send_message(f"You need {cost} silver to upgrade your locker size.")
                return
            
            self.player.wealth["silvers"] -= cost
            self.player.locker["capacity"] += upgrade_amount
            
            # Save
            db.update_player_locker(self.player.name, self.player.locker)
            
            self.player.send_message(f"You pay {cost} silver to the clerk.")
            self.player.send_message(f"Your locker capacity has been increased to {self.player.locker['capacity']} items.")
        
        else:
            self.player.send_message("Usage: LOCKER LIST, LOCKER BUY (Costs 1000s for +10 slots)")

    def _show_status(self):
        locker = self.player.locker
        items = locker.get("items", [])
        capacity = locker.get("capacity", 50)
        self.player.send_message(f"--- Your Locker ({len(items)}/{capacity}) ---")
        if not items: 
            self.player.send_message("  (Empty)")
        else:
            for item in items:
                self.player.send_message(f"- {item.get('name', 'Unknown item')}")
        self.player.send_message("---")
        self.player.send_message("Type 'LOCKER BUY' to add 10 slots for 1000 silver.")