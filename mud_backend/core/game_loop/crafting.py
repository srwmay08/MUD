# mud_backend/core/game_loop/crafting.py
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

# Smelting Constants
MAX_TEMP = 2000
AMBIENT_TEMP = 20
FUEL_BURN_RATE = 5
TEMP_GAIN_PER_FUEL = 10
TEMP_LOSS_RATE = 2 

def _get_furnace_atmosphere(temp: int, slag: int, fuel: int) -> str:
    """Generates a flavor string based on furnace state."""
    if temp < 200:
        if fuel > 0: return "smolders with a thick, dark smoke."
        return "sits cold and dark."
    elif temp < 600:
        return "glows with a dull, sullen red light."
    elif temp < 1000:
        return "burns steadily, the coals glowing a bright cherry red."
    elif temp < 1400:
        base = "roars with a fierce orange heat"
        if slag > 20: base += ", and a gurgling sound comes from deep within"
        return base + "."
    else:
        return "emits a blinding white light and a deafening roar like a captured dragon!"

def process_crafting_stations(world: 'World', broadcast_callback):
    """
    Iterates through all rooms and processes any active crafting stations.
    """
    for room_id, room_data in world.game_rooms.items():
        if not room_data or "objects" not in room_data:
            continue
            
        for obj in room_data["objects"]:
            if obj.get("keywords") and "furnace" in obj.get("keywords") and "state" in obj:
                _process_furnace_tick(obj, room_id, broadcast_callback)

def _process_furnace_tick(furnace: dict, room_id: str, broadcast_callback):
    state = furnace["state"]
    
    # 1. Fuel & Temp Logic
    fuel = state.get("fuel", 0)
    temp = state.get("temp", AMBIENT_TEMP)
    air_flow = state.get("air_flow", 50) 
    
    burn_rate = FUEL_BURN_RATE * (0.5 + (air_flow / 100.0))
    
    if fuel > 0:
        consumed = min(fuel, burn_rate)
        state["fuel"] -= consumed
        efficiency = 0.2 + (air_flow / 125.0) 
        temp_gain = consumed * TEMP_GAIN_PER_FUEL * efficiency
        temp += temp_gain
    
    # Cooling Logic
    cooling = TEMP_LOSS_RATE * (1.0 + (air_flow / 50.0))
    cooling += (temp - AMBIENT_TEMP) * 0.05
    temp -= cooling
    state["temp"] = max(AMBIENT_TEMP, min(MAX_TEMP, int(temp)))
    
    # 2. Smelting Logic
    if temp > 1000 and state.get("ore", 0) > 0:
        flux = state.get("flux", 0)
        ore = state.get("ore", 0)
        
        conversion_amt = 10
        if ore >= conversion_amt:
            state["ore"] -= conversion_amt
            
            slag_generated = 5 
            if flux >= conversion_amt:
                state["flux"] -= conversion_amt
                slag_generated = 2 
            
            state["slag"] = state.get("slag", 0) + slag_generated
            state["ready_metal"] = state.get("ready_metal", 0) + conversion_amt

    # 3. Ambient Feedback (Dynamic)
    # 10% chance per tick to emit flavor text if the furnace is active
    if temp > 100 and random.random() < 0.10:
        flavor_text = _get_furnace_atmosphere(state["temp"], state.get("slag", 0), state.get("fuel", 0))
        broadcast_callback(room_id, f"The {furnace['name']} {flavor_text}", "ambient")