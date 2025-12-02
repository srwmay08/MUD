# mud_backend/verbs/whisper.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.registry import VerbRegistry

@VerbRegistry.register(["whisper"])
class Whisper(BaseVerb):
    """
    Handles the 'whisper' command for private and group chat.
    WHISPER <player> <message>
    WHISPER GROUP <message>
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="speak"):
            return

        if not self.args:
            self.player.send_message("Usage: WHISPER <player> <message> OR WHISPER GROUP <message>")
            return

        target = self.args[0].lower()
        message = " ".join(self.args[1:])

        if not message:
            self.player.send_message("What do you want to whisper?")
            return

        if target == "group" or target == "g":
            # --- WHISPER GROUP ---
            group = self.world.get_group(self.player.group_id)
            if not group:
                self.player.send_message("You are not in a group.")
                return
            
            group_id = self.player.group_id
            # Send to all members, skipping ignores logic is complex for groups.
            # Usually groups imply trust, so we might skip ignore checks, 
            # OR we manually iterate members. Let's iterate.
            
            full_msg = f"{self.player.name} whispers to the group, \"{message}\""
            
            for member_key in group["members"]:
                # Self
                if member_key == self.player.name.lower():
                    self.player.send_message(full_msg)
                    continue

                member_obj = self.world.get_player_obj(member_key)
                if member_obj:
                    if member_obj.is_ignoring(self.player.name):
                        continue
                    member_obj.send_message(full_msg, "group_chat")
            
        elif target == "ooc":
            # --- WHISPER OOC GROUP ---
            if not self.args[1:] or self.args[1].lower() not in ["group", "g"]:
                self.player.send_message("Usage: WHISPER OOC GROUP <message>")
                return
            
            message = " ".join(self.args[2:])
            if not message:
                self.player.send_message("What do you want to say?")
                return
                
            group = self.world.get_group(self.player.group_id)
            if not group:
                self.player.send_message("You are not in a group.")
                return

            full_msg = f"OOC [Group] {self.player.name}: {message}"
            
            for member_key in group["members"]:
                if member_key == self.player.name.lower():
                    self.player.send_message(full_msg, "group_chat_ooc")
                    continue
                    
                member_obj = self.world.get_player_obj(member_key)
                if member_obj:
                    if member_obj.is_ignoring(self.player.name):
                        continue
                    member_obj.send_message(full_msg, "group_chat_ooc")

        else:
            # --- WHISPER <player> ---
            target_player = self.world.get_player_obj(target)
            if not target_player:
                self.player.send_message(f"You cannot find '{self.args[0]}' to whisper to.")
                return
            
            if target_player.name.lower() == self.player.name.lower():
                self.player.send_message("You mumble to yourself.")
                return

            # Check Ignore
            if target_player.is_ignoring(self.player.name):
                # Standard behavior: Don't tell the sender they are ignored, just drop it.
                # Or tell them "They are not listening."
                self.player.send_message(f"You whisper to {target_player.name}, \"{message}\"")
                return

            # Send to target
            target_player.send_message(f"{self.player.name} whispers to you, \"{message}\"")
            
            # Send to self
            self.player.send_message(f"You whisper to {target_player.name}, \"{message}\"")