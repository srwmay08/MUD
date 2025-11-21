# mud_backend/verbs/flags.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry # <-- Added
import re

# Define valid options for flags
FLAG_OPTIONS = {
    "mechanics": ["on", "numberless", "flavorless", "brief", "off"],
    "combat": ["on", "numberless", "flavorless", "brief", "off"],
    "showdeath": ["on", "off"],
    "descriptions": ["on", "brief", "off"],
    "ambient": ["on", "off"],
    "idlekick": ["on", "off"],
    "righthand": ["on", "off"],
    "lefthand": ["on", "off"],
    "safedrop": ["on", "off"],
    "groupinvites": ["on", "off"] 
}

# Define the default state for all flags
DEFAULT_FLAGS = {
    "mechanics": "on",
    "combat": "on",
    "showdeath": "on",
    "descriptions": "on",
    "ambient": "on",
    "idlekick": "on",
    "idletime": 30,
    "righthand": "on",
    "lefthand": "off",
    "safedrop": "on",
    "groupinvites": "on"
}

@VerbRegistry.register(["flag", "flags"]) # <-- Corrected Placement
class Flag(BaseVerb):
    """
    Handles the 'flag' command to set player preferences.
    """

    def _show_current_flags(self):
        flags = self.player.flags
        self.player.send_message("--- **Your Current Flags** ---")
        for key, default in DEFAULT_FLAGS.items():
            current_value = flags.get(key, default)
            self.player.send_message(f"{key.upper():<15} {str(current_value).upper()}")

    def execute(self):
        args_str = " ".join(self.args).lower()
        if args_str == "group open":
            self.args = ["groupinvites", "on"]
            self.player.send_message("(Alias for: FLAG GROUPINVITES ON)")
        elif args_str == "group close":
            self.args = ["groupinvites", "off"]
            self.player.send_message("(Alias for: FLAG GROUPINVITES OFF)")

        if not self.args:
            self._show_current_flags()
            return

        match = re.match(r"(\w+)\s+(.*)", " ".join(self.args))
        if not match:
            self.player.send_message("Usage: FLAG <setting> <value> (e.g., FLAG COMBAT BRIEF)")
            return
            
        flag_name = match.group(1).lower()
        value = match.group(2).lower()

        if flag_name == "idletime":
            try:
                time_val = int(value)
                if 5 <= time_val <= 120:
                    self.player.flags["idletime"] = time_val
                    self.player.send_message(f"Flag IDLETIME set to {time_val} minutes.")
                else:
                    self.player.send_message("IDLETIME must be between 5 and 120 minutes.")
            except ValueError:
                self.player.send_message("Usage: FLAG IDLETIME <minutes>")
            return

        elif flag_name in FLAG_OPTIONS:
            if value in FLAG_OPTIONS[flag_name]:
                self.player.flags[flag_name] = value
                self.player.send_message(f"Flag {flag_name.upper()} set to {value.upper()}.")
                
                if flag_name == "righthand" and value == "on":
                    if self.player.flags.get("lefthand") == "on":
                        self.player.flags["lefthand"] = "off"
                        self.player.send_message("Flag LEFTHAND set to OFF (mutually exclusive).")
                elif flag_name == "lefthand" and value == "on":
                     if self.player.flags.get("righthand") == "on":
                        self.player.flags["righthand"] = "off"
                        self.player.send_message("Flag RIGHTHAND set to OFF (mutually exclusive).")
            else:
                valid_str = ", ".join(FLAG_OPTIONS[flag_name]).upper()
                self.player.send_message(f"Invalid value. Options for {flag_name.upper()} are: {valid_str}.")
            return

        else:
            self.player.send_message(f"Unknown flag: '{flag_name}'.")
            self.player.send_message("Type FLAG to see all available settings.")