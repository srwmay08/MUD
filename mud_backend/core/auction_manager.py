# mud_backend/core/auction_manager.py
import time
import uuid
import random
from mud_backend.core import db

class AuctionManager:
    def __init__(self, world):
        self.world = world
        self.mail_manager = world.mail_manager 

    def create_auction(self, player, item_data, start_price, buyout_price=None, duration_days=3):
        """Creates listing."""
        auction = {
            "uid": uuid.uuid4().hex,
            "seller": player.name,
            "item_data": item_data, # Store full item dict snapshot
            "start_price": int(start_price),
            "buyout_price": int(buyout_price) if buyout_price else None,
            "current_bid": 0,
            "high_bidder": None,
            "end_time": time.time() + (duration_days * 86400),
            "status": "active"
        }
        db.create_auction(auction)
        return True

    def place_bid(self, bidder, auction_id, bid_amount):
        auction = db.get_auction(auction_id)
        if not auction or auction['status'] != 'active':
            return "Auction not active."

        if bid_amount > bidder.wealth["silvers"]:
            return "Not enough silver."

        min_bid = max(auction['start_price'], auction['current_bid'] + 1)
        if bid_amount < min_bid:
            return f"Bid too low. Minimum is {min_bid}."

        # Escrow Logic
        # 1. Refund previous bidder
        if auction['high_bidder']:
            self.mail_manager.send_system_mail(
                auction['high_bidder'], 
                "Outbid!", 
                f"You were outbid on {auction['item_data']['name']}. Funds returned.",
                gold=auction['current_bid'],
                flags=["System_Priority"]
            )

        # 2. Take money from new bidder
        bidder.wealth["silvers"] -= bid_amount
        
        # 3. Update Auction
        db.update_auction_bid(auction_id, bid_amount, bidder.name)
        
        # 4. Anti-Sniping (Extend if < 60s left)
        # Note: Database update for time extension would go here
        
        # Check Buyout
        if auction['buyout_price'] and bid_amount >= auction['buyout_price']:
            self.resolve_auction(auction)
            return "Buyout accepted! You won the auction."

        return "Bid accepted."

    def tick(self):
        """Called every minute by game loop."""
        active = db.get_active_auctions()
        now = time.time()
        
        for auc in active:
            if now >= auc['end_time']:
                self.resolve_auction(auc)
                
            # Peddler Logic
            if random.random() < 0.05: 
                self.peddle_item(auc)

    def resolve_auction(self, auction):
        """Ends auction, distributes goods."""
        # Refresh state in case it changed mid-tick
        current_auc = db.get_auction(auction['uid'])
        if current_auc['status'] != 'active': return

        db.end_auction(auction['uid'])
        
        if current_auc['high_bidder']:
            # Success
            # Mail item to Winner
            self.mail_manager.send_system_mail(
                current_auc['high_bidder'],
                "Auction Won",
                f"You won the {current_auc['item_data']['name']}!",
                items=[current_auc['item_data']],
                flags=["System_Priority"]
            )
            
            # Mail gold to Seller (minus cut)
            cut = int(current_auc['current_bid'] * 0.10)
            earnings = current_auc['current_bid'] - cut
            self.mail_manager.send_system_mail(
                current_auc['seller'],
                "Auction Sold",
                f"Your {current_auc['item_data']['name']} sold for {current_auc['current_bid']}. House took {cut}.",
                gold=earnings,
                flags=["System_Priority"]
            )
        else:
            # No bids, return item
            self.mail_manager.send_system_mail(
                current_auc['seller'],
                "Auction Expired",
                f"Your {current_auc['item_data']['name']} did not sell.",
                items=[current_auc['item_data']],
                flags=["System_Priority"]
            )

    def peddle_item(self, auction):
        """Finds the Auctioneer NPC room and makes them shout."""
        # For prototype, assume Town Square has the auctioneer
        room_id = "town_square" 
        
        item_name = auction['item_data']['name']
        price = auction['current_bid'] if auction['current_bid'] > 0 else auction['start_price']
        
        msg = f"The Town Crier shouts, 'Auction active for {item_name}! Current price is {price} silvers!'"
        self.world.broadcast_to_room(room_id, msg, "message")