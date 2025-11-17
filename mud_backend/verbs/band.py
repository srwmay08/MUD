# mud_backend/verbs/band.py
import time
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core import db
from mud_backend.verbs.foraging import _set_action_roundtime
from bson.objectid import ObjectId

class Band(BaseVerb):
    """
    Handles 'band' command.
    """
    def execute(self):
        if not self.args:
            self.player.send_message("Usage: BAND <CREATE|INVITE|LIST|REMOVE|KICK|DELETE> or BT <message>.")
            return
            
        database = db.get_db()
        if not database:
            self.player.send_message("The Adventuring Band system is currently unavailable.")
            return
            
        command = self.args[0].lower()
        args = self.args[1:]
        player_name = self.player.name
        
        # --- BAND CREATE ---
        if command == "create":
            if self.player.band_id:
                self.player.send_message("You are already in an adventuring band. You must leave it first.")
                return
            
            try:
                result = database.bands.insert_one({
                    "leader_name": player_name,
                    "members": [player_name],
                    "created_at": time.time()
                })
                band_id = result.inserted_id
                self.player.band_id = str(band_id)
                self.player.send_message(f"You have created a new adventuring band: {player_name}'s Band.")
            except Exception as e:
                if "duplicate key" in str(e):
                    self.player.send_message("A band led by you already exists. Use BAND DELETE to remove it first.")
                else:
                    self.player.send_message(f"An error occurred: {e}")
            return

        # --- BAND LIST ---
        elif command == "list":
            if not self.player.band_id:
                self.player.send_message("You are not in an adventuring band.")
                return
            
            try:
                band_data = database.bands.find_one({"_id": ObjectId(self.player.band_id)})
                if not band_data:
                    self.player.send_message("Your band seems to be missing. Your band ID has been cleared.")
                    self.player.band_id = None
                    return
                
                self.player.send_message(f"--- {band_data['leader_name']}'s Band ---")
                for member_name in band_data["members"]:
                    member_obj = self.world.get_player_obj(member_name.lower())
                    status = " (Online)" if member_obj else " (Offline)"
                    self.player.send_message(f"- {member_name}{status}")
            except Exception as e:
                self.player.send_message("Your band ID appears to be corrupted. Clearing it.")
                self.player.band_id = None
            return

        # --- BAND INVITE ---
        elif command == "invite":
            if not args:
                self.player.send_message("Usage: BAND INVITE <player_name>")
                return
                
            if not self.player.band_id:
                self.player.send_message("You must create or be in a band to invite someone.")
                return
                
            try:
                band_data = database.bands.find_one({"_id": ObjectId(self.player.band_id)})
                if not band_data:
                    self.player.send_message("Your band is missing.")
                    self.player.band_id = None
                    return
                
                if band_data["leader_name"] != player_name:
                    self.player.send_message("Only the band leader can invite new members.")
                    return
                    
                if len(band_data.get("members", [])) >= 10:
                    self.player.send_message("Your band is full (10 members max).")
                    return
                
                target_name = " ".join(args)
                target_player_obj = self.world.get_player_obj(target_name.lower())
                
                if not target_player_obj:
                    self.player.send_message(f"Player '{target_name}' must be online to be invited.")
                    return
                    
                if target_player_obj.band_id:
                    self.player.send_message(f"{target_player_obj.name} is already in a band.")
                    return
                
                # Use the trading system to send the invite
                offer = {
                    "from_player_name": player_name,
                    "offer_time": time.time(),
                    "trade_type": "band_invite",
                    "band_id": str(self.player.band_id),
                    "band_name": f"{band_data['leader_name']}'s Band"
                }
                
                if self.world.get_pending_trade(target_player_obj.name.lower()):
                    self.player.send_message(f"{target_player_obj.name} has a pending offer. Please wait.")
                    return
                
                self.world.set_pending_trade(target_player_obj.name.lower(), offer)
                self.player.send_message(f"You have invited {target_player_obj.name} to join your band.")
                self.world.send_message_to_player(
                    target_player_obj.name.lower(),
                    f"{player_name} has invited you to join their adventuring band, \"{offer['band_name']}\".\n"
                    f"Type '<span class='keyword' data-command='accept'>ACCEPT</span>' or "
                    f"'<span class='keyword' data-command='decline'>DECLINE</span>'.",
                    "message"
                )
            except Exception:
                self.player.send_message("Your band ID appears to be corrupted. Clearing it.")
                self.player.band_id = None
            return

        # --- BAND REMOVE ---
        elif command == "remove":
            if not self.player.band_id:
                self.player.send_message("You are not in an adventuring band.")
                return
            
            try:
                band_id_obj = ObjectId(self.player.band_id)
                band_data = database.bands.find_one({"_id": band_id_obj})
                
                if not band_data:
                    self.player.send_message("Your band seems to be missing. Your band ID has been cleared.")
                    self.player.band_id = None
                    return
                
                if band_data["leader_name"] == player_name:
                    self.player.send_message("You are the leader. Use BAND KICK <self> or BAND DELETE.")
                    return
                
                database.bands.update_one(
                    {"_id": band_id_obj},
                    {"$pull": {"members": player_name}}
                )
                self.player.band_id = None
                self.player.send_message(f"You have left {band_data['leader_name']}'s Band.")
                
                # Notify leader
                leader_obj = self.world.get_player_obj(band_data["leader_name"].lower())
                if leader_obj:
                    self.world.send_message_to_player(leader_obj.name.lower(), f"{player_name} has left your band.", "message")
            except Exception:
                self.player.send_message("Your band ID appears to be corrupted. Clearing it.")
                self.player.band_id = None
            return

        # --- BAND KICK ---
        elif command == "kick":
            if not args:
                self.player.send_message("Usage: BAND KICK <player_name>")
                return
            
            if not self.player.band_id:
                self.player.send_message("You are not in an adventuring band.")
                return
                
            try:
                band_id_obj = ObjectId(self.player.band_id)
                band_data = database.bands.find_one({"_id": band_id_obj})
                
                if not band_data:
                    self.player.send_message("Your band is missing.")
                    self.player.band_id = None
                    return
                
                if band_data["leader_name"] != player_name:
                    self.player.send_message("Only the band leader can kick members.")
                    return
                
                target_name = " ".join(args)
                target_name_lower = target_name.lower()

                # Find proper capitalization
                target_name_proper = None
                for member in band_data["members"]:
                    if member.lower() == target_name_lower:
                        target_name_proper = member
                        break
                
                if not target_name_proper:
                    self.player.send_message(f"'{target_name}' is not in your band.")
                    return
                
                if target_name_proper == player_name:
                    self.player.send_message("You cannot kick yourself. Use BAND REMOVE or BAND DELETE.")
                    return
                
                database.bands.update_one(
                    {"_id": band_id_obj},
                    {"$pull": {"members": target_name_proper}}
                )
                self.player.send_message(f"You have kicked {target_name_proper} from the band.")
                
                # Update the target player's data (online or offline)
                target_obj = self.world.get_player_obj(target_name_lower)
                if target_obj:
                    target_obj.band_id = None
                    self.world.send_message_to_player(target_name_lower, f"You have been kicked from {band_data['leader_name']}'s Band.", "message")
                else:
                    database.players.update_one(
                        {"name": {"$regex": f"^{target_name_proper}$", "$options": "i"}},
                        {"$set": {"band_id": None}}
                    )
            except Exception:
                self.player.send_message("Your band ID appears to be corrupted. Clearing it.")
                self.player.band_id = None
            return

        # --- BAND DELETE ---
        elif command == "delete":
            if not self.player.band_id:
                self.player.send_message("You are not in an adventuring band.")
                return
            
            try:
                band_id_obj = ObjectId(self.player.band_id)
                band_data = database.bands.find_one({"_id": band_id_obj})
                
                if not band_data:
                    self.player.send_message("Your band is missing.")
                    self.player.band_id = None
                    return
                
                if band_data["leader_name"] != player_name:
                    self.player.send_message("Only the band leader can delete the band.")
                    return
                
                # Notify all members and clear their band_id
                for member_name in band_data["members"]:
                    member_obj = self.world.get_player_obj(member_name.lower())
                    if member_obj:
                        member_obj.band_id = None
                        self.world.send_message_to_player(member_name.lower(), f"{player_name} has deleted the adventuring band.", "message")
                    else:
                        database.players.update_one(
                            {"name": {"$regex": f"^{member_name}$", "$options": "i"}},
                            {"$set": {"band_id": None}}
                        )
                
                # Delete the band
                database.bands.delete_one({"_id": band_id_obj})
                self.player.send_message("You have deleted the adventuring band.")
            except Exception:
                self.player.send_message("Your band ID appears to be corrupted. Clearing it.")
                self.player.band_id = None
            return

        else:
            self.player.send_message(f"Unknown BAND command: '{command}'.")

class BT(BaseVerb):
    """
    Handles 'bt' (Band Talk).
    """
    def execute(self):
        if not self.args:
            self.player.send_message("What do you want to say to your band?")
            return
            
        if not self.player.band_id:
            self.player.send_message("You are not in an adventuring band.")
            return

        database = db.get_db()
        if not database:
            self.player.send_message("The Adventuring Band system is currently unavailable.")
            return

        try:
            band_data = database.bands.find_one({"_id": ObjectId(self.player.band_id)})
            if not band_data:
                self.player.send_message("Your band is missing.")
                self.player.band_id = None
                return
                
            message = " ".join(self.args)
            band_msg = f"[{self.player.name} (Band)]: {message}"
            
            for member_name in band_data["members"]:
                member_obj = self.world.get_player_obj(member_name.lower())
                if member_obj: # Only send to online members
                    self.world.send_message_to_player(member_name.lower(), band_msg, "message")
        except Exception:
            self.player.send_message("Your band ID appears to be corrupted. Clearing it.")
            self.player.band_id = None