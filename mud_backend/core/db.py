# mud_backend/core/db.py
# MODIFIED FILE
import socket 
import json
import os
import uuid
from typing import TYPE_CHECKING, Optional, Any, List, Dict
import glob
from pymongo import MongoClient
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError 
from mud_backend import config
from werkzeug.security import generate_password_hash, check_password_hash

if TYPE_CHECKING:
    from .game_objects import Player, Room
    from .game_state import World

MONGO_URI = config.MONGO_URI
DATABASE_NAME = config.DATABASE_NAME

client: Optional[MongoClient] = None
db = None

MOCK_ROOMS = {
    "town_square": { 
        "room_id": "town_square", 
        "name": "The Great Town Square", 
        "description": {"default": "A mock square."} 
    },
    "inn_room": {
        "room_id": "inn_room",
        "name": "A Room at the Inn",
        "description": {
            "default": "You are in a simple, comfortable room. A plain bed, a small table, and a wooden chair are the only furnishings. A single door leads OUT."
        },
        "objects": [
            { "name": "bed", "description": "A simple straw mattress...", "perception_dc": 0, "keywords": ["bed", "mattress"], "verbs": ["look", "investigate"] },
            { "name": "window", "description": "Looking out the window, you can see the bustling town square.", "perception_dc": 0, "keywords": ["window"] },
            { "name": "table", "description": "A small, plain wooden table.", "perception_dc": 0, "keywords": ["table"], "verbs": ["look", "investigate"] }
        ],
        "hidden_objects": [
            {
                "name": "a note", "item_id": "inn_note", "description": "A folded piece of parchment rests on the table.",
                "perception_dc": 10, "keywords": ["note", "parchment", "a note"],
                "verbs": ["GET", "LOOK", "EXAMINE", "TAKE"], "is_item": True
            }
        ],
        "exits": { "out": "inn_front_desk" }
    },
    "inn_front_desk": {
        "room_id": "inn_front_desk", "name": "Inn - Front Desk", "description": {"default": "You are at the front desk of the inn. A portly innkeeper stands here. A door leads back to your room, and the main exit leads OUT."},
        "objects": [
            { "name": "an innkeeper", "description": "A portly, cheerful-looking man.", "keywords": ["innkeeper", "man"], "verbs": ["look", "talk to", "give"], "is_npc": True, "quest_giver_ids": ["innkeeper_quest_1"] }
        ],
        "exits": { "out": "ts_south" },
        "interior_id": "inn"
    }
}

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
        data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
        json_files = glob.glob(os.path.join(data_dir, '**/rooms_*.json'), recursive=True)
        
        if not json_files:
            print("[DB ERROR] No 'rooms_*.json' files found in data/ directory.")
            return

        upsert_count = 0
        update_count = 0
        total_rooms = 0

        for file_path in json_files:
            with open(file_path, 'r') as f:
                room_data_list = json.load(f)
            
            for room_data in room_data_list:
                room_id = room_data.get("room_id")
                if not room_id:
                    continue
                
                total_rooms += 1
                result = database.rooms.update_one(
                    {"room_id": room_id},
                    {"$set": room_data},
                    upsert=True
                )
                if result.upserted_id:
                    upsert_count += 1
                elif result.modified_count > 0:
                    update_count += 1
        
        if upsert_count > 0 or update_count > 0:
             print(f"[DB INIT] JSON sync complete. Total rooms: {total_rooms}. Inserted: {upsert_count}, Updated: {update_count}.")
        else:
             print(f"[DB INIT] All {total_rooms} room(s) are up-to-date.")
             
    except FileNotFoundError:
        print(f"[DB ERROR] Could not find data directory at: {data_dir}")
    except json.JSONDecodeError:
        print(f"[DB ERROR] A zone file contains invalid JSON.")
    except Exception as e:
        print(f"[DB ERROR] An error occurred loading rooms: {e}")

    # 2. Test Player 'Alice'
    if database.players.count_documents({"name": "Alice"}) == 0:
        database.players.insert_one(
            {
                "name": "Alice", 
                "account_username": "dev", 
                "current_room_id": "town_square",
                "level": 0, "experience": 0, "game_state": "playing", "chargen_step": 99,
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
    
    # 3. Test Account 'dev'
    if database.accounts.count_documents({"username": "dev"}) == 0:
        database.accounts.insert_one({
            "username": "dev",
            "password_hash": generate_password_hash("dev")
        })
        print("[DB INIT] Inserted test account 'dev' (password: dev).")

def fetch_account(username: str) -> Optional[dict]:
    """Fetches an account by username (case-insensitive)."""
    database = get_db()
    if database is None: return None
    return database.accounts.find_one({"username": {"$regex": f"^{username}$", "$options": "i"}})

def create_account(username: str, password: str) -> bool:
    """Creates a new account with a hashed password."""
    database = get_db()
    if database is None: return False
    
    try:
        database.accounts.insert_one({
            "username": username,
            "password_hash": generate_password_hash(password)
        })
        return True
    except Exception as e:
        print(f"[DB ERROR] Could not create account: {e}")
        return False

def check_account_password(account_data: dict, password: str) -> bool:
    """Checks a given password against the stored hash."""
    return check_password_hash(account_data.get("password_hash", ""), password)

def fetch_characters_for_account(account_username: str) -> List[dict]:
    """Fetches all player characters associated with an account."""
    database = get_db()
    if database is None: return []
    
    characters = []
    cursor = database.players.find({
        "account_username": {"$regex": f"^{account_username}$", "$options": "i"}
    })
    for char in cursor:
        characters.append(char)
    return characters

def fetch_player_data(player_name: str) -> dict:
    database = get_db()
    if database is None: return {} 
    player_data = database.players.find_one({"name": {"$regex": f"^{player_name}$", "$options": "i"}})
    return player_data if player_data else {}

def fetch_room_data(room_id: str) -> dict:
    database = get_db()
    if database is None:
        mock = MOCK_ROOMS.get(room_id)
        if mock:
            return mock
        return {} 
        
    room_data = database.rooms.find_one({"room_id": room_id})
    if room_data is None:
        mock = MOCK_ROOMS.get(room_id)
        if mock:
            print(f"[DB WARN] room_id '{room_id}' not found in DB, serving mock data.")
            return mock
        return {"room_id": "void", "name": "The Void", "description": "Nothing but endless darkness here."}
    return room_data

def save_game_state(player: 'Player'):
    database = get_db()
    if database is None:
        print(f"\n[DB SAVE MOCK] Player {player.name} state saved (Mock).")
        return
        
    player_data = player.to_dict()
    player_data["account_username"] = player.account_username 
    
    result = database.players.update_one(
        {"name": player.name}, 
        {"$set": player_data}, 
        upsert=True            
    )
    if result.upserted_id:
        player._id = result.upserted_id
        print(f"\n[DB SAVE] Player {player.name} created with ID: {player._id} for account {player.account_username}")

def save_band(band_data: Dict[str, Any]):
    """Saves a band's data to the 'bands' collection."""
    database = get_db()
    if database is None:
        print(f"\n[DB SAVE MOCK] Band {band_data.get('id')} state saved (Mock).")
        return
        
    band_id = band_data.get("id")
    if not band_id:
        print("[DB ERROR] Cannot save band, 'id' is missing.")
        return
        
    database.bands.update_one(
        {"id": band_id},
        {"$set": band_data},
        upsert=True
    )

def delete_band(band_id: str):
    """Deletes a band from the 'bands' collection."""
    database = get_db()
    if database is None:
        print(f"\n[DB SAVE MOCK] Band {band_id} deleted (Mock).")
        return
    database.bands.delete_one({"id": band_id})
    
def fetch_all_bands(database) -> Dict[str, Dict[str, Any]]:
    """Loads all bands from the DB into a dictionary for caching."""
    if database is None:
        return {}
    
    print("[DB INIT] Caching all bands from database...")
    bands_dict = {}
    try:
        for band_data in database.bands.find():
            band_id = band_data.get("id")
            if band_id:
                bands_dict[band_id] = band_data
        print(f"[DB INIT] ...Cached {len(bands_dict)} bands.")
        return bands_dict
    except Exception as e:
        print(f"[DB ERROR] Failed to fetch all bands: {e}")
        return {}
        
def update_player_band(player_name_lower: str, band_id: Optional[str]):
    """Sets or unsets a player's band_id in the database."""
    database = get_db()
    if database is None: return
    
    database.players.update_one(
        {"name": {"$regex": f"^{player_name_lower}$", "$options": "i"}},
        {"$set": {"band_id": band_id}}
    )

def update_player_band_xp_bank(player_name_lower: str, amount_to_add: int):
    """Adds a value to a player's band_xp_bank in the database."""
    database = get_db()
    if database is None: return
    
    database.players.update_one(
        {"name": {"$regex": f"^{player_name_lower}$", "$options": "i"}},
        {"$inc": {"band_xp_bank": amount_to_add}}
    )

def save_room_state(room: 'Room'):
    """Saves the current state of a room object to the database."""
    database = get_db()
    room_data_dict = room.to_dict()
    
    if database is None:
        print(f"\n[DB SAVE MOCK] Room {room.name} state saved (Mock).")
        return
        
    query = {"room_id": room.room_id}
    room_data_dict.pop('_id', None)

    database.rooms.update_one(
        query, 
        {"$set": room_data_dict},       
        upsert=True
    )
    
def fetch_all_rooms() -> dict:
    """Fetches all rooms."""
    database = get_db()
    if database is None:
        print("[DB WARN] No database connection, cannot fetch all rooms.")
        print("[DB WARN] Loading MOCK_ROOMS cache.")
        return MOCK_ROOMS
        
    print("[DB INIT] Caching all rooms from database...")
    rooms_dict = {}
    try:
        for room_data in database.rooms.find():
            room_id = room_data.get("room_id")
            if room_id:
                if "objects" in room_data:
                    for obj in room_data["objects"]:
                        if (obj.get("is_monster") or obj.get("is_npc")) and "uid" not in obj:
                            obj["uid"] = uuid.uuid4().hex
                rooms_dict[room_id] = room_data
        print(f"[DB INIT] ...Cached {len(rooms_dict)} rooms.")
        return rooms_dict
    except Exception as e:
        print(f"[DB ERROR] Failed to fetch all rooms: {e}")
        return {}

def _load_json_data(filename: str) -> Any:
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
    return {} if ".json" in filename else []

def fetch_all_monsters() -> dict:
    """Fetches all monsters from all 'monsters*.json' files."""
    print("[DB INIT] Caching all monsters from monsters*.json files...")
    monster_templates = {}
    try:
        data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
        json_files = glob.glob(os.path.join(data_dir, '**/monsters*.json'), recursive=True)

        for file_path in json_files:
            with open(file_path, 'r') as f:
                monster_list = json.load(f)
            
            if isinstance(monster_list, list):
                for m in monster_list:
                    if isinstance(m, dict) and m.get("monster_id"):
                        monster_templates[m["monster_id"]] = m
            else:
                 print(f"[DB WARN] Monster file {file_path} is not a valid list.")
    except Exception as e:
        print(f"[DB ERROR] An error occurred loading monsters: {e}")
        
    print(f"[DB INIT] ...Cached {len(monster_templates)} monsters from {len(json_files)} file(s).")
    return monster_templates

def fetch_all_loot_tables() -> dict:
    """Fetches all loot tables from all 'loot*.json' files."""
    print("[DB INIT] Caching all loot tables from loot*.json files...")
    loot_tables = {}
    try:
        data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
        json_files = glob.glob(os.path.join(data_dir, '**/loot*.json'), recursive=True)

        for file_path in json_files:
            with open(file_path, 'r') as f:
                table_data = json.load(f)
            if isinstance(table_data, dict):
                loot_tables.update(table_data)
            else:
                print(f"[DB WARN] Loot file {file_path} is not a valid dictionary.")
    except Exception as e:
        print(f"[DB ERROR] An error occurred loading loot tables: {e}")
    
    print(f"[DB INIT] ...Cached {len(loot_tables)} loot tables from {len(json_files)} file(s).")
    return loot_tables

def fetch_all_items() -> dict:
    """Fetches all items from all 'items*.json' files."""
    print("[DB INIT] Caching all items from items*.json files...")
    items = {}
    try:
        data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
        json_files = glob.glob(os.path.join(data_dir, '**/items*.json'), recursive=True)

        for file_path in json_files:
            with open(file_path, 'r') as f:
                item_data = json.load(f)
            if isinstance(item_data, dict):
                items.update(item_data)
            else:
                 print(f"[DB WARN] Item file {file_path} is not a valid dictionary.")
    except Exception as e:
        print(f"[DB ERROR] An error occurred loading items: {e}")
    
    print(f"[DB INIT] ...Cached {len(items)} items from {len(json_files)} file(s).")
    return items

def fetch_all_levels() -> list:
    print("[DB INIT] Caching level table from leveling.json...")
    level_data = _load_json_data("leveling.json")
    if isinstance(level_data, list):
        print(f"[DB INIT] ...Cached {len(level_data)} level thresholds.")
        return level_data
    print("[DB ERROR] 'leveling.json' is not a valid list.")
    return []

def fetch_all_skills() -> dict:
    print("[DB INIT] Caching all skills from skills.json...")
    skill_list = _load_json_data("skills.json")
    if not isinstance(skill_list, list):
        print("[DB ERROR] 'skills.json' is not a valid list.")
        return {}
    skill_templates = {s["skill_id"]: s for s in skill_list if isinstance(s, dict) and s.get("skill_id")}
    print(f"[DB INIT] ...Cached {len(skill_templates)} skills.")
    return skill_templates

def fetch_all_criticals() -> dict:
    print("[DB INIT] Caching all criticals from criticals.json...")
    criticals = _load_json_data("criticals.json")
    print(f"[DB INIT] ...Cached {len(criticals)} critical tables.")
    return criticals

def fetch_all_quests() -> dict:
    print("[DB INIT] Caching all quests from quests.json...")
    quests = _load_json_data("quests.json")
    print(f"[DB INIT] ...Cached {len(quests)} quests.")
    return quests

def fetch_all_nodes() -> dict:
    print("[DB INIT] Caching all gathering nodes from nodes.json...")
    nodes = _load_json_data("nodes.json")
    print(f"[DB INIT] ...Cached {len(nodes)} nodes.")
    return nodes

def fetch_all_factions() -> dict:
    """Loads faction.json into a dictionary."""
    print("[DB INIT] Caching all factions from faction.json...")
    factions = _load_json_data("faction.json")
    print(f"[DB INIT] ...Cached {len(factions.get('factions', 0))} factions.")
    return factions

# --- NEW: Fetch All Spells ---
def fetch_all_spells() -> dict:
    """Loads spells.json into a dictionary."""
    print("[DB INIT] Caching all spells from spells.json...")
    spells = _load_json_data("spells.json")
    print(f"[DB INIT] ...Cached {len(spells)} spells.")
    return spells
# --- END NEW ---