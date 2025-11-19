# mud_backend/verbs/smelting.py
import random
import time
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.verbs.item_actions import _get_item_data, _find_item_in_hands
from typing import Dict, Any

def _find_furnace(room) -> Dict[str, Any] | None:
    for obj in room.objects:
        if "furnace" in obj.get("keywords", []) and "state" in obj:
            return obj
    return None

# ... (Crush, Wash, Charge classes remain the same) ...

class Charge(BaseVerb):
    """CHARGE FURNACE WITH [ORE/COAL/FLUX]"""
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        
        if len(self.args) < 2:
            self.player.send_message("Usage: CHARGE FURNACE WITH [ORE|COAL|FLUX]")
            return
            
        furnace = _find_furnace(self.room)
        if not furnace:
            self.player.send_message("There is no furnace here.")
            return

        target_material = self.args[-1].lower() 
        item_ref, slot = _find_item_in_hands(self.player, target_material)
        
        if not item_ref:
            self.player.send_message(f"You aren't holding any {target_material}.")
            return
            
        state = furnace["state"]
        item_data = _get_item_data(item_ref, self.world.game_items)
        
        if target_material == "coal":
            state["fuel"] = state.get("fuel", 0) + 20
            self.player.send_message("You shovel coal into the furnace. It hisses as it hits the heat.")
        elif target_material == "flux":
            state["flux"] = state.get("flux", 0) + 10
            self.player.send_message("You sprinkle flux into the mix. It crackles and sparks.")
        elif target_material == "ore":
            if item_data.get("name") == "washed copper ore":
                state["ore"] = state.get("ore", 0) + 10
                self.player.send_message("You dump the washed ore into the crucible.")
            else:
                self.player.send_message("That ore isn't ready for smelting. It must be crushed and washed.")
                return
        else:
            self.player.send_message("You can't charge the furnace with that.")
            return

        self.player.worn_items[slot] = None
        _set_action_roundtime(self.player, 4.0)

class Bellow(BaseVerb):
    """Pumps air into the furnace."""
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        
        furnace = _find_furnace(self.room)
        if not furnace:
            self.player.send_message("There is no furnace here.")
            return
            
        state = furnace["state"]
        fuel = state.get("fuel", 0)
        temp = state.get("temp", 20)

        if fuel > 0:
            state["temp"] += 50
            state["fuel"] -= 2
            if temp > 1000:
                self.player.send_message("You pump the bellows. A jet of white flame roars upwards!")
            else:
                self.player.send_message("You pump the bellows, feeding oxygen to the coals. They brighten instantly.")
        else:
            self.player.send_message("The bellows wheeze with a hollow sound. The fire is starving for fuel.")
            
        _set_action_roundtime(self.player, 3.0)

class Vent(BaseVerb):
    """Adjusts furnace airflow."""
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        
        furnace = _find_furnace(self.room)
        if not furnace: return
        
        state = furnace["state"]
        current = state.get("air_flow", 50)
        
        if "open" in self.args:
            state["air_flow"] = min(100, current + 25)
            self.player.send_message("You open the damper. You hear the draft rushing through the chimney.")
        elif "close" in self.args:
            state["air_flow"] = max(0, current - 25)
            self.player.send_message("You close the damper, stifling the airflow.")
        else:
            self.player.send_message(f"Vents are currently at {current}%. Usage: VENT OPEN or VENT CLOSE")
        
        _set_action_roundtime(self.player, 2.0)

class Tap(BaseVerb):
    """Releases slag."""
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        
        furnace = _find_furnace(self.room)
        if not furnace: return
        
        state = furnace["state"]
        slag = state.get("slag", 0)
        
        if slag > 10:
            self.player.send_message("You knock the clay plug loose. A stream of glowing, viscous slag vomits forth onto the floor!")
            state["slag"] = 0
        elif slag > 0:
            self.player.send_message("You open the tap. A small trickle of grey impurities drips out.")
            state["slag"] = 0
        else:
            self.player.send_message("You open the tap, but only hot air escapes. The melt is clean.")
            
        _set_action_roundtime(self.player, 6.0)

# ... (Extract and Shingle remain largely the same, or can be tweaked similarly) ...
class Extract(BaseVerb):
    """Pulls out the bloom."""
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        furnace = _find_furnace(self.room)
        if not furnace: return
        
        state = furnace["state"]
        metal = state.get("ready_metal", 0)
        
        if metal < 10:
            self.player.send_message("You peek inside. The ore hasn't reduced to a bloom yet.")
            return
            
        bloom = {
            "name": "a glowing bloom",
            "description": "A spongy mass of hot metal and slag, pulsing with heat.",
            "keywords": ["bloom", "glowing", "metal"],
            "is_item": True,
            "verbs": ["GET", "LOOK", "SHINGLE"],
            "temp": state["temp"],
            "mass": metal,
            "quality": "rough",
            "uid": f"bloom_{int(time.time())}"
        }
        
        self.room.objects.append(bloom)
        self.world.save_room(self.room)
        
        state["ready_metal"] = 0
        state["temp"] -= 500 
        
        self.player.send_message("Shielding your face from the heat, you tear open the door and drag the glowing, spongy bloom onto the floor!")
        _set_action_roundtime(self.player, 10.0)

class Shingle(BaseVerb):
    """Hammers bloom into ingot."""
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        
        bloom = None
        for obj in self.room.objects:
            if obj.get("name") == "a glowing bloom":
                bloom = obj
                break
        if not bloom:
            self.player.send_message("There is no bloom here to shingle.")
            return
            
        has_hammer = False
        for slot in ["mainhand", "offhand"]:
            item_ref = self.player.worn_items.get(slot)
            if item_ref:
                data = _get_item_data(item_ref, self.world.game_items)
                if data.get("tool_type") == "hammer":
                    has_hammer = True
        if not has_hammer:
            self.player.send_message("You need a hammer to shingle the bloom.")
            return

        # Success
        ingot = {
            "name": "a copper ingot",
            "description": "A solid bar of copper, radiating warmth.",
            "keywords": ["ingot", "copper"],
            "is_item": True,
            "verbs": ["GET", "LOOK", "TAKE"],
            "temp": bloom.get("temp", 1000) - 200,
            "quality": "standard",
            "uid": f"ingot_{int(time.time())}"
        }
        
        self.room.objects.remove(bloom)
        self.room.objects.append(ingot)
        self.world.save_room(self.room)
        
        self.player.send_message("Sparks fly as you strike the bloom! Molten slag squirts out as you compact the spongy metal into a solid bar.")
        _set_action_roundtime(self.player, 5.0)