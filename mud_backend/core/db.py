# core/db.py
from typing import TYPE_CHECKING
from pymongo import MongoClient
from pymongo.errors import ConnectionError, OperationFailure

# Import the Player object for type hinting without circular dependency
if TYPE_CHECKING:
    from .game_objects import Player

# --- CONFIGURATION ---
# IMPORTANT: Use your actual MongoDB connection string here.
# Assuming a local MongoDB server running on the default port.
MONGO_URI = "mongodb://localhost:27017/" 
DATABASE_NAME = "MUD_DEV"
# ---------------------

# Global client and database object
client: Optional[MongoClient] = None
db = None

def get_db():
    """Initializes and returns the MongoDB database object."""
    global client, db
    if db is None:
        try:
            # Attempt to connect to MongoDB with a timeout
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            # The ismaster command confirms a connection quickly
            client.admin.command('ismaster') 
            db = client[DATABASE_NAME]
            print(f"[DB INIT] Connected to MongoDB database: {DATABASE_NAME}")
            
            # Populate the database with initial data if it's empty
            ensure_initial_data()
            
        except (ConnectionError, OperationFailure) as e:
            print(f"[DB ERROR] Could not connect to MongoDB (using mock data): {e}")
            db = None # Keep db as None so the functions use the mock fallback
            
    return db

def ensure_initial_data():
    """Ensures base entities (like the starting room and a test player) exist."""
    database = get_db()
    if database is None:
        return

    # 1. Rooms (We use 'room_id' as the unique key instead of MongoDB's '_id')
    if database.rooms.count_documents({}) == 0:
        database.rooms.insert_many([
            {
                "room_id": "town_square", 
                "name": "The Great Town Square", 
                "description": "A bustling place with a magnificent fountain in the center."
            },
            {
                "room_id": "north_gate", 
                "name": "Northern City Gate", 
                "description": "The massive iron gates leading out of the city stand before you."
            }
        ])
        print("[DB INIT] Inserted initial room data.")
        
    # 2. Test Player
    if database.players.count_documents({"name": "Alice"}) == 0:
        database.players.insert_one(
            {
                "name": "Alice", 
                "current_room_id": "town_square", 
                "level": 5,
                "gold": 100
            }
        )
        print("[DB INIT] Inserted test player 'Alice'.")


def fetch_player_data(player_name: str) -> dict:
    """Fetches player data from the 'players' collection or returns mock data."""
    database = get_db()
    if database is None:
        # Mock data fallback
        if player_name == "Alice":
            return {"name": "Alice", "current_room_id": "town_square", "level": 5}
        return {}

    player_data = database.players.find_one({"name": player_name})
    return player_data if player_data else {}


def fetch_room_data(room_id: str) -> dict:
    """Fetches room data from the 'rooms' collection or returns mock data."""
    database = get_db()
    if database is None:
        # Mock data fallback
        if room_id == "town_square":
            return {"id": "town_square", "name": "The Great Town Square", "description": "A bustling place with a fountain."}
        return {}
    
    room_data = database.rooms.find_one({"room_id": room_id})
    
    if room_data is None:
        # Return a default "void" room if a requested room_id is not found
        return {"room_id": "void", "name": "The Void", "description": "Nothing but endless darkness here."}
        
    return room_data


def save_game_state(player: 'Player'):
    """Saves player state back to the 'players' collection."""
    database = get_db()
    if database is None:
        print(f"\n[DB SAVE MOCK] Player {player.name} state saved (Mock).")
        return

    player_data = player.to_dict()
    
    # Update/Insert operation (upsert=True)
    result = database.players.update_one(
        {"name": player.name}, # Query: Find player by name
        {"$set": player_data}, # Update: Set all fields from player_data
        upsert=True            # Option: Insert if no document is found
    )
    
    if result.upserted_id:
        # If a new document was inserted, update the Player object with the new _id
        player._id = result.upserted_id
        print(f"\n[DB SAVE] Player {player.name} created with ID: {player._id}")
    else:
        print(f"\n[DB SAVE] Player {player.name} state updated.")

# Initialize the connection when the module first loads
get_db()