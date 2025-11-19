# mud_backend/verbs/smelting.py
import random
import time
import math
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.verbs.item_actions import _get_item_data, _find_item_in_hands
from typing import Dict, Any
from mud_backend.core import loot_system
from mud_backend import config

def _find_furnace(room) -> Dict[str, Any] | None:
    for obj in room.objects:
        if "furnace" in obj.get("keywords", []) and "state" in obj:
            return obj
    return None

class Crush(BaseVerb):
    """CRUSH ore on a worktable."""
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        
        # 1. Check for hammer
        has_hammer = False
        for slot in ["mainhand", "offhand"]:
            item_ref = self.player.worn_items.get(slot)
            if item_ref:
                data = _get_item_data(item_ref, self.world.game_items)
                if data.get("tool_type") == "hammer":
                    has_hammer = True
                    break
        if not has_hammer:
            self.player.send_message("You need a hammer to crush ore.")
            return

        # 2. Check for Ore in other hand
        ore_ref, ore_slot = _find_item_in_hands(self.player, "ore")
        if not ore_ref:
            self.player.send_message("You need to be holding ore to crush it.")
            return
        
        ore_data = _get_item_data(ore_ref, self.world.game_items)
        if ore_data.get("name") != "a chunk of copper ore":
            self.player.send_message("You can only crush raw copper ore chunks.")
            return

        # 3. Check for Table
        has_table = False
        for obj in self.room.objects:
            if "table" in obj.get("keywords", []):
                has_table = True
                break
        if not has_table:
            self.player.send_message("You need a sturdy table to crush ore on.")
            return

        # Success
        self.player.send_message("You smash the ore with your hammer, reducing it to gravel.")
        self.player.worn_items[ore_slot] = "crushed_copper_ore" # Replace item ID
        
        # --- Loot Table Logic for Gems ---
        loot_table_id = "crushed_copper_ore_loot"
        
        dropped_items = loot_system.generate_loot_from_table(
            loot_table_id,
            self.world.game_loot_tables,
            self.world.game_items
        )
        
        gem_found = False
        if dropped_items:
             for item_id in dropped_items:
                 gem_data = self.world.game_items.get(item_id)
                 if gem_data:
                     self.player.inventory.append(item_id)
                     self.player.send_message(f"As the ore crumbles, {gem_data['name']} falls out!")
                     gem_found = True

        # --- XP Calculation ---
        # Base XP for crushing is small (1/20th scale = ~5 XP)
        nominal_xp = 5
        
        # Bonus XP for finding a gem
        if gem_found:
            nominal_xp += 5
            self.player.send_message("You feel a surge of excitement from the discovery!")

        if nominal_xp > 0:
            self.player.send_message(f"You have gained {nominal_xp} experience from crushing ore.")
            self.player.grant_experience(nominal_xp, source="smithing")

        _set_action_roundtime(self.player, 5.0)

class Wash(BaseVerb):
    """WASH crushed ore in a sink."""
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        
        ore_ref, ore_slot = _find_item_in_hands(self.player, "ore")
        if not ore_ref:
            self.player.send_message("You need to be holding crushed ore to wash it.")
            return
            
        ore_data = _get_item_data(ore_ref, self.world.game_items)
        if ore_data.get("name") != "crushed copper ore":
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

        self.player.send_message("You thoroughly wash the dirt and grit from the ore.")
        self.player.worn_items[ore_slot] = "washed_copper_ore"
        
        # --- XP Grant ---
        # Washing is a simple step, grant small XP
        self.player.send_message("You have gained 5 experience from washing ore.")
        self.player.grant_experience(5, source="smithing")
        
        _set_action_roundtime(self.player, 8.0)

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

        target_material = self.args[-1].lower() # "ore", "coal", "flux"
        item_ref, slot = _find_item_in_hands(self.player, target_material)
        
        if not item_ref:
            self.player.send_message(f"You aren't holding any {target_material}.")
            return
            
        # Logic to update furnace state
        state = furnace["state"]
        item_data = _get_item_data(item_ref, self.world.game_items)
        
        if target_material == "coal":
            state["fuel"] = state.get("fuel", 0) + 20
            self.player.send_message("You shovel coal into the furnace.")
        elif target_material == "flux":
            state["flux"] = state.get("flux", 0) + 10
            self.player.send_message("You sprinkle flux into the mix.")
        elif target_material == "ore":
            if item_data.get("name") == "washed copper ore":
                state["ore"] = state.get("ore", 0) + 10
                self.player.send_message("You charge the furnace with washed ore.")
            else:
                self.player.send_message("That ore isn't ready for smelting. It must be crushed and washed.")
                return
        else:
            self.player.send_message("You can't charge the furnace with that.")
            return

        # Remove item from hand
        self.player.worn_items[slot] = None
        
        # --- XP Grant ---
        # Loading the furnace is labor, grant very small XP
        self.player.grant_experience(2, source="smithing")
        
        _set_action_roundtime(self.player, 4.0)

class Bellow(BaseVerb):
    """Pumps air into the furnace."""
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        
        furnace = _find_furnace(self.room)
        if not furnace:
            self.player.send_message("There is no furnace here.")
            return
            
        self.player.send_message("You pump the bellows, feeding air to the fire!")
        
        # Mechanic: Immediate heat gain, but burns fuel
        state = furnace["state"]
        if state.get("fuel", 0) > 0:
            state["temp"] += 50
            state["fuel"] -= 2
        else:
            self.player.send_message("The bellows wheeze, but there is no fuel to burn.")
            
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
            self.player.send_message("You open the vents to increase airflow.")
        elif "close" in self.args:
            state["air_flow"] = max(0, current - 25)
            self.player.send_message("You close the vents to stifle the fire.")
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
        
        if slag > 0:
            self.player.send_message("You open the tap. Molten slag hisses as it flows out.")
            state["slag"] = 0
            
            # --- XP Grant ---
            # Successful maintenance
            self.player.send_message("You have gained 5 experience from maintaining the furnace.")
            self.player.grant_experience(5, source="smithing")
        else:
            self.player.send_message("You open the tap, but nothing comes out.")
            
        _set_action_roundtime(self.player, 6.0)

class Extract(BaseVerb):
    """Pulls out the bloom."""
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        furnace = _find_furnace(self.room)
        if not furnace: return
        
        state = furnace["state"]
        metal = state.get("ready_metal", 0)
        
        if metal < 10:
            self.player.send_message("There isn't enough metal to extract a bloom yet.")
            return
            
        # Create a Dynamic Item (Dict)
        bloom = {
            "name": "a glowing bloom",
            "description": "A spongy mass of hot metal and slag.",
            "keywords": ["bloom", "glowing", "metal"],
            "is_item": True,
            "verbs": ["GET", "LOOK", "SHINGLE"],
            "temp": state["temp"],
            "mass": metal,
            "quality": "rough",
            "uid": f"bloom_{int(time.time())}"
        }
        
        # Put in room
        self.room.objects.append(bloom)
        self.world.save_room(self.room)
        
        # Reset furnace metal
        state["ready_metal"] = 0
        state["temp"] -= 500 # Heat loss from opening door
        
        self.player.send_message("You tear open the furnace door and drag out a glowing bloom!")
        
        # --- XP Grant ---
        # Successful extraction is a key step
        self.player.send_message("You have gained 10 experience from extracting the bloom.")
        self.player.grant_experience(10, source="smithing")
        
        _set_action_roundtime(self.player, 10.0)

class Shingle(BaseVerb):
    """Hammers bloom into ingot."""
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        
        # 1. Check for bloom in room
        bloom = None
        for obj in self.room.objects:
            if obj.get("name") == "a glowing bloom":
                bloom = obj
                break
        if not bloom:
            self.player.send_message("There is no bloom here to shingle.")
            return
            
        # 2. Check for Hammer
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

        # --- Calculate Quality and XP ---
        bloom_temp = bloom.get("temp", 1000)
        # Ideal temp for Copper shingling/working ~1100
        temp_diff = abs(bloom_temp - 1100)
        
        quality_str = "standard"
        xp_gain = 20
        
        if temp_diff < 100:
            quality_str = "superior"
            xp_gain = 50
        elif temp_diff < 200:
            quality_str = "good"
            xp_gain = 35
        elif temp_diff >= 400:
            quality_str = "poor"
            xp_gain = 10
            
        # Success: Convert bloom to Ingot (Dynamic Item)
        ingot = {
            "name": "a copper ingot",
            "description": f"A solid bar of {quality_str} quality copper, still warm.",
            "keywords": ["ingot", "copper"],
            "is_item": True,
            "verbs": ["GET", "LOOK", "TAKE"],
            "temp": bloom_temp - 200,
            "quality": quality_str,
            "uid": f"ingot_{int(time.time())}"
        }
        
        self.room.objects.remove(bloom)
        self.room.objects.append(ingot)
        self.world.save_room(self.room)
        
        self.player.send_message(f"You strike the bloom repeatedly, squeezing out the slag and forging it into a {quality_str} ingot.")
        
        # --- XP Grant ---
        self.player.send_message(f"You have gained {xp_gain} experience from forging the ingot.")
        self.player.grant_experience(xp_gain, source="smithing")
        
        _set_action_roundtime(self.player, 5.0)