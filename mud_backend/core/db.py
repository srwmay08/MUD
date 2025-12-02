# mud_backend/core/db.py
import socket 
import json
import os
import sys
import uuid
import glob
from typing import TYPE_CHECKING, Optional, Any, List, Dict

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure 
from werkzeug.security import generate_password_hash, check_password_hash

from mud_backend import config

if TYPE_CHECKING:
    from .game_objects import Player, Room

MONGO_URI = config.MONGO_URI
DATABASE_NAME = config.DATABASE_NAME

client: Optional[MongoClient] = None
db = None

def get_db():
    global client, db
    
    if db is not None:
        return db

    try:
        # Set a short timeout so we don't hang forever during development
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        
        # Force a connection check immediately
        client.admin.command('ismaster')
        
        db = client[DATABASE_NAME]
        print(f"[DB INIT] Connected to MongoDB: {DATABASE_NAME}")
        
        # Check if this is a fresh install and seed data
        ensure_initial_data()
        return db
        
    except ConnectionFailure as e:
        print(f"\n[CRITICAL DB ERROR] Could not connect to MongoDB at {MONGO_URI}")
        print(f"Error Details: {e}")
        print("-------------------------------------------------------------")
        print("PLEASE ENSURE MONGODB IS RUNNING.")
        print("1. Open a new terminal.")
        print("2. Type 'mongod' and hit enter.")
        print("3. If it is running, check the URI in config.py.")
        print("-------------------------------------------------------------")
        # Kill the server immediately so we don't run in a broken state
        sys.exit(1)

def ensure_initial_data():
    """Ensures base entities exist from JSON definitions."""
    database = get_db()

    print("[DB INIT] Syncing JSON data to Database...")
    
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    json_files = glob.glob(os.path.join(data_dir, '**/rooms_*.json'), recursive=True)
    
    if not json_files:
        print("[DB ERROR] No 'rooms_*.json' files found in data/ directory.")
        return

    upsert_count = 0
    for file_path in json_files:
        try:
            with open(file_path, 'r') as f:
                # Check if file is empty before loading
                content = f.read()
                if not content.strip():
                    print(f"[DB WARN] Skipping empty file: {file_path}")
                    continue
                room_data_list = json.loads(content)
            
            for room_data in room_data_list:
                room_id = room_data.get("room_id")
                if not room_id: continue
                
                result = database.rooms.update_one(
                    {"room_id": room_id},
                    {"$set": room_data},
                    upsert=True
                )
                if result.upserted_id: upsert_count += 1
        except json.JSONDecodeError as e:
            print(f"[DB ERROR] Invalid JSON in {file_path}: {e}")
        except Exception as e:
            print(f"[DB ERROR] Failed to load {file_path}: {e}")
    
    if upsert_count > 0:
            print(f"[DB INIT] JSON sync complete. Inserted {upsert_count} new rooms.")

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
    return get_db().accounts.find_one({"username": {"$regex": f"^{username}$", "$options": "i"}})

def create_account(username: str, password: str) -> bool:
    try:
        get_db().accounts.insert_one({
            "username": username,
            "password_hash": generate_password_hash(password)
        })
        return True
    except Exception as e:
        print(f"[DB ERROR] Could not create account: {e}")
        return False

def check_account_password(account_data: dict, password: str) -> bool:
    return check_password_hash(account_data.get("password_hash", ""), password)

def fetch_characters_for_account(account_username: str) -> List[dict]:
    cursor = get_db().players.find({
        "account_username": {"$regex": f"^{account_username}$", "$options": "i"}
    })
    return list(cursor)

def fetch_player_data(player_name: str) -> dict:
    player_data = get_db().players.find_one({"name": {"$regex": f"^{player_name}$", "$options": "i"}})
    return player_data if player_data else {}

def fetch_room_data(room_id: str) -> dict:
    room_data = get_db().rooms.find_one({"room_id": room_id})
    if room_data is None:
        print(f"[DB WARN] room_id '{room_id}' not found in DB. Is it defined in the JSON files?")
        return {"room_id": "void", "name": "The Void", "description": "Nothing but endless darkness here."}
    return room_data

def save_game_state(player: 'Player'):
    player_data = player.to_dict()
    player_data["account_username"] = player.account_username 
    
    result = get_db().players.update_one(
        {"name": player.name}, 
        {"$set": player_data}, 
        upsert=True            
    )
    if result.upserted_id:
        player._id = result.upserted_id

def save_band(band_data: Dict[str, Any]):
    band_id = band_data.get("id")
    if not band_id: return
    get_db().bands.update_one({"id": band_id}, {"$set": band_data}, upsert=True)

def delete_band(band_id: str):
    get_db().bands.delete_one({"id": band_id})
    
def fetch_all_bands(database) -> Dict[str, Dict[str, Any]]:
    db_ref = database if database is not None else get_db()
    bands_dict = {}
    for band_data in db_ref.bands.find():
        band_id = band_data.get("id")
        if band_id:
            bands_dict[band_id] = band_data
    return bands_dict
        
def update_player_band(player_name_lower: str, band_id: Optional[str]):
    get_db().players.update_one(
        {"name": {"$regex": f"^{player_name_lower}$", "$options": "i"}},
        {"$set": {"band_id": band_id}}
    )

def update_player_band_xp_bank(player_name_lower: str, amount_to_add: int):
    get_db().players.update_one(
        {"name": {"$regex": f"^{player_name_lower}$", "$options": "i"}},
        {"$inc": {"band_xp_bank": amount_to_add}}
    )

def save_room_state(room: 'Room'):
    room_data_dict = room.to_dict()
    room_data_dict.pop('_id', None)
    get_db().rooms.update_one(
        {"room_id": room.room_id}, 
        {"$set": room_data_dict},       
        upsert=True
    )
    
def fetch_all_rooms() -> dict:
    rooms_dict = {}
    for room_data in get_db().rooms.find():
        room_id = room_data.get("room_id")
        if room_id:
            if "objects" in room_data:
                for obj in room_data["objects"]:
                    if (obj.get("is_monster") or obj.get("is_npc")) and "uid" not in obj:
                        obj["uid"] = uuid.uuid4().hex
            rooms_dict[room_id] = room_data
    return rooms_dict

def _load_json_data(filename: str) -> Any:
    try:
        json_path = os.path.join(os.path.dirname(__file__), '..', 'data', filename)
        with open(json_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[DB ERROR] Could not find '{filename}' at: {json_path}")
    except json.JSONDecodeError:
        print(f"[DB ERROR] '{filename}' contains invalid JSON.")
    return {} if ".json" in filename else []

def fetch_all_monsters() -> dict:
    monster_templates = {}
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    
    search_patterns = ['**/monsters*.json', '**/npcs*.json']
    
    for pattern in search_patterns:
        for file_path in glob.glob(os.path.join(data_dir, pattern), recursive=True):
            with open(file_path, 'r') as f:
                try:
                    monster_list = json.load(f)
                    if isinstance(monster_list, list):
                        for m in monster_list:
                            if isinstance(m, dict) and m.get("monster_id"):
                                monster_templates[m["monster_id"]] = m
                except json.JSONDecodeError:
                    print(f"[DB ERROR] Invalid JSON in {file_path}")
                    
    return monster_templates

def fetch_all_loot_tables() -> dict:
    loot_tables = {}
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    for file_path in glob.glob(os.path.join(data_dir, '**/loot*.json'), recursive=True):
        with open(file_path, 'r') as f:
            table_data = json.load(f)
        if isinstance(table_data, dict):
            loot_tables.update(table_data)
    return loot_tables

def fetch_all_items() -> dict:
    items = {}
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    for file_path in glob.glob(os.path.join(data_dir, '**/items*.json'), recursive=True):
        with open(file_path, 'r') as f:
            item_data = json.load(f)
        if isinstance(item_data, dict):
            items.update(item_data)
    return items

def fetch_all_levels() -> list:
    return _load_json_data("leveling.json")

def fetch_all_skills() -> dict:
    skill_list = _load_json_data("skills.json")
    if isinstance(skill_list, list):
        return {s["skill_id"]: s for s in skill_list if isinstance(s, dict) and s.get("skill_id")}
    return {}

def fetch_all_criticals() -> dict:
    return _load_json_data("criticals.json")

def fetch_all_quests() -> dict:
    quests = {}
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    main_quests = _load_json_data("quests.json")
    if isinstance(main_quests, dict):
        for k, v in main_quests.items():
            v["id"] = k
        quests.update(main_quests)

    for file_path in glob.glob(os.path.join(data_dir, '**/quest*.json'), recursive=True):
        if os.path.basename(file_path) == "quests.json":
             continue
        with open(file_path, 'r') as f:
            try:
                data = json.load(f)
                if isinstance(data, dict):
                    for k, v in data.items():
                        v["id"] = k
                    quests.update(data)
            except json.JSONDecodeError:
                print(f"[DB ERROR] Invalid JSON in {file_path}")
    return quests

def fetch_all_nodes() -> dict:
    return _load_json_data("nodes.json")

def fetch_all_factions() -> dict:
    return _load_json_data("faction.json")

def fetch_all_races() -> dict:
    return _load_json_data("races.json")

def fetch_all_spells() -> dict:
    spells = {}
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    spells_dir = os.path.join(data_dir, 'spells')
    if os.path.exists(spells_dir):
        for file_path in glob.glob(os.path.join(spells_dir, '*.json')):
            with open(file_path, 'r') as f:
                try:
                    spell_data = json.load(f)
                    if isinstance(spell_data, dict):
                        spells.update(spell_data)
                except json.JSONDecodeError:
                    print(f"[DB ERROR] Invalid JSON in spell file: {file_path}")
    root_spells_path = os.path.join(data_dir, "spells.json")
    if os.path.exists(root_spells_path):
        root_spells = _load_json_data("spells.json")
        if root_spells:
            spells.update(root_spells)
    return spells

def fetch_all_deities() -> dict:
    try:
        json_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'lore', 'deities.json')
        if os.path.exists(json_path):
            with open(json_path, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"[DB ERROR] Could not load deities: {e}")
    return {}

def fetch_all_guilds() -> dict:
    try:
        json_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'lore', 'guilds.json')
        if os.path.exists(json_path):
            with open(json_path, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"[DB ERROR] Could not load guilds: {e}")
    return {}

def fetch_combat_rules() -> dict:
    return _load_json_data("combat_rules.json")

# --- ECONOMY & MAIL EXTENSIONS ---

def send_mail(mail_data: dict):
    """Inserts a mail object."""
    get_db().mail.insert_one(mail_data)

def get_player_mail(player_name: str) -> List[dict]:
    """Retrieves all mail for a player."""
    return list(get_db().mail.find({"recipient": player_name, "deleted": {"$ne": True}}))

def mark_mail_read(mail_id: str):
    get_db().mail.update_one({"uid": mail_id}, {"$set": {"read": True}})

def delete_mail(mail_id: str):
    get_db().mail.update_one({"uid": mail_id}, {"$set": {"deleted": True}})

def get_priority_mail(player_name: str) -> List[dict]:
    """Used for the Courier trigger."""
    return list(get_db().mail.find({
        "recipient": player_name, 
        "flags": "System_Priority", 
        "delivered": False,
        "deleted": {"$ne": True}
    }))

def mark_mail_delivered(mail_id: str):
    get_db().mail.update_one({"uid": mail_id}, {"$set": {"delivered": True}})

def create_auction(auction_data: dict):
    get_db().auctions.insert_one(auction_data)

def get_active_auctions() -> List[dict]:
    return list(get_db().auctions.find({"status": "active"}))

def get_auction(auction_id: str) -> Optional[dict]:
    return get_db().auctions.find_one({"uid": auction_id})

def update_auction_bid(auction_id: str, new_bid: int, high_bidder: str):
    get_db().auctions.update_one(
        {"uid": auction_id}, 
        {"$set": {"current_bid": new_bid, "high_bidder": high_bidder}}
    )

def end_auction(auction_id: str, status: str = "ended"):
    get_db().auctions.update_one({"uid": auction_id}, {"$set": {"status": status}})

def update_player_locker(player_name: str, locker_data: dict):
    get_db().players.update_one(
        {"name": {"$regex": f"^{player_name}$", "$options": "i"}},
        {"$set": {"locker": locker_data}}
    )