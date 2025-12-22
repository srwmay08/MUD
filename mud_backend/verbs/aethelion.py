# mud_backend/verbs/aethelion.py
import random
import time
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core.utils import check_action_roundtime, set_action_roundtime
from mud_backend.core.item_utils import find_item_in_inventory

@VerbRegistry.register(["polish"])
class Polish(BaseVerb):
    """
    POLISH <object>
    Quest: Polish the Sun-Discs to remove tarnish.
    """
    def execute(self):
        if check_action_roundtime(self.player, action_type="other"): return
        if not self.args:
            self.player.send_message("Polish what?")
            return

        target = " ".join(self.args).lower()
        
        # Find the Sun-Disc
        found_disc = False
        for obj in self.room.objects:
            if "sun-disc" in obj.get("keywords", []) and (target == "disc" or target in obj.get("keywords", [])):
                found_disc = True
                break
        
        if not found_disc:
            self.player.send_message("You don't see that here to polish.")
            return

        self.player.send_message("You vigorously polish the golden sun-disc, removing the grime of the city...")
        self.player.send_message("The disc gleams, reflecting the light with renewed brilliance.")
        
        # Update Counter
        self.player.quest_counters["polished_sun_disc"] = self.player.quest_counters.get("polished_sun_disc", 0) + 1
        set_action_roundtime(self.player, 5.0, rt_type="hard")


@VerbRegistry.register(["light"])
class Light(BaseVerb):
    """
    LIGHT <object>
    Quest: Light the Braziers. Requires Coal.
    """
    def execute(self):
        if check_action_roundtime(self.player, action_type="other"): return
        if not self.args:
            self.player.send_message("Light what?")
            return

        target = " ".join(self.args).lower()
        
        # Find Brazier
        found_brazier = False
        for obj in self.room.objects:
            if "brazier" in obj.get("keywords", []) and (target == "brazier" or target in obj.get("keywords", [])):
                found_brazier = True
                break
                
        if not found_brazier:
            self.player.send_message("You don't see a brazier here.")
            return

        # Check for Coal
        coal_id = find_item_in_inventory(self.player, self.world.game_items, "coal")
        if not coal_id:
            self.player.send_message("You need fuel (coal) to light the brazier.")
            return

        # Consume Coal
        self.player.inventory.remove(coal_id)
        
        self.player.send_message("You place a lump of coal in the brazier and strike a spark.")
        self.player.send_message("The holy fire roars to life, banishing the shadows!")
        
        # Update Counter
        self.player.quest_counters["lit_brazier"] = self.player.quest_counters.get("lit_brazier", 0) + 1
        set_action_roundtime(self.player, 4.0, rt_type="hard")


@VerbRegistry.register(["recite"])
class Recite(BaseVerb):
    """
    RECITE <text>
    Quest: Recite the Litany of Law.
    """
    LITANY = "i vow to uphold the light"

    def execute(self):
        if check_action_roundtime(self.player, action_type="speak"): return
        
        if "altar" not in [k for obj in self.room.objects for k in obj.get("keywords", [])]:
            self.player.send_message("You should probably be near an altar to recite holy vows.")
            return

        text = " ".join(self.args).lower().strip().replace('"', '').replace("'", "")
        
        self.player.send_message(f"You recite, \"{text}\"")
        self.world.broadcast_to_room(self.room.room_id, f"{self.player.name} recites, \"{text}\"", "message", skip_sid=self.player.uid)

        if text == self.LITANY:
            self.player.send_message("You feel a sense of clarity and purpose settle over your mind.")
            self.player.quest_counters["recited_litany"] = self.player.quest_counters.get("recited_litany", 0) + 1
        else:
            self.player.send_message("You stumble over the words. That is not the correct Litany.")


@VerbRegistry.register(["scrub"])
class Scrub(BaseVerb):
    """
    SCRUB <object>
    Quest: Scrub the Marble Steps.
    """
    def execute(self):
        if check_action_roundtime(self.player, action_type="other"): return
        
        target = " ".join(self.args).lower()
        
        # Find Steps
        found_steps = False
        for obj in self.room.objects:
            if "steps" in obj.get("keywords", []) and (target == "steps" or target in obj.get("keywords", [])):
                found_steps = True
                break
        
        if not found_steps:
            self.player.send_message("You don't see any steps here to scrub.")
            return

        self.player.send_message("You get down on your hands and knees and scrub the mud from the pristine marble steps.")
        self.player.send_message("It is humbling work, but the stone shines white once more.")
        
        # Update Counter
        self.player.quest_counters["scrubbed_steps"] = self.player.quest_counters.get("scrubbed_steps", 0) + 1
        set_action_roundtime(self.player, 6.0, rt_type="hard")


@VerbRegistry.register(["focus", "adjust"])
class Focus(BaseVerb):
    """
    FOCUS <prism>
    Quest: Focus the Central Prism.
    """
    def execute(self):
        if check_action_roundtime(self.player, action_type="other"): return
        
        target = " ".join(self.args).lower()
        
        # Find Prism
        found_prism = False
        for obj in self.room.objects:
            if "prism" in obj.get("keywords", []) and (target == "prism" or target in obj.get("keywords", [])):
                found_prism = True
                break
                
        if not found_prism:
            self.player.send_message("There is no prism here to focus.")
            return

        self.player.send_message("You carefully adjust the angle of the giant crystal prism...")
        
        # Simple check: Can only focus during the day
        from mud_backend.core.game_loop import environment
        if "night" in environment.current_time_of_day:
             self.player.send_message("There is no sunlight to focus right now.")
             return

        self.player.send_message("The beam of sunlight aligns perfectly with the altar, illuminating the holy symbols!")
        
        # Update Counter
        self.player.quest_counters["focused_prism"] = self.player.quest_counters.get("focused_prism", 0) + 1
        set_action_roundtime(self.player, 3.0, rt_type="hard")