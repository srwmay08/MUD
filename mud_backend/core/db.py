# core/db.py
import socket 
from typing import TYPE_CHECKING, Optional
from pymongo import MongoClient
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError 

# Import the Player and Room object for type hinting
if TYPE_CHECKING:
    from .game_objects import Player, Room # Added Room

# --- CONFIGURATION ---
MONGO_URI = "mongodb://localhost:27017/" 
DATABASE_NAME = "MUD_Dev"  
# ---------------------

# Global client and database object
client: Optional[MongoClient] = None
db = None

def get_db():
    """Initializes and returns the MongoDB database object."""
    global client, db 
    if db is None:
        try:
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            client.admin.command('ismaster') 
            db = client[DATABASE_NAME]
            
            print(f"[DB INIT] Connected to MongoDB database: {DATABASE_NAME}")
            
            ensure_initial_data()
            
        except (socket.error, ServerSelectionTimeoutError, OperationFailure) as e:
            print(f"[DB ERROR] Could not connect to MongoDB (using mock data): {e}")
            db = None
            
    return db

def ensure_initial_data():
    """Ensures base entities exist."""
    database = get_db()
    if database is None:
        return

    # 1. Rooms
    if database.rooms.count_documents({"room_id": "well_bottom"}) == 0:
        database.rooms.insert_many([
            # UPDATED: Town Square now includes the 'well' object for LOOK/CLIMB
            {
                "room_id": "town_square", 
                "name": "The Great Town Square", 
                "description": "A bustling place with a magnificent fountain in the center. A stone well stands near the eastern corner, with a thick, wet rope disappearing into the darkness.",
                "unabsorbed_social_exp": 100,
                "objects": [ # NEW OBJECT LIST
                    {
                        "name": "fountain", 
                        "description": "The fountain depicts the Goddess of Wealth pouring endless gold into the city. Its water is cool and clear."
                    },
                    {
                        "name": "well",
                        "description": "A weathered stone well. You can see a dark, winding rope tied to the lip, leading down. You could probably **CLIMB** the rope.",
                        "verbs": ["CLIMB"],
                        "target_room": "well_bottom"
                    }
                ]
            },
            {
                "room_id": "north_gate", 
                "name": "Northern City Gate", 
                "description": "The massive iron gates leading out of the city stand before you.",
                "unabsorbed_social_exp": 0
            },
            # NEW: Well Bottom Room
            {
                "room_id": "well_bottom", 
                "name": "The Bottom of the Well", 
                "description": "It is dark and cramped down here. The air is damp and smells of stagnant water and mildew. A monster is stirring in the corner!",
                "unabsorbed_social_exp": 0,
                "objects": [
                    {
                        "name": "rope",
                        "description": "A thick, wet rope leads back up to the town square. You can **CLIMB** back up.",
                        "verbs": ["CLIMB"],
                        "target_room": "town_square"
                    }
                ]
            }
        ])
        print("[DB INIT] Inserted initial room data.")
        
    # 2. Test Player
    if database.players.count_documents({"name": "Alice"}) == 0:
        database.players.insert_one(
            {
                "name": "Alice", 
                "current_room_id": "town_square", 
                "level": 1, # Changed from 5 for new players
                "experience": 0,
                "strength": 12, # NEW STAT
                "agility": 15,  # NEW STAT
                "gold": 100
            }
        )
        print("[DB INIT] Inserted test player 'Alice'.")


def fetch_player_data(player_name: str) -> dict:
    """Fetches player data from the 'players' collection or returns mock data."""
    database = get_db()
    if database is None:
        # Mock data fallback (Updated to include new stats)
        if player_name == "Alice":
            return {"name": "Alice", "current_room_id": "town_square", "level": 1, "experience": 0, "strength": 12, "agility": 15}
        return {}

    player_data = database.players.find_one({"name": player_name})
    return player_data if player_data else {}


def fetch_room_data(room_id: str) -> dict:
    """Fetches room data from the 'rooms' collection or returns mock data."""
    database = get_db()
    if database is None:
        # Mock data fallback (Updated)
        if room_id == "town_square":
            return {
                "room_id": "town_square", 
                "name": "The Great Town Square", 
                "description": "A bustling place with a magnificent fountain in the center. A stone well stands near the eastern corner.",
                "unabsorbed_social_exp": 100,
                "objects": [{"name": "well", "description": "A well. You could CLIMB down."}]
            }
        return {}
    
    room_data = database.rooms.find_one({"room_id": room_id})
    
    if room_data is None:
        return {"room_id": "void", "name": "The Void", "description": "Nothing but endless darkness here."}
        
    return room_data


def save_game_state(player: 'Player'):
    """Saves player state back to the 'players' collection."""
    database = get_db()
    if database is None:
        print(f"\n[DB SAVE MOCK] Player {player.name} state saved (Mock).")
        return

    player_data = player.to_dict()
    
    result = database.players.update_one(
        {"name": player.name}, 
        {"$set": player_data}, 
        upsert=True            
    )
    
    if result.upserted_id:
        player._id = result.upserted_id
        print(f"\n[DB SAVE] Player {player.name} created with ID: {player._id}")
    else:
        print(f"\n[DB SAVE] Player {player.name} state updated.")

def save_room_state(room: 'Room'):
    """Saves room state back to the 'rooms' collection."""
    database = get_db()
    if database is None:
        print(f"\n[DB SAVE MOCK] Room {room.name} state saved (Mock).")
        return

    room_data = room.to_dict()
    
    # Update operation on room using its unique room_id
    database.rooms.update_one(
        {"room_id": room.room_id}, 
        {"$set": room_data},       
        upsert=True
    )
    print(f"\n[DB SAVE] Room {room.name} state updated.")

get_db()