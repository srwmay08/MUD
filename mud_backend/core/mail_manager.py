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
        Spawns a courier if Priority mail exists, or moves existing one to follow player.
        """
        priority_mail = db.get_priority_mail(player.name)
        if not priority_mail:
            return

        # 1. Check if courier is already in the current room
        current_room = self.world.get_active_room_safe(player.current_room_id)
        if not current_room: return

        for obj in current_room.objects:
            if obj.get("is_courier") and obj.get("target_player") == player.name:
                # Already here, maybe say something random occasionally
                if random.random() < 0.3:
                    self.world.broadcast_to_room(player.current_room_id, f"The courier tugs at {player.name}'s sleeve. 'Delivery!'", "ambient")
                return 

        # 2. Check if courier exists in ANY active room (Follow logic)
        existing_courier = None
        old_room_id = None
        
        # We need to search all active rooms safely
        # Note: Accessing world.active_rooms keys should be thread safe enough for reading
        # locking directory_lock is better practice
        with self.world.room_directory_lock:
            active_room_ids = list(self.world.active_rooms.keys())

        for rid in active_room_ids:
            r = self.world.get_active_room_safe(rid)
            if not r: continue
            
            # Lock the room to modify objects list
            with r.lock:
                # Find courier in this room
                to_remove = None
                for obj in r.objects:
                    if obj.get("is_courier") and obj.get("target_player") == player.name:
                        existing_courier = obj
                        to_remove = obj
                        break
                
                if to_remove:
                    r.objects.remove(to_remove)
                    # We found him, stop searching
                    break
        
        if existing_courier:
            # Move to new room
            current_room.objects.append(existing_courier)
            self.world.broadcast_to_room(player.current_room_id, f"A swift courier runs in after {player.name}, panting slightly. 'Wait up!'", "ambient_spawn")
        else:
            # Spawn new
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
            "despawn_time": time.time() + 600 # 10 minutes persistence
        }
        
        room.objects.append(courier_obj)
        self.world.broadcast_to_room(room.room_id, f"A swift courier bustles in. '{greeting}'", "ambient_spawn")

    def collect_mail(self, player, courier_obj, dest_gold="wallet", dest_items="inventory"):
        """
        Handles the interaction.
        dest_gold: 'wallet' or 'bank'
        dest_items: 'inventory' or 'locker'
        """
        mail_list = courier_obj.get("mail_data", [])
        if not mail_list: return

        total_gold = 0
        items_to_add = []

        # Aggregate
        for mail in mail_list:
            total_gold += mail.get("gold", 0)
            items_to_add.extend(mail.get("items", []))

        # --- Handle Gold ---
        if total_gold > 0:
            if dest_gold == "bank":
                player.wealth["bank_silvers"] = player.wealth.get("bank_silvers", 0) + total_gold
                player.send_message(f"The courier deposits {total_gold} silver directly into your bank account.")
            else:
                player.wealth["silvers"] += total_gold
                player.send_message(f"The courier hands you a pouch containing {total_gold} silver.")

        # --- Handle Items ---
        if items_to_add:
            if dest_items == "locker":
                # Add to locker
                locker = player.locker
                # Check capacity (Optional, but polite)
                if len(locker["items"]) + len(items_to_add) > locker["capacity"]:
                    player.send_message("Your locker is too full to accept these items! You must take them.")
                    dest_items = "inventory" # Fallback
                else:
                    for item in items_to_add:
                        # Ensure ID
                        if "uid" not in item: item["uid"] = uuid.uuid4().hex
                        locker["items"].append(item)
                    db.update_player_locker(player.name, locker)
                    player.send_message(f"The courier sends {len(items_to_add)} items directly to your locker at Town Hall.")
            
            if dest_items == "inventory":
                # Check weight limit logic could go here, but typically mail forces it or drops to ground.
                # For now, we force add to inventory even if overweight (player just can't move).
                for item_data in items_to_add:
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