# mud_backend/verbs/smelting.py
import random
import time
import math
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.item_utils import get_item_data, find_item_in_inventory, find_item_in_hands
from typing import Dict, Any
from mud_backend.core import loot_system
from mud_backend import config
from mud_backend.core.registry import VerbRegistry

def _find_furnace(room) -> Dict[str, Any] | None:
    for obj in room.objects:
        if "furnace" in obj.get("keywords", []) and "state" in obj:
            return obj
    return None

METAL_PROPERTIES = {
    "copper": { "melt_temp": 1085, "crush_loot": "crushed_copper_ore_loot", "crushed_id": "crushed_copper_ore", "washed_id": "washed_copper_ore", "xp_mod": 1.0 },
    "iron": { "melt_temp": 1538, "crush_loot": "crushed_iron_ore_loot", "crushed_id": "crushed_iron_ore", "washed_id": "washed_iron_ore", "xp_mod": 1.5 }
}

@VerbRegistry.register(["crush"]) 
class Crush(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        
        has_hammer = False
        for slot in ["mainhand", "offhand"]:
            item_ref = self.player.worn_items.get(slot)
            if item_ref:
                data = get_item_data(item_ref, self.world.game_items)
                if data.get("tool_type") == "hammer":
                    has_hammer = True
                    break
        if not has_hammer:
            self.player.send_message("You need a hammer to crush ore.")
            return

        ore_ref, ore_slot = find_item_in_hands(self.player, self.world.game_items, "ore")
        if not ore_ref:
            self.player.send_message("You need to be holding ore to crush it.")
            return
        
        ore_data = get_item_data(ore_ref, self.world.game_items)
        material = ore_data.get("material")
        
        if not material or material not in METAL_PROPERTIES or ore_data.get("item_type") != "ore":
            self.player.send_message("You can only crush raw metal ore chunks (copper, iron).")
            return

        has_table = False
        for obj in self.room.objects:
            if "table" in obj.get("keywords", []):
                has_table = True
                break
        if not has_table:
            self.player.send_message("You need a sturdy table to crush ore on.")
            return

        metal_props = METAL_PROPERTIES[material]

        self.player.send_message(f"You smash the {material} ore with your hammer, reducing it to gravel.")
        self.player.worn_items[ore_slot] = metal_props["crushed_id"]
        
        loot_table_id = metal_props["crush_loot"]
        dropped_items = loot_system.generate_loot_from_table(self.world, loot_table_id)
        
        gem_found = False
        if dropped_items:
             for item_data in dropped_items: 
                 item_id = item_data.get("item_id")
                 if item_id:
                     self.player.inventory.append(item_id)
                     self.player.send_message(f"As the ore crumbles, {item_data['name']} falls out!")
                     gem_found = True

        nominal_xp = int(5 * metal_props["xp_mod"])
        if gem_found:
            nominal_xp += 5
            self.player.send_message("You feel a surge of excitement from the discovery!")

        if nominal_xp > 0:
            self.player.send_message(f"You have gained {nominal_xp} experience from crushing ore.")
            self.player.grant_experience(nominal_xp, source="smithing")

        _set_action_roundtime(self.player, 5.0)

@VerbRegistry.register(["wash"]) 
class Wash(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        
        ore_ref, ore_slot = find_item_in_hands(self.player, self.world.game_items, "ore")
        if not ore_ref:
            self.player.send_message("You need to be holding crushed ore to wash it.")
            return
            
        ore_data = get_item_data(ore_ref, self.world.game_items)
        material = ore_data.get("material")
        
        if not material or material not in METAL_PROPERTIES or ore_data.get("item_type") != "ore_gravel":
            self.player.send_message("That ore doesn't need washing (or hasn't been crushed yet).")
            return

        has_sink = False
        for obj in self.room.objects:
            if "sink" in obj.get("keywords", []):
                has_sink = True
                break
        if not has_sink:
            self.player.send_message("You need a sink or water source to wash the ore.")
            return

        metal_props = METAL_PROPERTIES[material]
        self.player.send_message("You thoroughly wash the dirt and grit from the ore.")
        self.player.worn_items[ore_slot] = metal_props["washed_id"]
        
        xp = int(5 * metal_props["xp_mod"])
        self.player.send_message(f"You have gained {xp} experience from washing ore.")
        self.player.grant_experience(xp, source="smithing")
        
        _set_action_roundtime(self.player, 8.0)

@VerbRegistry.register(["charge"]) 
class Charge(BaseVerb):
    """CHARGE FURNACE WITH [ORE/COAL/FLUX/WEAPON]"""
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        if len(self.args) < 2:
            self.player.send_message("Usage: CHARGE FURNACE WITH [ORE|COAL|FLUX|WEAPON]")
            return
            
        furnace = _find_furnace(self.room)
        if not furnace:
            self.player.send_message("There is no furnace here.")
            return

        target_arg = self.args[-1].lower()
        item_ref = None
        slot = None
        
        if target_arg in ["ore", "coal", "flux"]:
             item_ref, slot = find_item_in_hands(self.player, self.world.game_items, target_arg)
        
        if not item_ref:
             item_ref, slot = find_item_in_hands(self.player, self.world.game_items, target_arg) 

        if not item_ref:
            self.player.send_message(f"You aren't holding '{target_arg}'.")
            return
            
        state = furnace["state"]
        item_data = get_item_data(item_ref, self.world.game_items)
        item_type = item_data.get("item_type")
        item_material = item_data.get("material")
        current_metal_type = state.get("metal_type")

        if "coal" in item_data.get("keywords", []):
            state["fuel"] = state.get("fuel", 0) + 10
            self.player.send_message("You shovel coal into the furnace.")
        elif item_type == "flux":
            state["flux"] = state.get("flux", 0) + 5
            self.player.send_message("You sprinkle flux into the mix.")
        elif item_type == "ore_clean":
            if current_metal_type and current_metal_type != item_material and state.get("ready_metal", 0) > 0:
                self.player.send_message(f"The furnace currently contains {current_metal_type}. You cannot mix {item_material} in!")
                return
            if state.get("ready_metal", 0) == 0:
                state["metal_type"] = item_material
            state["ore"] = state.get("ore", 0) + 10
            self.player.send_message(f"You charge the furnace with washed {item_material} ore.")
        elif item_type == "weapon" and item_material in METAL_PROPERTIES:
            if current_metal_type and current_metal_type != item_material and state.get("ready_metal", 0) > 0:
                self.player.send_message(f"The furnace currently contains {current_metal_type}. You cannot mix {item_material} in!")
                return
            if state.get("ready_metal", 0) == 0:
                state["metal_type"] = item_material
            metal_yield = 5
            state["ready_metal"] = state.get("ready_metal", 0) + metal_yield
            state["slag"] = state.get("slag", 0) + 5
            self.player.send_message(f"You toss the {item_data['name']} into the furnace to melt it down.")
        else:
            self.player.send_message("You can't charge the furnace with that.")
            return

        self.player.worn_items[slot] = None
        self.player.grant_experience(2, source="smithing")
        _set_action_roundtime(self.player, 4.0)

@VerbRegistry.register(["bellow"]) 
class Bellow(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        furnace = _find_furnace(self.room)
        if not furnace:
            self.player.send_message("There is no furnace here.")
            return
        self.player.send_message("You pump the bellows, feeding air to the fire!")
        state = furnace["state"]
        if state.get("fuel", 0) > 0:
            state["temp"] += 50
            state["fuel"] -= 2
        else:
            self.player.send_message("The bellows wheeze, but there is no fuel to burn.")
        _set_action_roundtime(self.player, 3.0)

@VerbRegistry.register(["vent"]) 
class Vent(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        furnace = _find_furnace(self.room)
        if not furnace: return
        state = furnace["state"]
        current = state.get("air_flow", 50)
        if "open" in self.args:
            state["air_flow"] = min(100, current + 25)
            self.player.send_message("You open the vents to increase airflow.")
        elif "close" in self.args:
            state["air_flow"] = max(0, current - 25)
            self.player.send_message("You close the vents to stifle the fire.")
        else:
            self.player.send_message(f"Vents are currently at {current}%. Usage: VENT OPEN or VENT CLOSE")
        _set_action_roundtime(self.player, 2.0)

@VerbRegistry.register(["tap"]) 
class Tap(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        furnace = _find_furnace(self.room)
        if not furnace: return
        state = furnace["state"]
        slag = state.get("slag", 0)
        if slag > 0:
            self.player.send_message("You open the tap. Molten slag hisses as it flows out.")
            state["slag"] = 0
            self.player.send_message("You have gained 5 experience from maintaining the furnace.")
            self.player.grant_experience(5, source="smithing")
        else:
            self.player.send_message("You open the tap, but nothing comes out.")
        _set_action_roundtime(self.player, 6.0)

@VerbRegistry.register(["extract"]) 
class Extract(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        furnace = _find_furnace(self.room)
        if not furnace: return
        state = furnace["state"]
        metal = state.get("ready_metal", 0)
        metal_type = state.get("metal_type", "copper")
        props = METAL_PROPERTIES.get(metal_type, METAL_PROPERTIES["copper"])
        melt_temp = props["melt_temp"]
        current_temp = state.get("temp", 0)
        if current_temp < melt_temp:
             self.player.send_message(f"The {metal_type} hasn't melted yet! (Current: {current_temp}, Needed: {melt_temp})")
             return
        if metal < 50:
            self.player.send_message("There isn't enough metal (50 units needed) to extract a bloom yet.")
            return
        bloom = {
            "name": f"a glowing {metal_type} bloom",
            "description": f"A spongy mass of hot {metal_type} and slag.",
            "keywords": ["bloom", "glowing", "metal", metal_type],
            "is_item": True,
            "verbs": ["GET", "LOOK", "SHINGLE"],
            "temp": state["temp"],
            "mass": 50,
            "quality": "rough",
            "material": metal_type,
            "uid": f"bloom_{int(time.time())}"
        }
        self.room.objects.append(bloom)
        self.world.save_room(self.room)
        state["ready_metal"] -= 50
        state["temp"] -= 500 
        if state["ready_metal"] <= 0:
            state["metal_type"] = None
            state["ready_metal"] = 0
        self.player.send_message(f"You tear open the furnace door and drag out a glowing {metal_type} bloom!")
        xp = int(10 * props["xp_mod"])
        self.player.send_message(f"You have gained {xp} experience from extracting the bloom.")
        self.player.grant_experience(xp, source="smithing")
        _set_action_roundtime(self.player, 10.0)

@VerbRegistry.register(["shingle"]) 
class Shingle(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        bloom = None
        for obj in self.room.objects:
            if "bloom" in obj.get("keywords", []):
                bloom = obj
                break
        if not bloom:
            self.player.send_message("There is no bloom here to shingle.")
            return
        has_hammer = False
        for slot in ["mainhand", "offhand"]:
            item_ref = self.player.worn_items.get(slot)
            if item_ref:
                data = get_item_data(item_ref, self.world.game_items)
                if data.get("tool_type") == "hammer":
                    has_hammer = True
        if not has_hammer:
            self.player.send_message("You need a hammer to shingle the bloom.")
            return
        material = bloom.get("material", "copper")
        props = METAL_PROPERTIES.get(material, METAL_PROPERTIES["copper"])
        target_temp = props["melt_temp"] 
        bloom_temp = bloom.get("temp", 1000)
        temp_diff = abs(bloom_temp - target_temp)
        quality_str = "standard"
        base_xp = 10
        if temp_diff < 100:
            quality_str = "superior"
            base_xp = 25
        elif temp_diff < 200:
            quality_str = "good"
            base_xp = 15
        elif temp_diff >= 400:
            quality_str = "poor"
            base_xp = 5
        ingot = {
            "name": f"an {material} ingot",
            "description": f"A solid bar of {quality_str} quality {material}, still warm.",
            "keywords": ["ingot", material],
            "is_item": True,
            "verbs": ["GET", "LOOK", "TAKE"],
            "temp": bloom_temp - 200,
            "quality": quality_str,
            "material": material,
            "uid": f"ingot_{int(time.time())}"
        }
        self.room.objects.remove(bloom)
        self.room.objects.append(ingot)
        self.world.save_room(self.room)
        self.player.send_message(f"You strike the bloom repeatedly, squeezing out the slag and forging it into a {quality_str} {material} ingot.")
        final_xp = int(base_xp * props["xp_mod"])
        self.player.send_message(f"You have gained {final_xp} experience from forging the ingot.")
        self.player.grant_experience(final_xp, source="smithing")
        _set_action_roundtime(self.player, 5.0)