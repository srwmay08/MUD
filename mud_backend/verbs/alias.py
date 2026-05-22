# mud_backend/verbs/alias.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry

@VerbRegistry.register(["alias", "unalias"])
class Alias(BaseVerb):
    """
    Handles player-defined aliases.
    Usage:
      ALIAS - List all aliases.
      ALIAS <key> <command> - Create/Update an alias (e.g., 'ALIAS k kill kobold').
      UNALIAS <key> - Remove an alias.
    """
    def execute(self):
        # We need to access the command used (alias vs unalias)
        cmd = self.command.lower()

        if cmd == "unalias":
            if not self.args:
                self.player.send_message("Usage: UNALIAS <key>")
                return
            
            key = self.args[0].lower()
            if key in self.player.aliases:
                del self.player.aliases[key]
                self.player.send_message(f"Alias '{key}' removed.")
            else:
                self.player.send_message(f"You do not have an alias named '{key}'.")
            return

        # Handle ALIAS
        if not self.args:
            # List aliases
            if not self.player.aliases:
                self.player.send_message("You have no aliases defined.")
            else:
                self.player.send_message("--- Your Aliases ---")
                for k, v in self.player.aliases.items():
                    self.player.send_message(f"{k} => {v}")
            return

        key = self.args[0].lower()
        
        if len(self.args) < 2:
            # View specific alias
            val = self.player.aliases.get(key)
            if val:
                self.player.send_message(f"Alias: {key} => {val}")
            else:
                self.player.send_message(f"Alias '{key}' not found.")
            return

        # Set alias
        value = " ".join(self.args[1:])
        
        # Safety check: Prevent aliasing 'alias' to infinite loops
        if key == "alias" or key == "unalias":
            self.player.send_message("You cannot override the alias command itself.")
            return

        self.player.aliases[key] = value
        self.player.send_message(f"Alias set: {key} => {value}")