# core/game_objects.py
from typing import Optional

class Player:
    def __init__(self, name: str, current_room_id: str, db_data: Optional[dict] = None):
        self.name = name
        self.current_room_id = current_room_id
        self.db_data = db_data if db_data is not None else {}
        self.messages = [] # For storing output to send to the client
        
        # MongoDB specific field to store the primary key
        self._id = self.db_data.get("_id") 

    def send_message(self, message: str):
        """Adds a message to the player's output queue."""
        self.messages.append(message)

    def to_dict(self) -> dict:
        """Converts player state to a dictionary ready for MongoDB insertion/update."""
        # Start with all current attributes and merge in existing db_data
        data = {
            "name": self.name,
            "current_room_id": self.current_room_id,
            **self.db_data 
        }
        # Ensure name and current_room_id overwrite any older values from db_data
        data["name"] = self.name 
        data["current_room_id"] = self.current_room_id
        
        # The _id field is needed for MongoDB to update an existing record.
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
        # MongoDB specific field
        self._id = self.db_data.get("_id") 

    def __repr__(self):
        return f"<Room: {self.name}>"