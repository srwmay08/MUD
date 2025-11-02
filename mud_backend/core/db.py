# core/db.py
import socket 
import json
import os
from typing import TYPE_CHECKING, Optional
from pymongo import MongoClient
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError 
from mud_backend import config # <-- NEW IMPORT

if TYPE_CHECKING:
    from .game_objects import Player, Room

MONGO_URI = config.MONGO_URI # <-- CHANGED
DATABASE_NAME = config.DATABASE_NAME # <-- CHANGED

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
    """Ensures base entities exist from JSON definitions."""
    database = get_db()
    if database is None:
        return

    # --- 1. Load Rooms from JSON ---
    print("[DB INIT] Checking initial data from JSON...")
    try:
        json_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'rooms.json')
        with open(json_path, 'r') as f:
            room_data_list = json.load(f)
        
        # (Rest of room loading logic is unchanged)
        upsert_count = 0
        update_count = 0
        for room_data in room_data_list:
            room_id = room_data.get("room_id")
            if not room_id:
                continue
            result = database.rooms.update_one(
                {"room_id": room_id},
                {"$set": room_data},
                upsert=True
            )
            if result.upserted_id:
                print(f"[DB DEBUG] Inserted new room: {room_id}")
                upsert_count += 1
            elif result.modified_count > 0:
                print(f"[DB DEBUG] Updated existing room: {room_id}")
                update_count += 1
        
        if upsert_count > 0 or update_count > 0:
             print(f"[DB INIT] JSON sync complete. Inserted: {upsert_count}, Updated: {update_count}.")
        else:
             print("[DB INIT] All room data is up-to-date.")
             
    except FileNotFoundError:
        print(f"[DB ERROR] Could not find 'rooms.json' at: {json_path}")
    except json.JSONDecodeError:
        print(f"[DB ERROR] 'rooms.json' contains invalid JSON.")
    except Exception as e:
        print(f"[DB ERROR] An error occurred loading rooms: {e}")

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
    # (function is unchanged)
    database = get_db()
    if database is None: return {} 
    player_data = database.players.find_one({"name": {"$regex": f"^{player_name}$", "$options": "i"}})
    return player_data if player_data else {}


def fetch_room_data(room_id: str) -> dict:
    # (function is unchanged)
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
    # (function is unchanged)
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
    # (function is unchanged)
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

def fetch_all_rooms() -> dict:
    # (function is unchanged)
    database = get_db()
    if database is None:
        print("[DB WARN] No database connection, cannot fetch all rooms.")
        return {}
        
    print("[DB INIT] Caching all rooms from database...")
    rooms_dict = {}
    try:
        for room_data in database.rooms.find():
            room_id = room_data.get("room_id")
            if room_id:
                rooms_dict[room_id] = room_data
        print(f"[DB INIT] ...Cached {len(rooms_dict)} rooms.")
        return rooms_dict
    except Exception as e:
        print(f"[DB ERROR] Failed to fetch all rooms: {e}")
        return {}

# ---
# NEW FUNCTIONS TO LOAD DATA FILES
# ---

def _load_json_data(filename: str) -> dict:
    """Helper to load a JSON file from the 'data' directory."""
    try:
        json_path = os.path.join(os.path.dirname(__file__), '..', 'data', filename)
        with open(json_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[DB ERROR] Could not find '{filename}' at: {json_path}")
    except json.JSONDecodeError:
        print(f"[DB ERROR] '{filename}' contains invalid JSON.")
    except Exception as e:
        print(f"[DB ERROR] An error occurred loading '{filename}': {e}")
    return {}

def fetch_all_monsters() -> dict:
    """Loads monsters.json and keys it by monster_id."""
    print("[DB INIT] Caching all monsters from monsters.json...")
    monster_list = _load_json_data("monsters.json")
    monster_templates = {m["monster_id"]: m for m in monster_list if m.get("monster_id")}
    print(f"[DB INIT] ...Cached {len(monster_templates)} monsters.")
    return monster_templates

def fetch_all_loot_tables() -> dict:
    """Loads loot.json."""
    print("[DB INIT] Caching all loot tables from loot.json...")
    loot_tables = _load_json_data("loot.json")
    print(f"[DB INIT] ...Cached {len(loot_tables)} loot tables.")
    return loot_tables

def fetch_all_items() -> dict:
    """Loads items.json."""
    print("[DB INIT] Caching all items from items.json...")
    items = _load_json_data("items.json")
    print(f"[DB INIT] ...Cached {len(items)} items.")
    return items

# ---
get_db()