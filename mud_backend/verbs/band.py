# mud_backend/verbs/band.py
import time
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from typing import Optional, Dict, Any
import uuid
from mud_backend.core import db 
from mud_backend.core.registry import VerbRegistry # <-- Added

MAX_BAND_MEMBERS = 10

@VerbRegistry.register(["band", "bt"]) 
class Band(BaseVerb):
    """Handles persistent Adventuring Band commands."""
    def execute(self):
        # Handle 'bt' alias shortcut
        if self.command.lower() == "bt":
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
            return

        if not self.args:
            self.player.send_message("Usage: BAND <create|invite|join|list|remove|kick|delete>")
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
                "pending_invites": {} 
            }
            
            self.world.set_band(new_band_id, new_band)
            db.save_band(new_band)
            
            self.player.band_id = new_band_id
            db.update_player_band(player_key, new_band_id) 
            
            self.player.send_message(f"You have created a new adventuring band! (Name: {self.player.name}'s Band)")
            self.player.send_message("Use BAND INVITE <player> to invite members.")
            return

        if command == "join":
            if not target_name:
                self.player.send_message("Usage: BAND JOIN <leader_name>")
                return
            
            if self.player.band_id:
                self.player.send_message("You are already in an adventuring band. Use BAND REMOVE first.")
                return

            target_leader_key = target_name.lower()
            invite_band = self.world.get_band_invite_for_player(player_key)
            
            if not invite_band or invite_band["pending_invites"].get(player_key) != target_leader_key:
                self.player.send_message(f"You have not been invited to a band by '{target_name.capitalize()}'.")
                return
            
            band_id = invite_band["id"]
            
            if len(invite_band["members"]) >= MAX_BAND_MEMBERS:
                self.player.send_message("That band is now full.")
                invite_band["pending_invites"].pop(player_key, None)
                self.world.set_band(band_id, invite_band)
                db.save_band(invite_band)
                return

            invite_band["pending_invites"].pop(player_key, None) 
            invite_band["members"].append(player_key)
            self.world.set_band(band_id, invite_band)
            db.save_band(invite_band) 
            
            self.player.band_id = band_id
            db.update_player_band(player_key, band_id) 
            
            self.world.send_message_to_band(band_id, f"{self.player.name.capitalize()} has joined the adventuring band!")
            return

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
            db.update_player_band(player_key, None) 
            self.player.send_message("You have left the adventuring band.")
            
            if is_leader:
                if band["members"]:
                    new_leader_key = band["members"][0]
                    band["leader"] = new_leader_key
                    self.world.set_band(band_id, band)
                    db.save_band(band)
                    self.world.send_message_to_band(band_id, f"{self.player.name} has left the band. {new_leader_key.capitalize()} is the new leader.")
                else:
                    self.world.remove_band(band_id)
                    db.delete_band(band_id)
            else:
                self.world.set_band(band_id, band)
                db.save_band(band)
                self.world.send_message_to_band(band_id, f"{self.player.name} has left the adventuring band.")
            return

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
            
            if target_player_key in band["members"]:
                self.player.send_message(f"{target_name.capitalize()} is already in your band.")
                return
                
            if target_player_key in band["pending_invites"]:
                self.player.send_message(f"You have already invited {target_name.capitalize()}.")
                return

            target_player_data = db.fetch_player_data(target_player_key) 
            if not target_player_data:
                self.player.send_message(f"There is no player named '{target_name}'.")
                return
                
            if target_player_data.get("band_id"):
                self.player.send_message(f"{target_name.capitalize()} is already in another adventuring band.")
                return

            band["pending_invites"][target_player_key] = player_key
            self.world.set_band(band_id, band)
            db.save_band(band)
            
            self.player.send_message(f"You have invited {target_name.capitalize()} to join your band.")
            
            self.world.send_message_to_player(
                target_player_key,
                f"{self.player.name} has invited you to join their adventuring band. "
                f"Type '<span class='keyword' data-command='band join {self.player.name}'>BAND JOIN {self.player.name}</span>' to accept."
            )
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
            db.save_band(band)
            
            self.world.send_message_to_band(band_id, f"{target_name.capitalize()} has been kicked from the adventuring band by the leader.")
            
            db.update_player_band(target_player_key, None)
            
            target_player_obj = self.world.get_player_obj(target_player_key)
            if target_player_obj:
                target_player_obj.band_id = None
                target_player_obj.send_message("You have been kicked from your adventuring band by the leader.")
            return
            
        if command == "delete":
            self.world.send_message_to_band(band_id, f"The adventuring band '{self.player.name}'s Band' has been deleted by the leader.", skip_player_key=player_key)
            self.player.send_message("You have deleted the adventuring band.")
            
            for member_key in band["members"]:
                db.update_player_band(member_key, None)
                member_obj = self.world.get_player_obj(member_key)
                if member_obj:
                    member_obj.band_id = None
            
            self.world.remove_band(band_id)
            db.delete_band(band_id)
            return
            
        self.player.send_message("Usage: BAND <create|invite|join|list|remove|kick|delete>")