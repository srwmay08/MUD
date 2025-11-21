# mud_backend/verbs/whisper.py
# NEW FILE
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime

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
            
            # Send to all members, including self
            group_id = self.player.group_id
            self.world.send_message_to_group(
                group_id,
                f"{self.player.name} whispers to the group, \"{message}\"",
                msg_type="group_chat"
            )
            
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

            group_id = self.player.group_id
            self.world.send_message_to_group(
                group_id,
                f"OOC [Group] {self.player.name}: {message}",
                msg_type="group_chat_ooc"
            )

        else:
            # --- WHISPER <player> ---
            target_player = self.world.get_player_obj(target)
            if not target_player:
                self.player.send_message(f"You cannot find '{self.args[0]}' to whisper to.")
                return
            
            if target_player.name.lower() == self.player.name.lower():
                self.player.send_message("You mumble to yourself.")
                return

            # Send to target
            target_player.send_message(f"{self.player.name} whispers to you, \"{message}\"")
            
            # Send to self
            self.player.send_message(f"You whisper to {target_player.name}, \"{message}\"")