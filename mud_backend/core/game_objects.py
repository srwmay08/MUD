# core/game_objects.py

class Player:
    def __init__(self, name, current_room_id, db_data=None):
        self.name = name
        self.current_room_id = current_room_id
        self.db_data = db_data if db_data is not None else {}
        self.messages = [] # For storing output to send to the client

    def send_message(self, message: str):
        """Adds a message to the player's output queue."""
        self.messages.append(message)

    def __repr__(self):
        return f"<Player: {self.name}>"

class Room:
    def __init__(self, room_id, name, description, db_data=None):
        self.room_id = room_id
        self.name = name
        self.description = description
        self.db_data = db_data if db_data is not None else {}

    def __repr__(self):
        return f"<Room: {self.name}>"