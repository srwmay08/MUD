# mud_backend/verbs/assess.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.verbs.item_actions import _get_item_data

class Assess(BaseVerb):
    """
    ASSESS <item|furnace>
    Gives mechanical feedback on crafting items.
    """
    def execute(self):
        if not self.args:
            self.player.send_message("Assess what?")
            return
            
        target = " ".join(self.args).lower()
        
        # Check room objects (Furnace)
        for obj in self.room.objects:
            if target in obj.get("keywords", []) and "state" in obj:
                state = obj["state"]
                temp = state.get("temp", 0)
                fuel = state.get("fuel", 0)
                self.player.send_message(f"--- Assessment: {obj['name']} ---")
                self.player.send_message(f"Temperature: {temp} C")
                self.player.send_message(f"Fuel Level:  {fuel}")
                self.player.send_message(f"Air Flow:    {state.get('air_flow')}%")
                return
        
        self.player.send_message("You don't see that here to assess.")