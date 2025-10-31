# core/game_objects.py
from typing import Optional, List, Dict, Any
# Import Dict and Any for better type hinting of the room objects list

class Player:
    def __init__(self, name: str, current_room_id: str, db_data: Optional[dict] = None):
        self.name = name
        self.current_room_id = current_room_id
        self.db_data = db_data if db_data is not None else {}
        self.messages = [] # For storing output to send to the client
        
        # MongoDB specific field to store the primary key
        self._id = self.db_data.get("_id") 

        # Player Stats (Old)
        self.experience = self.db_data.get("experience", 0) 
        self.level = self.db_data.get("level", 1)         
        
        # --- MODIFIED STAT FIELDS ---
        # self.stats will hold the FINAL assigned stats (e.g., {"STR": 90, "CON": 75, ...})
        self.stats: Dict[str, int] = self.db_data.get("stats", {})
        
        # RENAMED: This now stores the best *list* of rolls, not just the total
        self.best_stat_pool: List[int] = self.db_data.get("best_stat_pool", [])
        # --- END MODIFIED STAT FIELDS ---


        # DEPRECATED: These are now drawn from the self.stats dictionary
        self.strength = self.stats.get("STR", 10)
        self.agility = self.stats.get("AGI", 10)


        # --- FIELDS FOR CHARGEN AND DESCRIPTION ---
        
        # game_state: "playing" or "chargen"
        self.game_state: str = self.db_data.get("game_state", "playing")
        
        # Which chargen question they are on
        self.chargen_step: int = self.db_data.get("chargen_step", 0)
        
        # A dictionary to store all appearance data
        self.appearance: Dict[str, str] = self.db_data.get("appearance", {})
        
        # --- END NEW FIELDS ---

    def send_message(self, message: str):
        """Adds a message to the player's output queue."""
        self.messages.append(message)

    def gain_exp(self, amount: int):
        """Adds experience and checks for leveling up."""
        self.experience += amount
        self.send_message(f"You absorb {amount} experience!")
        if self.experience >= self.level * 1000:
            self.level += 1
            self.send_message(f"**CONGRATULATIONS! You have advanced to Level {self.level}!**")

    def to_dict(self) -> dict:
        """Converts player state to a dictionary ready for MongoDB insertion/update."""
        
        # Update strength/agility from the stats dict before saving
        self.strength = self.stats.get("STR", self.strength)
        self.agility = self.stats.get("AGI", self.agility)
        
        data = {
            **self.db_data,
            
            "name": self.name,
            "current_room_id": self.current_room_id,
            "experience": self.experience, 
            "level": self.level,           
            "strength": self.strength,
            "agility": self.agility,
            
            # --- FIELDS TO SAVE ---
            "stats": self.stats,
            "best_stat_pool": self.best_stat_pool, # Was best_stat_roll_total
            # --- END FIELDS TO SAVE ---
            
            "game_state": self.game_state,
            "chargen_step": self.chargen_step,
            "appearance": self.appearance,
        }
        
        if self._id:
            data["_id"] = self._id
            
        return data

    def __repr__(self):
        return f"<Player: {self.name}>"

class Room:
    def __init__(self, room_id: str, name: str, description: str, db_data: Optional[dict] = None):
        self.room_id = room_id
        self.name = name
        self.description = description
        self.db_data = db_data if db_data is not None else {}
        
        self._id = self.db_data.get("_id") 
        
        self.unabsorbed_social_exp = self.db_data.get("unabsorbed_social_exp", 0)
        # Custom objects list for look and interaction
        self.objects: List[Dict[str, Any]] = self.db_data.get("objects