# mud_backend/verbs/relations.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core import db

@VerbRegistry.register(["friend", "ignore", "befriend", "unfriend", "unignore"])
class Relations(BaseVerb):
    """
    Handles social lists.
    Usage:
      FRIEND <player>  - Toggles friend status
      IGNORE <player>  - Toggles ignore status
      FRIEND LIST      - Lists friends
      IGNORE LIST      - Lists ignored players
    """
    def execute(self):
        if not self.args:
            self.player.send_message("Usage: FRIEND <player>, IGNORE <player>, FRIEND LIST, IGNORE LIST")
            return

        command = self.command.lower()
        target_name = self.args[0].lower()
        
        # --- Handle Listing ---
        if target_name == "list":
            if "friend" in command or "befriend" in command:
                if not self.player.friends:
                    self.player.send_message("You have no friends listed.")
                else:
                    self.player.send_message(f"Friends: {', '.join([f.capitalize() for f in self.player.friends])}")
            elif "ignore" in command:
                if not self.player.ignored:
                    self.player.send_message("You are ignoring no one.")
                else:
                    self.player.send_message(f"Ignored: {', '.join([f.capitalize() for f in self.player.ignored])}")
            return

        # --- Resolve Target ---
        # We search DB because you might want to add offline players
        target_data = db.fetch_player_data(target_name)
        if not target_data:
            self.player.send_message(f"Player '{target_name}' does not exist.")
            return
            
        real_name = target_data["name"]
        real_name_lower = real_name.lower()
        
        if real_name_lower == self.player.name.lower():
            self.player.send_message("You cannot perform that action on yourself.")
            return

        # --- Handle Friend ---
        if command in ["friend", "befriend", "unfriend"]:
            if real_name_lower in self.player.friends:
                self.player.friends.remove(real_name_lower)
                self.player.send_message(f"You have removed {real_name} from your friends list.")
            else:
                if real_name_lower in self.player.ignored:
                    self.player.send_message(f"You cannot friend someone you are ignoring. Unignore {real_name} first.")
                    return
                self.player.friends.append(real_name_lower)
                self.player.send_message(f"You have added {real_name} to your friends list.")
                # Notify target if they are online
                self.world.send_message_to_player(real_name_lower, f"{self.player.name} has added you to their friends list.")

        # --- Handle Ignore ---
        elif command in ["ignore", "unignore"]:
            if real_name_lower in self.player.ignored:
                self.player.ignored.remove(real_name_lower)
                self.player.send_message(f"You have removed {real_name} from your ignore list.")
            else:
                if real_name_lower in self.player.friends:
                    self.player.send_message(f"You cannot ignore a friend. Unfriend {real_name} first.")
                    return
                # Check for admin immunity
                if target_data.get("is_admin"):
                    self.player.send_message("You cannot ignore an administrator.")
                    return
                    
                self.player.ignored.append(real_name_lower)
                self.player.send_message(f"You are now ignoring {real_name}. You will not see their messages.")
        
        self.player.mark_dirty()