# mud_backend/verbs/group.py
import time
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from typing import Optional, Dict, Any
import uuid

MAX_GROUP_MEMBERS = 10

@VerbRegistry.register(["group"]) 
class Group(BaseVerb):
    """
    Handles all group-related commands:
    GROUP (status), GROUP <player>, GROUP LEADER <player>,
    GROUP REMOVE <player>, GROUP OPEN, GROUP CLOSE
    """
    def execute(self):
        # ... (Rest of code is unchanged) ...
        # (Paste the full content of Group.execute from your previous upload here)
        if not self.args:
            self._show_group_status()
            return

        command = self.args[0].lower()
        target_name = " ".join(self.args[1:])
        player_key = self.player.name.lower()
        
        if command == "open":
            self.player.flags["groupinvites"] = "on"
            self.player.send_message("You are now open to group invitations.")
            return
            
        if command == "close":
            self.player.flags["groupinvites"] = "off"
            self.player.send_message("You are no longer open to group invitations.")
            return
            
        group = self.world.get_group(self.player.group_id)
        
        if command == "leader":
            if not group:
                self.player.send_message("You are not in a group.")
                return
            if group["leader"] != player_key:
                self.player.send_message("Only the group leader can change leadership.")
                return
            if not target_name:
                self.player.send_message("Usage: GROUP LEADER <player>")
                return
            
            target_player_obj = self.world.get_player_obj(target_name.lower())
            if not target_player_obj or target_player_obj.group_id != self.player.group_id:
                self.player.send_message(f"'{target_name}' is not in your group.")
                return
                
            group["leader"] = target_player_obj.name.lower()
            self.world.set_group(self.player.group_id, group)
            
            self.world.send_message_to_group(self.player.group_id, f"{self.player.name} has made {target_player_obj.name} the new group leader.")
            return
            
        if command == "remove":
            if not group:
                self.player.send_message("You are not in a group.")
                return
            if group["leader"] != player_key:
                self.player.send_message("Only the group leader can remove members.")
                return
            if not target_name:
                self.player.send_message("Usage: GROUP REMOVE <player>")
                return
                
            target_player_obj = self.world.get_player_obj(target_name.lower())
            if not target_player_obj or target_player_obj.group_id != self.player.group_id:
                self.player.send_message(f"'{target_name}' is not in your group.")
                return
                
            if target_player_obj.name.lower() == player_key:
                self.player.send_message("You cannot remove yourself. Use LEAVE instead.")
                return
                
            target_player_obj.group_id = None
            group["members"].remove(target_player_obj.name.lower())
            self.world.set_group(self.player.group_id, group)
            
            self.world.send_message_to_group(self.player.group_id, f"{target_player_obj.name} has been removed from the group.")
            target_player_obj.send_message("You have been removed from the group.")
            return

        # GROUP <player> (Invite/Auto-Join)
        target_player_name = " ".join(self.args).lower()
        target_player_obj = self.world.get_player_obj(target_player_name)
        
        if not target_player_obj or target_player_obj.current_room_id != self.player.current_room_id:
            self.player.send_message(f"You don't see anyone named '{target_player_name}' here.")
            return
            
        if target_player_obj.group_id:
            self.player.send_message(f"{target_player_obj.name} is already in a group.")
            return
            
        pending_invite = self.world.get_pending_group_invite(target_player_name)
        if pending_invite and pending_invite.get("from_player_name", "").lower() != player_key:
            self.player.send_message(f"{target_player_obj.name} already has a pending group invitation from someone else.")
            return

        if not group:
            new_group_id = uuid.uuid4().hex
            group = {
                "id": new_group_id,
                "leader": player_key,
                "members": [player_key]
            }
            self.world.set_group(new_group_id, group)
            self.player.group_id = new_group_id
        else:
            if group["leader"] != player_key:
                self.player.send_message("Only the group leader can invite new members.")
                return

        if target_player_obj.flags.get("groupinvites", "on") == "off":
            self.player.send_message(f"You invite {target_player_obj.name} to join your group.")
            invite = {
                "from_player_name": self.player.name,
                "group_id": self.player.group_id,
                "time": time.time()
            }
            self.world.set_pending_group_invite(target_player_name, invite)
            
            self.world.send_message_to_player(
                target_player_obj.name.lower(),
                f"{self.player.name} has invited you to join their group. (Expires in 30 seconds)\n"
                f"Type '<span class='keyword' data-command='join {self.player.name}'>JOIN {self.player.name}</span>' to accept.",
                "message"
            )
        else:
            if len(group["members"]) >= MAX_GROUP_MEMBERS:
                self.player.send_message(f"Your group is full. You cannot add {target_player_obj.name}.")
                return

            group["members"].append(target_player_obj.name.lower())
            target_player_obj.group_id = self.player.group_id
            self.world.set_group(self.player.group_id, group)
            
            self.player.send_message(f"You invite {target_player_obj.name} to join your group.")
            self.world.send_message_to_group(self.player.group_id, f"{target_player_obj.name} has joined the group.")

    def _show_group_status(self):
        group = self.world.get_group(self.player.group_id)
        if not group:
            self.player.send_message("You are not currently in a group.")
            return
            
        leader_name = group['leader'].capitalize()
        members = [name.capitalize() for name in group['members']]
        
        self.player.send_message(f"--- Group Status (Leader: {leader_name}) ---")
        for member_name in members:
            status = "(Leader)" if member_name.lower() == group['leader'] else ""
            self.player.send_message(f"- {member_name} {status}")

@VerbRegistry.register(["hold"]) 
class Hold(BaseVerb):
    def execute(self):
        player_key = self.player.name.lower()
        target_player_name = " ".join(self.args).lower()
        
        target_player_obj = self.world.get_player_obj(target_player_name)
        
        if not target_player_obj or target_player_obj.current_room_id != self.player.current_room_id:
            self.player.send_message(f"You don't see anyone named '{target_player_name}' here.")
            return
            
        if target_player_obj.group_id:
            self.player.send_message(f"{target_player_obj.name} is already in a group.")
            return
        
        pending_invite = self.world.get_pending_group_invite(target_player_name)
        if pending_invite and pending_invite.get("from_player_name", "").lower() != player_key:
            self.player.send_message(f"{target_player_obj.name} is considering another offer.")
            return
            
        group = self.world.get_group(self.player.group_id)
        
        if not group:
            new_group_id = uuid.uuid4().hex
            group = {
                "id": new_group_id,
                "leader": player_key,
                "members": [player_key]
            }
            self.world.set_group(new_group_id, group)
            self.player.group_id = new_group_id
        else:
            if group["leader"] != player_key:
                self.player.send_message("Only the group leader can invite new members.")
                return

        if target_player_obj.flags.get("groupinvites", "on") == "off":
            self.player.send_message(f"You reach out to {target_player_obj.name}, inviting them to join...")
            invite = {
                "from_player_name": self.player.name,
                "group_id": self.player.group_id,
                "time": time.time()
            }
            self.world.set_pending_group_invite(target_player_name, invite)
            
            self.world.send_message_to_player(
                target_player_obj.name.lower(), 
                f"{self.player.name} reaches out to you, inviting you to join their group. (Expires in 30 seconds)\n"
                f"Type '<span class='keyword' data-command='join {self.player.name}'>JOIN {self.player.name}</span>' to accept.",
                "message" 
            )
        else:
            if len(group["members"]) >= MAX_GROUP_MEMBERS:
                self.player.send_message(f"Your group is full. You cannot add {target_player_obj.name}.")
                return
                
            group["members"].append(target_player_obj.name.lower())
            target_player_obj.group_id = self.player.group_id
            self.world.set_group(self.player.group_id, group)

            self.player.send_message(f"You reach out to hold {target_player_obj.name}'s hand...")
            self.world.send_message_to_group(self.player.group_id, f"{target_player_obj.name} has joined the group.")

@VerbRegistry.register(["join"]) 
class Join(BaseVerb):
    def execute(self):
        if not self.args:
            self.player.send_message("Usage: JOIN <player>")
            return
            
        if self.player.group_id:
            self.player.send_message("You are already in a group. You must LEAVE first.")
            return

        player_key = self.player.name.lower()
        target_leader_name = " ".join(self.args).lower()
        
        invite = self.world.get_pending_group_invite(player_key)
        
        if invite and invite["from_player_name"].lower() == target_leader_name:
            self.world.remove_pending_group_invite(player_key) 
            
            group = self.world.get_group(invite["group_id"])
            
            if not group:
                self.player.send_message("That group no longer exists.")
                return
                
            leader_obj = self.world.get_player_obj(group["leader"])
            if not leader_obj or leader_obj.current_room_id != self.player.current_room_id:
                self.player.send_message(f"{group['leader'].capitalize()} is no longer here.")
                return
                
            if len(group["members"]) >= MAX_GROUP_MEMBERS:
                self.player.send_message("That group is now full.")
                return
                
            group["members"].append(player_key)
            self.player.group_id = invite["group_id"]
            self.world.set_group(invite["group_id"], group)
            
            self.world.send_message_to_group(invite["group_id"], f"{self.player.name} has joined the group.")
            return
        
        target_leader_obj = self.world.get_player_obj(target_leader_name)
        
        if not target_leader_obj or target_leader_obj.current_room_id != self.player.current_room_id:
            self.player.send_message(f"You don't see anyone named '{target_leader_name}' here.")
            return
            
        if target_leader_obj.flags.get("groupinvites", "on") == "off":
            self.player.send_message(f"{target_leader_obj.name} is not accepting group invitations right now.")
            return
        
        target_group = self.world.get_group(target_leader_obj.group_id)
        
        if not target_group:
            new_group_id = uuid.uuid4().hex
            new_group = {
                "id": new_group_id,
                "leader": target_leader_name, 
                "members": [target_leader_name, player_key] 
            }
            self.world.set_group(new_group_id, new_group)
            self.player.group_id = new_group_id
            target_leader_obj.group_id = new_group_id 
            
            self.world.send_message_to_group(new_group_id, f"{self.player.name} has joined {target_leader_obj.name}'s group.")

        else:
            if target_group["leader"] != target_leader_name:
                self.player.send_message(f"{target_leader_obj.name} is not the leader of their group. You must join the leader.")
                return
            
            if len(target_group["members"]) >= MAX_GROUP_MEMBERS:
                self.player.send_message("That group is now full.")
                return
                
            target_group["members"].append(player_key)
            self.player.group_id = target_group["id"]
            self.world.set_group(target_group["id"], target_group)
            
            self.world.send_message_to_group(target_group["id"], f"{self.player.name} has joined the group.")

@VerbRegistry.register(["leave"]) 
class Leave(BaseVerb):
    def execute(self):
        group = self.world.get_group(self.player.group_id)
        if not group:
            self.player.send_message("You are not in a group.")
            return
            
        player_key = self.player.name.lower()
        group_id = self.player.group_id
        
        self.player.send_message("You leave the group.")
        self.player.group_id = None
        group["members"].remove(player_key)
        self.world.send_message_to_group(group_id, f"{self.player.name} has left the group.")
        
        if group["leader"] == player_key:
            if group["members"]:
                new_leader_key = group["members"][0]
                group["leader"] = new_leader_key
                self.world.set_group(group_id, group)
                self.world.send_message_to_group(group_id, f"{new_leader_key.capitalize()} is the new group leader.")
            else:
                self.world.remove_group(group_id)
        else:
            self.world.set_group(group_id, group)
            
@VerbRegistry.register(["disband"]) 
class Disband(BaseVerb):
    def execute(self):
        group = self.world.get_group(self.player.group_id)
        if not group:
            self.player.send_message("You are not in a group.")
            return
            
        if group["leader"] != self.player.name.lower():
            self.player.send_message("Only the group leader can disband the group.")
            return
            
        self.player.send_message("You disband the group.")
        
        group_id = self.player.group_id
        
        for member_key in group["members"]:
            member_obj = self.world.get_player_obj(member_key)
            if member_obj:
                member_obj.group_id = None
                if member_key != self.player.name.lower():
                    member_obj.send_message("The group has been disbanded by the leader.")
                    
        self.world.remove_group(group_id)