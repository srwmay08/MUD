# mud_backend/verbs/religion.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry

@VerbRegistry.register(["worship", "pray"])
class Worship(BaseVerb):
    """
    Handles 'worship' command.
    WORSHIP LIST - Lists available deities.
    WORSHIP <deity> - Pledges devotion to a deity.
    """
    def execute(self):
        if not self.args:
            self._show_status()
            return

        arg = self.args[0].lower()

        if arg == "list":
            self._list_deities()
            return

        # Attempting to worship a deity
        target_deity = arg
        deities_data = self.world.assets.deities
        
        # Find exact match
        deity_key = None
        for key, data in deities_data.items():
            if key == target_deity or data["name"].lower() == target_deity:
                deity_key = key
                break
        
        if not deity_key:
            self.player.send_message(f"You do not know of a deity named '{self.args[0]}'.")
            return

        deity_data = deities_data[deity_key]
        deity_name = deity_data["name"]

        # Check if already worshipping
        if deity_key in self.player.deities:
            self.player.send_message(f"You are already a devotee of {deity_name}.")
            return

        # Check Conflicts
        for my_deity in self.player.deities:
            my_deity_data = deities_data.get(my_deity)
            if not my_deity_data: continue
            
            # Check if new deity conflicts with existing
            if deity_key in my_deity_data.get("conflicts", []):
                self.player.send_message(f"You cannot worship {deity_name} while you follow {my_deity_data['name']}. They are enemies!")
                return
            
            # Check if existing deity conflicts with new
            if my_deity in deity_data.get("conflicts", []):
                self.player.send_message(f"{deity_name} will not accept the devotion of one who follows {my_deity_data['name']}!")
                return

        # Success
        self.player.deities.append(deity_key)
        self.player.send_message(f"You kneel and pledge your service to **{deity_name}**, {deity_data.get('title', '')}.")
        self.player.send_message(f"You feel a subtle protective aura settle over you.")

    def _show_status(self):
        if not self.player.deities:
            self.player.send_message("You do not currently worship any deities.")
        else:
            names = []
            for d_key in self.player.deities:
                d_data = self.world.assets.deities.get(d_key, {})
                names.append(d_data.get("name", d_key.capitalize()))
            self.player.send_message(f"You follow the path of: {', '.join(names)}.")
        self.player.send_message("Type 'WORSHIP LIST' to see known deities.")

    def _list_deities(self):
        self.player.send_message("--- Known Deities of Abjuration ---")
        deities = self.world.assets.deities
        for key, data in deities.items():
            self.player.send_message(f"**{data['name']}**: {data.get('title', '')}")
            self.player.send_message(f"   {data.get('description', '')}")