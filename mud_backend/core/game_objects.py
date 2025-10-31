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

        # NEW: Player Stats and EXP
        self.experience = self.db_data.get("experience", 0) 
        self.level = self.db_data.get("level", 1)         
        self.strength = self.db_data.get("strength", 10)   # NEW
        self.agility = self.db_data.get("agility", 10)     # NEW

    def send_message(self, message: str):
        """Adds a message to the player's output queue."""
        self.messages.append(message)

    def gain_exp(self, amount: int):
        """Adds experience and checks for leveling up."""
        self.experience += amount
        self.send_message(f"You absorb {amount} experience!")
        # Basic leveling logic placeholder
        if self.experience >= self.level * 1000:
            self.level += 1
            self.send_message(f"**CONGRATULATIONS! You have advanced to Level {self.level}!**")

    def to_dict(self) -> dict:
        """Converts player state to a dictionary ready for MongoDB insertion/update."""
        # Include all relevant stats in the saved data
        data = {
            "name": self.name,
            "current_room_id": self.current_room_id,
            "experience": self.experience, 
            "level": self.level,           
            "strength": self.strength,     # NEW
            "agility": self.agility,       # NEW
            **self.db_data 
        }
        # Ensure name and current_room_id overwrite any older values from db_data
        data["name"] = self.name 
        data["current_room_id"] = self.current_room_id
        
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
        # NEW: Custom objects list for look and interaction
        self.objects: List[Dict[str, Any]] = self.db_data.get("objects", []) 

    def to_dict(self) -> dict:
        """Converts room state to a dictionary ready for MongoDB update."""
        data = {
            "room_id": self.room_id,
            "name": self.name,
            "description": self.description,
            "unabsorbed_social_exp": self.unabsorbed_social_exp,
            "objects": self.objects, # NEW
            **self.db_data
        }
        if self._id:
            data["_id"] = self._id
        return data

    def __repr__(self):
        return f"<Room: {self.name}>"