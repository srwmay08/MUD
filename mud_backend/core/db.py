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
    if database.rooms.count_documents({"room_id": "town_square"}) == 0:
        database.rooms.insert_many([
            {
                "room_id": "town_square", 
                "name": "The Great Town Square", 
                "description": "A bustling place with a magnificent fountain in the center. A stone well stands near the eastern corner, with a thick, wet rope disappearing into the darkness. To the south, you see the door to the local inn.",
                "unabsorbed_social_exp": 100,
                "objects": [ 
                    {
                        "name": "fountain", 
                        "description": "The fountain depicts the Goddess of Wealth pouring endless gold into the city. Its water is cool and clear."
                    },
                    {
                        "name": "well",
                        "description": "A weathered stone well. You can see a dark, winding rope tied to the lip, leading down. You could probably **CLIMB** the rope.",
                        "verbs": ["CLIMB"],
                        "target_room": "well_bottom"
                    },
                    # --- NEW OBJECT ---
                    {
                        "name": "door",
                        "description": "The sturdy wooden door to the inn. You could probably **ENTER** it.",
                        "verbs": ["ENTER"], # We'll need to create an 'enter' verb later
                        "target_room": "inn_room"
                    }
                ]
            },
            {
                "room_id": "north_gate", 
                "name": "Northern City Gate", 
                "description": "The massive iron gates leading out of the city stand before you.",
                "unabsorbed_social_exp": 0
            },
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
            },
            # --- NEW ROOM ---
            {
                "room_id": "inn_room",
                "name": "A Room at the Inn",
                "description": "You are in a simple, comfortable room with a straw-stuffed mattress and a small wooden nightstand. The morning light streams in through a single window. You feel as though you just woke from a long, hazy dream...",
                "unabsorbed_social_exp": 0,
                "objects": [
                    {
                        "name": "bed",
                        "description": "A simple straw mattress on a wooden frame. It's surprisingly comfortable."
                    },
                    {
                        "name": "window",
                        "description": "Looking out the window, you can see the bustling town square."
                    }
                ]
            }
        ])
        print("[DB INIT] Inserted initial room data.")
        
    # 2. Test Player 'Alice'
    if database.players.count_documents({"name": "Alice"}) == 0:
        database.players.insert_one(
            {
                "name": "Alice", 
                "current_room_id": "town_square", # Alice starts in the square
                "level": 1,
                "experience": 0,
                "strength": 12,
                "agility": 15,
                "gold": 100,
                "game_state": "playing", # Alice is already playing
                "chargen_step": 99,
                "appearance": { # Alice has a full description
                    "race": "Elf",
                    "height": "taller than average",
                    "build": "slender",
                    "age": "youthful",
                    "eye_char": "bright",
                    "eye_color": "green",
                    "complexion": "pale",
                    "hair_style": "long",
                    "hair_texture": "wavy",
                    "hair_color": "blonde",
                    "hair_quirk": "in a braid",
                    "face": "angular",
                    "nose": "straight",
                    "mark": "a small silver earring",
                    "unique": "She carries a faint scent of pine."
                }
            }
        )
        print("[DB INIT] Inserted test player 'Alice'.")


def fetch_player_data(player_name: str) -> dict:
    """Fetches player data from the 'players' collection or returns mock data."""
    database = get_db()
    if database is None:
        return {} # No mock data for Alice anymore

    # Case-insensitive search for player name
    player_data = database.players.find_one({"name": {"$regex": f"^{player_name}$", "$options": "i"}})
    return player_data if player_data else {}


def fetch_room_data(room_id: str) -> dict:
    """Fetches room data from the 'rooms' collection or returns mock data."""
    database = get_db()
    if database is None:
        if room_id == "town_square":
            return { "room_id": "town_square", "name": "The Great Town Square", "description": "A mock square." }
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
    """SCode for mud_backend/core/db.py..."""
    # ... (rest of the file is unchanged) ...
    database = get_db()
    if database is None:
        print(f"\n[DB SAVE MOCK] Room {room.name} state saved (Mock).")
        return

    room_data = room.to_dict()
    
    database.rooms.update_one(
        {"room_id": room.room_id}, 
        {"$set": room_data},       
        upsert=True
    )
    print(f"\n[DB SAVE] Room {room.name} state updated.")

get_db()
