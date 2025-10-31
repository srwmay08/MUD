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
        
        # --- NEW STAT FIELDS ---
        self.stats: Dict[str, int] = self.db_data.get("stats", {})
        self.current_stat_pool: List[int] = self.db_data.get("current_stat_pool", [])
        self.best_stat_pool: List[int] = self.db_data.get("best_stat_pool", [])
        self.stats_to_assign: List[int] = self.db_data.get("stats_to_assign", [])
        # --- END NEW STAT FIELDS ---

        self.strength = self.stats.get("STR", 10)
        self.agility = self.stats.get("AGI", 10)

        # --- FIELDS FOR CHARGEN AND DESCRIPTION ---
        self.game_state: str = self.db_data.get("game_state", "playing")
        self.chargen_step: int = self.db_data.get("chargen_step", 0)
        self.appearance: Dict[str, str] = self.db_data.get("appearance", {})
        
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
            "current_stat_pool": self.current_stat_pool,
            "best_stat_pool": self.best_stat_pool,
            "stats_to_assign": self.stats_to_assign,
            
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
        self.objects: List[Dict[str, Any]] = self.db_data.get("objects", []) 
        
        # --- NEW FIELD ---
        # Holds a dictionary of { "direction": "target_room_id" }
        self.exits: Dict[str, str] = self.db_data.get("exits", {})

    def to_dict(self) -> dict:
        """Converts room state to a dictionary ready for MongoDB update."""
        
        data = {
            **self.db_data,
            "room_id": self.room_id,
            "name": self.name,
            "description": self.description,
            "unabsorbed_social_exp": self.unabsorbed_social_exp,
            "objects": self.objects,
            "exits": self.exits, # --- ADDED ---
        }
        
        if self._id:
            data["_id"] = self._id
        return data

    def __repr__(self):
        return f"<Room: {self.name}>"