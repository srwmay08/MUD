# mud_backend/core/db.py
import socket 
import json
import os
import uuid
# --- FIX: Import 'List' from typing ---
from typing import TYPE_CHECKING, Optional, Any, List
from pymongo import MongoClient
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError 
from mud_backend import config
# --- NEW: Import password hashing utilities ---
from werkzeug.security import generate_password_hash, check_password_hash

# --- REFACTORED: Removed game_state import ---
# from mud_backend.core import game_state
# --- END REFACTOR ---

if TYPE_CHECKING:
    from .game_objects import Player, Room
    # --- REFACTORED: Add World type hint ---
    from .game_state import World
    # --- END REFACTOR ---

MONGO_URI = config.MONGO_URI
DATABASE_NAME = config.DATABASE_NAME

client: Optional[MongoClient] = None
db = None

# ---
# --- THIS IS THE FIX: Create a static mock room cache
# ---
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
# ---
# --- END FIX
# ---

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
                upsert_count += 1
            elif result.modified_count > 0:
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

    # 2. Test Player 'Alice'
    # --- MODIFIED: Add account_username to Alice ---
    if database.players.count_documents({"name": "Alice"}) == 0:
        database.players.insert_one(
            {
                "name": "Alice", 
                "account_username": "dev", # <-- NEW: Link to an account
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

# --- NEW: Account Functions ---

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

# --- NEW: Character (Player) Functions ---

def fetch_characters_for_account(account_username: str) -> List[dict]:
    """Fetches all player characters associated with an account."""
    database = get_db()
    if database is None: return []
    
    characters = []
    # Find all players where 'account_username' matches (case-insensitive)
    cursor = database.players.find({
        "account_username": {"$regex": f"^{account_username}$", "$options": "i"}
    })
    for char in cursor:
        characters.append(char)
    return characters

# --- MODIFIED: Player & Room Functions ---

def fetch_player_data(player_name: str) -> dict:
    database = get_db()
    if database is None: return {} 
    # Check for player name (case-insensitive)
    player_data = database.players.find_one({"name": {"$regex": f"^{player_name}$", "$options": "i"}})
    return player_data if player_data else {}


def fetch_room_data(room_id: str) -> dict:
    database = get_db()
    if database is None:
        # --- MOCK DB FALLBACK ---
        # --- THIS IS THE FIX ---
        # Return from our static mock cache if it exists
        mock = MOCK_ROOMS.get(room_id)
        if mock:
            return mock
        # --- END FIX ---
        return {} # Original fallback
        
    room_data = database.rooms.find_one({"room_id": room_id})
    if room_data is None:
        # ---
        # --- THIS IS THE SECOND FIX ---
        # If the DB is connected but the query fails, *also* check mock data
        # This handles race conditions where the cache isn't populated yet
        mock = MOCK_ROOMS.get(room_id)
        if mock:
            print(f"[DB WARN] room_id '{room_id}' not found in DB, serving mock data.")
            return mock
        # --- END FIX ---
        return {"room_id": "void", "name": "The Void", "description": "Nothing but endless darkness here."}
    return room_data

def save_game_state(player: 'Player'):
    database = get_db()
    if database is None:
        print(f"\n[DB SAVE MOCK] Player {player.name} state saved (Mock).")
        return
        
    player_data = player.to_dict()
    # Ensure account_username is saved
    player_data["account_username"] = player.account_username 
    
    result = database.players.update_one(
        {"name": player.name}, 
        {"$set": player_data}, 
        upsert=True            
    )
    if result.upserted_id:
        player._id = result.upserted_id
        print(f"\n[DB SAVE] Player {player.name} created with ID: {player._id} for account {player.account_username}")
    else:
        pass # Standard save

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
    """
    Fetches all rooms and ensures every monster has a unique runtime ID (uid).
    """
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
                if "objects" in room_data:
                    for obj in room_data["objects"]:
                        # --- MODIFIED: Assign UID to NPCs as well ---
                        if (obj.get("is_monster") or obj.get("is_npc")) and "uid" not in obj:
                            obj["uid"] = uuid.uuid4().hex
                rooms_dict[room_id] = room_data
        print(f"[DB INIT] ...Cached {len(rooms_dict)} rooms.")
        return rooms_dict
    except Exception as e:
        print(f"[DB ERROR] Failed to fetch all rooms: {e}")
        return {}

def _load_json_data(filename: str) -> Any: # Changed to Any
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
    return {} if ".json" in filename else [] # Return list for e.g. leveling.json

def fetch_all_monsters() -> dict:
    print("[DB INIT] Caching all monsters from monsters.json...")
    monster_list = _load_json_data("monsters.json")
    monster_templates = {m["monster_id"]: m for m in monster_list if isinstance(m, dict) and m.get("monster_id")}
    print(f"[DB INIT] ...Cached {len(monster_templates)} monsters.")
    return monster_templates

def fetch_all_loot_tables() -> dict:
    print("[DB INIT] Caching all loot tables from loot.json...")
    loot_tables = _load_json_data("loot.json")
    print(f"[DB INIT] ...Cached {len(loot_tables)} loot tables.")
    return loot_tables

def fetch_all_items() -> dict:
    print("[DB INIT] Caching all items from items.json...")
    items = _load_json_data("items.json")
    print(f"[DB INIT] ...Cached {len(items)} items.")
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
    """Loads criticals.json into a dictionary."""
    print("[DB INIT] Caching all criticals from criticals.json...")
    criticals = _load_json_data("criticals.json")
    print(f"[DB INIT] ...Cached {len(criticals)} critical tables.")
    return criticals

def fetch_all_quests() -> dict:
    """Loads quests.json into a dictionary."""
    print("[DB INIT] Caching all quests from quests.json...")
    quests = _load_json_data("quests.json")
    print(f"[DB INIT] ...Cached {len(quests)} quests.")
    return quests

# ---
# --- NEW: Add fetch_all_factions
# ---
def fetch_all_factions() -> dict:
    """Loads faction.json into a dictionary."""
    print("[DB INIT] Caching all factions from faction.json...")
    factions = _load_json_data("faction.json")
    print(f"[DB INIT] ...Cached {len(factions.get('factions', 0))} factions.")
    return factions
# --- END NEW ---