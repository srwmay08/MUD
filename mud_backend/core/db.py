# core/db.py
import socket 
from typing import TYPE_CHECKING, Optional
from pymongo import MongoClient
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError 

if TYPE_CHECKING:
    from .game_objects import Player, Room

MONGO_URI = "mongodb://localhost:27017/" 
DATABASE_NAME = "MUD_Dev"  

client: Optional[MongoClient] = None
db = None

def get_db():
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
            # --- MAIN ROOM ---
            {
                "room_id": "town_square", 
                "name": "The Great Town Square", 
                # --- UPDATED DESCRIPTION ---
                "description": "A bustling place with a magnificent fountain in the center. Paths lead in all directions, and a stone well stands near the eastern corner.",
                "unabsorbed_social_exp": 100,
                "objects": [ 
                    {"name": "fountain", "description": "The fountain depicts the Goddess of Wealth pouring endless gold into the city. Its water is cool and clear."},
                    {"name": "well", "description": "A weathered stone well. You can see a dark, winding rope tied to the lip, leading down. You could probably **CLIMB** the rope.", "verbs": ["CLIMB"], "target_room": "well_bottom"},
                    # The 'door' is now in 'ts_south'
                ],
                "exits": {
                    "north": "ts_north",
                    "south": "ts_south",
                    "east": "ts_east",
                    "west": "ts_west",
                    "northeast": "ts_northeast",
                    "northwest": "ts_northwest",
                    "southeast": "ts_southeast",
                    "southwest": "ts_southwest",
                }
            },
            
            # --- DIRECTIONAL ROOMS ---
            {"room_id": "ts_north", "name": "North Square", "description": "You are in the northern part of the town square. The main square is to the south.", "exits": {"south": "town_square", "east": "ts_northeast", "west": "ts_northwest"}},
            # --- UPDATED SOUTHERN ROOM ---
            {"room_id": "ts_south", "name": "South Square", "description": "You are in the southern part of the town square. The main square is to the north. The sturdy wooden door to the inn is here.", "exits": {"north": "town_square", "east": "ts_southeast", "west": "ts_southwest"}, "objects": [{"name": "door", "description": "The sturdy wooden door to the inn. You could probably **ENTER** it.", "verbs": ["ENTER"], "target_room": "inn_room"}]},
            {"room_id": "ts_east", "name": "East Square", "description": "You are in the eastern part of the town square. The main square is to the west. The old well is here.", "exits": {"west": "town_square", "north": "ts_northeast", "south": "ts_southeast"}, "objects": [{"name": "well", "description": "A weathered stone well...", "verbs": ["CLIMB"], "target_room": "well_bottom"}]},
            {"room_id": "ts_west", "name": "West Square", "description": "You are in the western part of the town square. The main square is to the east.", "exits": {"east": "town_square", "north": "ts_northwest", "south": "ts_southwest"}},
            {"room_id": "ts_northeast", "name": "Northeast Square", "description": "You are in the northeast corner of the town square.", "exits": {"southwest": "town_square", "south": "ts_east", "west": "ts_north"}},
            {"room_id": "ts_northwest", "name": "Northwest Square", "description": "You are in the northwest corner of the town square.", "exits": {"southeast": "town_square", "south": "ts_west", "east": "ts_north"}},
            {"room_id": "ts_southeast", "name": "Southeast Square", "description": "You are in the southeast corner of the town square.", "exits": {"northwest": "town_square", "north": "ts_east", "west": "ts_south"}},
            {"room_id": "ts_southwest", "name": "Southwest Square", "description": "You are in the southwest corner of the town square.", "exits": {"northeast": "town_square", "north": "ts_west", "east": "ts_south"}},

            # --- OTHER ROOMS ---
            {
                "room_id": "inn_room",
                "name": "A Room at the Inn",
                "description": "You are in a simple, comfortable room... You feel as though you just woke from a long, hazy dream...",
                "objects": [
                    {"name": "bed", "description": "A simple straw mattress..."},
                    {"name": "window", "description": "Looking out the window, you can see the bustling town square."}
                ],
                # --- NEW EXIT ---
                "exits": { "out": "ts_south" } 
            },
            {
                "room_id": "well_bottom", 
                "name": "The Bottom of the Well", 
                "description": "It is dark and cramped down here. A monster is stirring in the corner!",
                "objects": [
                    {"name": "rope", "description": "A thick, wet rope leads back up to the town square.", "verbs": ["CLIMB"], "target_room": "town_square"}
                ],
                "exits": {}
            }
        ])
        print("[DB INIT] Inserted initial room data.")
        
    # 2. Test Player 'Alice' (Unchanged)
    if database.players.count_documents({"name": "Alice"}) == 0:
        database.players.insert_one(
            {
                "name": "Alice", 
                "current_room_id": "town_square",
                "level": 1, "experience": 0, "game_state": "playing", "chargen_step": 99,
                "stats": {
                    "STR": 75, "CON": 70, "DEX": 80, "AGI": 72, "LOG": 85, "INT": 88, "WIS": 65, "INF": 60,
                    "ZEA": 50, "ESS": 55, "DIS": 68, "AUR": 78
                },
                "appearance": {
                    "race": "Elf", "height": "taller than average", "build": "slender", "age": "youthful",
                    "eye_char": "bright", "eye_color": "green", "complexion": "pale", "hair_style": "long",
                    "hair_texture": "wavy", "hair_color": "blonde", "hair_quirk": "in a braid",
                    "face": "angular", "nose": "straight", "mark": "a small silver earring",
                    "unique": "She carries a faint scent of pine."
                }
            }
        )
        print("[DB INIT] Inserted test player 'Alice'.")


def fetch_player_data(player_name: str) -> dict:
    database = get_db()
    if database is None: return {} 
    player_data = database.players.find_one({"name": {"$regex": f"^{player_name}$", "$options": "i"}})
    return player_data if player_data else {}


def fetch_room_data(room_id: str) -> dict:
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