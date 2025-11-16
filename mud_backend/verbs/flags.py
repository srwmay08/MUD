# mud_backend/verbs/flags.py
from mud_backend.verbs.base_verb import BaseVerb
from typing import Dict, Any, List

# Master configuration for all player-settable flags
# 'values' is a list of valid options. Use ["ON", "OFF"] for booleans.
# Use ["NUMBER"] for numeric input.
FLAG_CONFIG = {
    "MECHANICS": {
        "desc": "How much detail to show for skill/mechanics rolls (e.g., prospecting, tripping).",
        "values": ["ON", "BRIEF", "NUMBERLESS", "OFF"],
        "default": "ON"
    },
    "SHOWDEATH": {
        "desc": "Show broadcast messages when other players are defeated.",
        "values": ["ON", "OFF"],
        "default": "ON"
    },
    "DESCRIPTIONS": {
        "desc": "The level of detail to show in room descriptions.",
        "values": ["ON", "BRIEF", "OFF"],
        "default": "ON"
    },
    "AMBIENT": {
        "desc": "Show ambient messages (e.g., weather, monster idles, corpse decay).",
        "values": ["ON", "OFF"],
        "default": "ON"
    },
    "COMBAT": {
        "desc": "The level of detail to show for your combat messages.",
        "values": ["ON", "BRIEF", "NUMBERLESS", "OFF"],
        "default": "ON"
    },
    "IDLE": {
        "desc": "Set to ON to prevent your character from being disconnected for idling.",
        "values": ["ON", "OFF"],
        "default": "OFF"
    },
    "IDLESET": {
        "desc": "Customize your idle timeout length in minutes (when IDLE is OFF).",
        "values": ["NUMBER"],
        "default": 30
    },
    "RIGHTHAND": {
        "desc": "Default to using your right hand first when using GET.",
        "values": ["ON", "OFF"],
        "default": "ON"
    },
    "LEFTHAND": {
        "desc": "Default to using your left hand first when using GET.",
        "values": ["ON", "OFF"],
        "default": "OFF"
    },
    "SAFEDROP": {
        "desc": "Require confirmation when dropping items on the ground.",
        "values": ["ON", "OFF"],
        "default": "ON"
    }
}


class Flag(BaseVerb):
    """
    Handles the 'flag' command.
    Allows the player to view and set their preferences.
    """

    def _show_flags(self):
        """Displays all available flags and their current settings."""
        self.player.send_message("<span class='room-title'>--- Your Current Flags ---</span>")
        
        # Use sorted keys for a consistent order
        for flag_name in sorted(FLAG_CONFIG.keys()):
            config_data = FLAG_CONFIG[flag_name]
            current_value = self.player.flags.get(flag_name, config_data["default"])
            
            # Format the display
            line = f"- **{flag_name}**: {current_value}"
            
            # Add valid options for clarity
            if config_data["values"] == ["ON", "OFF"]:
                options = "(<span class='keyword' data-command='flag {flag_name} ON'>ON</span>/<span class='keyword' data-command='flag {flag_name} OFF'>OFF</span>)"
            elif config_data["values"] == ["NUMBER"]:
                options = "(e.g., <span class='keyword' data-command='flag {flag_name} 15'>FLAG {flag_name} 15</span>)"
            else:
                options_list = "/".join([
                    f"<span class='keyword' data-command='flag {flag_name} {v}'>{v}</span>"
                    for v in config_data["values"]
                ])
                options = f"({options_list})"
            
            self.player.send_message(f"{line:<30} {options.format(flag_name=flag_name)}")
        
        self.player.send_message("\nType <span class='keyword' data-command='flag {flag_name} {value}'>FLAG {NAME} {VALUE}</span> to change a setting.")

    def execute(self):
        if not self.args:
            self._show_flags()
            return

        if len(self.args) < 2:
            # Check for just "flag {name}" to show help for one
            flag_name_in = self.args[0].upper()
            if flag_name_in in FLAG_CONFIG:
                self.player.send_message(f"**{flag_name_in}**: {FLAG_CONFIG[flag_name_in]['desc']}")
                self.player.send_message(f"Current setting: {self.player.flags.get(flag_name_in, FLAG_CONFIG[flag_name_in]['default'])}")
            else:
                self.player.send_message("Usage: FLAG <NAME> <VALUE> (e.g., FLAG AMBIENT OFF)")
            return

        flag_name_in = self.args[0].upper()
        value_in = " ".join(self.args[1:]).upper()

        if flag_name_in not in FLAG_CONFIG:
            self.player.send_message(f"'{flag_name_in}' is not a valid flag name. Type FLAG to see all options.")
            return

        config_data = FLAG_CONFIG[flag_name_in]
        
        # --- Value Validation ---
        if config_data["values"] == ["NUMBER"]:
            try:
                numeric_value = int(value_in)
                if flag_name_in == "IDLESET":
                    if numeric_value < 5:
                        self.player.send_message("IDLESET must be at least 5 minutes.")
                        return
                    self.player.flags[flag_name_in] = numeric_value
                    self.player.send_message(f"Flag **{flag_name_in}** set to **{numeric_value}** minutes.")
                else:
                    self.player.flags[flag_name_in] = numeric_value
                    self.player.send_message(f"Flag **{flag_name_in}** set to **{numeric_value}**.")
            except ValueError:
                self.player.send_message(f"{flag_name_in} requires a numeric value.")
                return
        
        elif value_in in config_data["values"]:
            # Standard value setting (e.g., ON, OFF, BRIEF)
            self.player.flags[flag_name_in] = value_in
            self.player.send_message(f"Flag **{flag_name_in}** set to **{value_in}**.")
            
            # --- Special: Handle mutual exclusivity for hands ---
            if flag_name_in == "RIGHTHAND" and value_in == "ON":
                if self.player.flags.get("LEFTHAND") == "ON":
                    self.player.flags["LEFTHAND"] = "OFF"
                    self.player.send_message("Flag **LEFTHAND** set to **OFF**.")
            elif flag_name_in == "LEFTHAND" and value_in == "ON":
                if self.player.flags.get("RIGHTHAND") == "ON":
                    self.player.flags["RIGHTHAND"] = "OFF"
                    self.player.send_message("Flag **RIGHTHAND** set to **OFF**.")
        
        else:
            self.player.send_message(f"'{value_in}' is not a valid value for {flag_name_in}.")
            self.player.send_message(f"Valid options are: {', '.join(config_data['values'])}")
            return