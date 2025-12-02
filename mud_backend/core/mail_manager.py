# mud_backend/core/mail_manager.py
import time
import uuid
import random
from mud_backend.core import db

class MailManager:
    def __init__(self, world):
        self.world = world

    def send_system_mail(self, recipient_name, subject, body, gold=0, items=None, flags=None):
        """Used by Auction House to send winnings/earnings."""
        if items is None: items = []
        if flags is None: flags = []
        
        mail = {
            "uid": uuid.uuid4().hex,
            "sender": "System",
            "recipient": recipient_name,
            "timestamp": time.time(),
            "subject": subject,
            "body": body,
            "gold": gold,
            "items": items, # List of Item Dicts (not IDs, actual objects)
            "flags": flags,
            "read": False,
            "delivered": False,
            "deleted": False
        }
        db.send_mail(mail)

    def check_for_courier(self, player):
        """
        Called on Room Enter (if room is SAFE/TOWN).
        Spawns a courier if Priority mail exists.
        """
        priority_mail = db.get_priority_mail(player.name)
        if not priority_mail:
            return

        # Check if courier already exists for this player in this room
        room = self.world.get_active_room_safe(player.current_room_id)
        if room:
            for obj in room.objects:
                if obj.get("is_courier") and obj.get("target_player") == player.name:
                    return # Already here

        self.spawn_courier(player, priority_mail)

    def spawn_courier(self, player, mail_list):
        room = self.world.get_active_room_safe(player.current_room_id)
        if not room: return

        courier_uid = uuid.uuid4().hex
        
        # Calculate total package info
        total_gold = sum(m.get("gold", 0) for m in mail_list)
        item_count = sum(len(m.get("items", [])) for m in mail_list)
        
        # Flavor text based on content
        greeting = f"I have a delivery for {player.name}."
        if total_gold > 0:
            greeting += " Looks like a heavy coin purse!"
        elif item_count > 0:
            greeting += " Careful, it's fragile."

        courier_obj = {
            "uid": courier_uid,
            "name": "a swift courier",
            "description": "A winded courier looking for their recipient.",
            "keywords": ["courier", "messenger"],
            "is_npc": True,
            "is_courier": True,
            "target_player": player.name,
            "mail_data": mail_list, # Bind mail to NPC
            "greeting": greeting,
            "verbs": ["look", "collect", "interact"],
            "despawn_time": time.time() + 300 # 5 minutes
        }
        
        room.objects.append(courier_obj)
        self.world.broadcast_to_room(room.room_id, f"A swift courier bustles in. '{greeting}'", "ambient_spawn")

    def collect_mail(self, player, courier_obj):
        """Handles the interaction."""
        mail_list = courier_obj.get("mail_data", [])
        if not mail_list: return

        total_gold = 0
        items_to_add = []

        # Aggregate
        for mail in mail_list:
            total_gold += mail.get("gold", 0)
            items_to_add.extend(mail.get("items", []))

        # Check Weight Limit
        current_weight = player.current_encumbrance
        added_weight = sum(item.get("weight", 1) for item in items_to_add)
        
        if current_weight + added_weight > player.max_carry_weight:
            player.send_message("The courier tries to hand you the packages, but you are carrying too much!")
            player.send_message("'Make some room,' he says. 'I'll wait.'")
            return

        # Success Transaction
        if total_gold > 0:
            player.wealth["silvers"] += total_gold
            player.send_message(f"The courier hands you a pouch containing {total_gold} silver.")

        for item_data in items_to_add:
            # Generate new UID to prevent collisions
            item_data["uid"] = uuid.uuid4().hex
            player.inventory.append(item_data) 
            player.send_message(f"You receive {item_data['name']}.")

        # Mark Delivered
        for mail in mail_list:
            db.mark_mail_delivered(mail["uid"])

        # Despawn Courier
        room = self.world.get_active_room_safe(player.current_room_id)
        if courier_obj in room.objects:
            room.objects.remove(courier_obj)
            self.world.broadcast_to_room(room.room_id, "The courier tips his cap and dashes off.", "ambient_spawn")