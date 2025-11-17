# mud_backend/verbs/band.py
# NEW FILE
import time
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from typing import Optional, Dict, Any
import uuid

MAX_BAND_MEMBERS = 10

class Band(BaseVerb):
    """
    Handles all persistent Adventuring Band commands:
    BAND CREATE, BAND INVITE, BAND LIST, BAND REMOVE, BAND KICK, BAND DELETE
    """
    def execute(self):
        if not self.args:
            self.player.send_message("Usage: BAND <create|invite|list|remove|kick|delete>")
            return
            
        command = self.args[0].lower()
        target_name = " ".join(self.args[1:])
        player_key = self.player.name.lower()
        
        if command == "create":
            if self.player.band_id:
                self.player.send_message("You are already in an adventuring band. Use BAND REMOVE first.")
                return
            
            new_band_id = uuid.uuid4().hex
            new_band = {
                "id": new_band_id,
                "leader": player_key,
                "members": [player_key],
                "pending_invites": {} # { "player_name": "inviter_name" }
            }
            
            self.world.set_band(new_band_id, new_band)
            self.world.db.save_band(new_band) # Save to DB
            
            self.player.band_id = new_band_id
            self.player.send_message(f"You have created a new adventuring band! (Name: {self.player.name}'s Band)")
            self.player.send_message("Use BAND INVITE <player> to invite members.")
            return

        # --- Commands that require you to be in a band ---
        band = self.world.get_band(self.player.band_id)
        if not band:
            self.player.send_message("You are not currently in an adventuring band.")
            return
            
        band_id = self.player.band_id
        is_leader = band["leader"] == player_key

        if command == "list":
            leader_name = band['leader'].capitalize()
            members = [name.capitalize() for name in band['members']]
            self.player.send_message(f"--- Adventuring Band (Leader: {leader_name}) ---")
            for member_name in members:
                status = "(Leader)" if member_name.lower() == band['leader'] else ""
                self.player.send_message(f"- {member_name} {status}")
            self.player.send_message(f"({len(members)}/{MAX_BAND_MEMBERS} members)")
            return
            
        if command == "remove":
            band["members"].remove(player_key)
            self.player.band_id = None
            self.player.send_message("You have left the adventuring band.")
            
            if is_leader:
                # Leader left, pick new leader or disband
                if band["members"]:
                    new_leader_key = band["members"][0]
                    band["leader"] = new_leader_key
                    self.world.set_band(band_id, band)
                    self.world.db.save_band(band)
                    self.world.send_message_to_band(band_id, f"{self.player.name} has left the band. {new_leader_key.capitalize()} is the new leader.")
                else:
                    # Band is empty, delete it
                    self.world.remove_band(band_id)
                    self.world.db.delete_band(band_id)
                    # No one to message
            else:
                # Member left
                self.world.set_band(band_id, band)
                self.world.db.save_band(band)
                self.world.send_message_to_band(band_id, f"{self.player.name} has left the adventuring band.")
            return

        # --- Leader-only commands ---
        if not is_leader:
            self.player.send_message("Only the band leader can do that.")
            return
            
        if command == "invite":
            if not target_name:
                self.player.send_message("Usage: BAND INVITE <player>")
                return
            
            if len(band["members"]) >= MAX_BAND_MEMBERS:
                self.player.send_message(f"Your band is full. You cannot invite more than {MAX_BAND_MEMBERS} members.")
                return

            target_player_key = target_name.lower()
            
            # Check if player exists (in DB, not just online)
            target_player_data = self.world.db.fetch_player_data(target_player_key)
            if not target_player_data:
                self.player.send_message(f"There is no player named '{target_name}'.")
                return
                
            if target_player_data.get("band_id"):
                self.player.send_message(f"{target_name.capitalize()} is already in an adventuring band.")
                return

            band["pending_invites"][target_player_key] = player_key
            self.world.set_band(band_id, band)
            self.world.db.save_band(band)
            
            self.player.send_message(f"You have invited {target_name.capitalize()} to join your band.")
            
            # Send to target player *if they are online*
            self.world.send_message_to_player(
                target_player_key,
                f"{self.player.name} has invited you to join their adventuring band. "
                f"Type '<span class='keyword' data-command='band join {self.player.name}'>BAND JOIN {self.player.name}</span>' to accept."
            )
            return
            
        if command == "join":
            # This is how a player *accepts* an invite
            target_leader_name = target_name.lower()
            if band["pending_invites"].get(player_key) == target_leader_name:
                # This player (self) was invited by the target leader
                # But self is ALREADY in a band (this one). This logic is for the *inviter*.
                # The *invitee* logic is separate.
                self.player.send_message("You are already in a band. Use BAND REMOVE first.")
            else:
                # This is the *invitee* accepting
                invitee_key = self.player.name.lower()
                invite = band["pending_invites"].get(invitee_key)
                
                if invite and invite == target_leader_name:
                    # Correct! Player is accepting the invite from the leader of this band
                    band["pending_invites"].pop(invitee_key, None)
                    band["members"].append(invitee_key)
                    self.world.set_band(band_id, band)
                    self.world.db.save_band(band)
                    
                    self.player.band_id = band_id
                    self.world.send_message_to_band(band_id, f"{self.player.name.capitalize()} has joined the adventuring band!")
                else:
                    self.player.send_message("You have not been invited to that band, or the invite is invalid.")
            return

        if command == "kick":
            if not target_name:
                self.player.send_message("Usage: BAND KICK <player>")
                return
            
            target_player_key = target_name.lower()
            if target_player_key == player_key:
                self.player.send_message("You cannot kick yourself. Use BAND REMOVE.")
                return
                
            if target_player_key not in band["members"]:
                self.player.send_message(f"'{target_name}' is not in your adventuring band.")
                return
                
            band["members"].remove(target_player_key)
            self.world.set_band(band_id, band)
            self.world.db.save_band(band)
            
            self.world.send_message_to_band(band_id, f"{target_name.capitalize()} has been kicked from the adventuring band by the leader.")
            
            # Update the kicked player in the DB
            self.world.db.update_player_band(target_player_key, None)
            
            target_player_obj = self.world.get_player_obj(target_player_key)
            if target_player_obj:
                target_player_obj.band_id = None
                target_player_obj.send_message("You have been kicked from your adventuring band by the leader.")
            return
            
        if command == "delete":
            self.world.send_message_to_band(band_id, f"The adventuring band '{self.player.name}'s Band' has been deleted by the leader.", skip_player_key=player_key)
            self.player.send_message("You have deleted the adventuring band.")
            
            # Remove band_id from all players
            for member_key in band["members"]:
                self.world.db.update_player_band(member_key, None)
                member_obj = self.world.get_player_obj(member_key)
                if member_obj:
                    member_obj.band_id = None
            
            # Delete from cache and DB
            self.world.remove_band(band_id)
            self.world.db.delete_band(band_id)
            return
            
        self.player.send_message("Usage: BAND <create|invite|list|remove|kick|delete>")


class BT(BaseVerb):
    """
    Handles the 'bt' (Band Talk) command.
    """
    def execute(self):
        if not self.player.band_id:
            self.player.send_message("You are not in an adventuring band.")
            return
            
        if not self.args:
            self.player.send_message("What do you want to say to your band?")
            return
            
        message = " ".join(self.args)
        self.world.send_message_to_band(
            self.player.band_id,
            f"[{self.player.name}] {message}",
            msg_type="band_chat"
        )