# mud_backend/verbs/assess.py
from mud_backend.verbs.base_verb import BaseVerb

class Assess(BaseVerb):
    """
    ASSESS <item|furnace>
    Gives mechanical feedback on crafting items.
    Shows detailed stats based on Mining/Smithing skill.
    """
    def execute(self):
        if not self.args:
            self.player.send_message("Assess what?")
            return
            
        target = " ".join(self.args).lower()
        
        # --- Assess Furnace ---
        for obj in self.room.objects:
            if target in obj.get("keywords", []) and "state" in obj:
                state = obj["state"]
                temp = state.get("temp", 20)
                fuel = state.get("fuel", 0)
                slag = state.get("slag", 0)
                
                # Determine Player Skill Level
                # Using 'mining' as a proxy for metallurgy knowledge here
                skill_rank = self.player.skills.get("mining", 0)
                
                self.player.send_message(f"--- Assessment: {obj['name']} ---")
                
                # Temperature Analysis
                if skill_rank < 10:
                    # Novice View
                    if temp < 100: self.player.send_message("Heat: Cold")
                    elif temp < 600: self.player.send_message("Heat: Warm")
                    elif temp < 1000: self.player.send_message("Heat: Hot")
                    else: self.player.send_message("Heat: Dangerously Hot")
                else:
                    # Expert View
                    self.player.send_message(f"Temperature: {temp}°C")
                    if temp > 1085: self.player.send_message("   (Sufficient to melt copper)")
                
                # Fuel Analysis
                if skill_rank < 5:
                    fuel_desc = "Empty" if fuel <= 0 else "Some fuel remains"
                    self.player.send_message(f"Fuel: {fuel_desc}")
                else:
                    self.player.send_message(f"Fuel Level:  {int(fuel)} units")

                # Airflow
                self.player.send_message(f"Air Flow:    {state.get('air_flow')}%")
                
                # Slag Warning (High Skill)
                if skill_rank >= 15 and slag > 20:
                    self.player.send_message("**WARNING**: You hear the gurgling of molten waste. The furnace needs tapping!")
                    
                return
        
        self.player.send_message("You don't see that here to assess.")