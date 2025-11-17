# mud_backend/core/game_state.py
# MODIFIED FILE
import time
import threading
import copy
from mud_backend import config
from typing import Dict, Any, Optional, List, Tuple
from mud_backend.core import db
# --- NEW: Import Player for type hinting ---
from mud_backend.core.game_objects import Player
# --- END NEW ---

#
# --- THIS FILE IS NO LONGER A GLOBAL MODULE ---
# It now defines the `World` class, which will be
# instantiated ONCE by app.py and passed to all
# systems that need it (Dependency Injection).
#

class World:
    """
    Holds all mutable game state and provides thread-safe
    methods for accessing and modifying it.
    """
    def __init__(self):
        self.socketio = None
        # ---
        # --- THIS IS THE FIX
        # ---
        self.app = None # To hold the Flask app context
        # ---
        # --- END FIX
        # ---
        
        # --- State Dictionaries ---
        self.runtime_monster_hp: Dict[str, int] = {}
        self.defeated_monsters: Dict[str, Dict[str, Any]] = {}
        self.game_rooms: Dict[str, Dict[str, Any]] = {}
        self.active_players: Dict[str, Dict[str, Any]] = {}
        self.combat_state: Dict[str, Dict[str, Any]] = {}
        self.pending_trades: Dict[str, Dict[str, Any]] = {}
        # --- NEW: Grouping and Band State ---
        self.active_groups: Dict[str, Dict[str, Any]] = {} # { "group_id": {"leader": "p1", "members": ["p1", "p2"]} }
        self.pending_group_invites: Dict[str, Dict[str, Any]] = {} # { "p2_lower": {"from": "p1", "group_id": "gid", "time": 123} }
        self.active_bands: Dict[str, Dict[str, Any]] = {} # { "band_id": {"leader": "p1", "members": ["p1", "p2", "p3"]} }
        # --- END NEW ---

        # --- Global Data Caches (Read-only after load) ---
        self.game_monster_templates: Dict[str, Dict] = {}
        self.game_loot_tables: Dict[str, List] = {}
        self.game_items: Dict[str, Dict] = {}
        self.game_level_table: List[int] = []
        self.game_skills: Dict[str, Dict] = {}
        self.game_criticals: Dict[str, Any] = {}
        self.game_quests: Dict[str, Any] = {}
        self.game_nodes: Dict[str, Any] = {} 
        self.game_factions: Dict[str, Any] = {}

        # --- Game Loop Timers ---
        self.last_game_tick_time: float = time.time()
        self.tick_interval_seconds: float = config.TICK_INTERVAL_SECONDS
        self.last_monster_tick_time: float = time.time()
        self.game_tick_counter: int = 0
        self.player_timeout_seconds: int = config.PLAYER_TIMEOUT_SECONDS
        # --- NEW: Band Payout Timer ---
        self.last_band_payout_time: float = time.time()
        # --- END NEW ---

        # --- Threading Locks ---
        self.player_lock = threading.RLock()
        self.combat_lock = threading.RLock()
        self.trade_lock = threading.RLock()
        self.room_lock = threading.RLock()
        self.monster_hp_lock = threading.RLock()
        self.defeated_lock = threading.RLock()
        # --- NEW: Grouping and Band Locks ---
        self.group_lock = threading.RLock()
        self.band_lock = threading.RLock()
        # --- END NEW ---

    # --- Data Loading ---
    
    def load_all_data(self, database):
        """
        Loads all static game data from the database into the
        World object's state. Called once on startup.
        """
        if database is None:
            print("[WORLD ERROR] Database is None. Cannot load data.")
            return
            
        print("[WORLD INIT] Loading all rooms into game state cache...")
        self.game_rooms = db.fetch_all_rooms()
        print("[WORLD INIT] Loading all monster templates...")
        self.game_monster_templates = db.fetch_all_monsters()
        print("[WORLD INIT] Loading all loot tables...")
        self.game_loot_tables = db.fetch_all_loot_tables()
        print("[WORLD INIT] Loading all items...")
        self.game_items = db.fetch_all_items()
        print("[WORLD INIT] Loading level table...")
        self.game_level_table = db.fetch_all_levels()
        print("[WORLD INIT] Loading all skills...")
        self.game_skills = db.fetch_all_skills()
        print("[WORLD INIT] Loading all criticals...")
        self.game_criticals = db.fetch_all_criticals()
        print("[WORLD INIT] Loading all quests...")
        self.game_quests = db.fetch_all_quests()
        print("[WORLD INIT] Loading all nodes...")
        self.game_nodes = db.fetch_all_nodes()
        print("[WORLD INIT] Loading all factions...")
        self.game_factions = db.fetch_all_factions()
        # --- NEW: Load Bands ---
        print("[WORLD INIT] Loading all adventuring bands...")
        self.active_bands = db.fetch_all_bands(database)
        # --- END NEW ---
        print("[WORLD INIT] Data loaded.")

    # --- Player Accessors (Thread-Safe) ---
    
    def get_player_info(self, player_name_lower: str) -> Optional[Dict[str, Any]]:
        with self.player_lock:
            return self.active_players.get(player_name_lower)

    def get_player_obj(self, player_name_lower: str) -> Optional['Player']:
        with self.player_lock:
            info = self.active_players.get(player_name_lower)
            if info:
                return info.get("player_obj")
        return None

    def set_player_info(self, player_name_lower: str, data: Dict[str, Any]):
        with self.player_lock:
            self.active_players[player_name_lower] = data
            
    def remove_player(self, player_name_lower: str) -> Optional[Dict[str, Any]]:
        # --- NEW: Handle group leave on disconnect ---
        player_obj = self.get_player_obj(player_name_lower)
        if player_obj and player_obj.group_id:
            group = self.get_group(player_obj.group_id)
            if group:
                group_id = player_obj.group_id
                player_obj.group_id = None
                if player_name_lower in group["members"]:
                    group["members"].remove(player_name_lower)
                
                self.send_message_to_group(group_id, f"{player_obj.name} has left the group (disconnected).")
                
                if group["leader"] == player_name_lower:
                    if group["members"]:
                        new_leader_key = group["members"][0]
                        group["leader"] = new_leader_key
                        self.set_group(group_id, group)
                        self.send_message_to_group(group_id, f"{new_leader_key.capitalize()} is the new group leader.")
                    else:
                        self.remove_group(group_id)
                else:
                    self.set_group(group_id, group)
        # --- END NEW ---
            
        with self.player_lock:
            return self.active_players.pop(player_name_lower, None)

    def get_all_players_info(self) -> List[Tuple[str, Dict[str, Any]]]:
        with self.player_lock:
            return list(self.active_players.items())

    # ---
    # --- THIS IS THE FIX: The missing function
    # ---
    def get_player_group_id_on_load(self, player_name_lower: str) -> Optional[str]:
        """
        Checks all active groups to see if a logging-in player
        belongs to one.
        """
        with self.group_lock:
            for group_id, group_data in self.active_groups.items():
                if player_name_lower in group_data.get("members", []):
                    return group_id
        return None
    # ---
    # --- END FIX
    # ---

    # --- Room Accessors (Thread-Safe) ---

    def get_room(self, room_id: str) -> Optional[Dict[str, Any]]:
        with self.room_lock:
            # Return a deep copy to prevent mutation outside of a lock
            room_data = self.game_rooms.get(room_id)
            if room_data:
                return copy.deepcopy(room_data)
        
        # If not in cache, fetch from DB (fallback)
        room_db_data = db.fetch_room_data(room_id)
        if room_db_data and room_db_data.get("room_id") != "void":
            with self.room_lock:
                self.game_rooms[room_id] = room_db_data
            return copy.deepcopy(room_db_data)
        return room_db_data # Returns void room or {}

    def get_all_rooms(self) -> Dict[str, Dict[str, Any]]:
        with self.room_lock:
            return copy.deepcopy(self.game_rooms)
            
    def update_room_cache(self, room_id: str, room_data: Dict[str, Any]):
        with self.room_lock:
            self.game_rooms[room_id] = room_data

    def save_room(self, room_obj: 'Room'):
        """Saves room to DB and updates the cache."""
        # This calls the db function, which is fine
        db.save_room_state(room_obj) 
        # But we also must update our internal cache
        with self.room_lock:
            self.game_rooms[room_obj.room_id] = room_obj.to_dict()

    def move_object_between_rooms(self, obj_to_move: Dict, from_room_id: str, to_room_id: str) -> bool:
        with self.room_lock:
            source_room = self.game_rooms.get(from_room_id)
            dest_room = self.game_rooms.get(to_room_id)

            if not source_room or not dest_room:
                return False
            
            # Find and remove from source
            found_in_source = False
            if "objects" in source_room and obj_to_move in source_room["objects"]:
                source_room["objects"].remove(obj_to_move)
                found_in_source = True
            
            if not found_in_source:
                # This can happen if the object representation isn't identical.
                # Try to find by UID if it's a monster.
                uid = obj_to_move.get("uid")
                if uid:
                    for i, obj in enumerate(source_room.get("objects", [])):
                        if obj.get("uid") == uid:
                            source_room["objects"].pop(i)
                            found_in_source = True
                            break
            
            if not found_in_source:
                return False # Object not found in source room

            # Add to destination
            if "objects" not in dest_room:
                dest_room["objects"] = []
            dest_room["objects"].append(obj_to_move)
            
            return True

    # --- Combat State Accessors (Thread-Safe) ---

    def get_combat_state(self, combatant_id: str) -> Optional[Dict[str, Any]]:
        with self.combat_lock:
            return self.combat_state.get(combatant_id)

    def set_combat_state(self, combatant_id: str, data: Dict[str, Any]):
        with self.combat_lock:
            self.combat_state[combatant_id] = data
            
    def remove_combat_state(self, combatant_id: str) -> Optional[Dict[str, Any]]:
        with self.combat_lock:
            return self.combat_state.pop(combatant_id, None)

    def get_all_combat_states(self) -> List[Tuple[str, Dict[str, Any]]]:
        with self.combat_lock:
            return list(self.combat_state.items())
            
    def stop_combat_for_all(self, combatant_id_1: str, combatant_id_2: str):
        with self.combat_lock:
            self.combat_state.pop(combatant_id_1, None)
            self.combat_state.pop(combatant_id_2, None)

    # --- Monster HP Accessors (Thread-Safe) ---
    
    def get_monster_hp(self, monster_uid: str) -> Optional[int]:
        with self.monster_hp_lock:
            return self.runtime_monster_hp.get(monster_uid)

    def set_monster_hp(self, monster_uid: str, hp: int):
        with self.monster_hp_lock:
            self.runtime_monster_hp[monster_uid] = hp
            
    def modify_monster_hp(self, monster_uid: str, max_hp: int, damage: int) -> int:
        with self.monster_hp_lock:
            if monster_uid not in self.runtime_monster_hp:
                self.runtime_monster_hp[monster_uid] = max_hp
            self.runtime_monster_hp[monster_uid] -= damage
            return self.runtime_monster_hp[monster_uid]

    def remove_monster_hp(self, monster_uid: str):
        with self.monster_hp_lock:
            self.runtime_monster_hp.pop(monster_uid, None)

    # --- Defeated Monster Accessors (Thread-Safe) ---
    
    def get_defeated_monster(self, monster_uid: str) -> Optional[Dict[str, Any]]:
        with self.defeated_lock:
            return self.defeated_monsters.get(monster_uid)

    def set_defeated_monster(self, monster_uid: str, data: Dict[str, Any]):
        with self.defeated_lock:
            self.defeated_monsters[monster_uid] = data
            
    def remove_defeated_monster(self, monster_uid: str) -> Optional[Dict[str, Any]]:
        with self.defeated_lock:
            return self.defeated_monsters.pop(monster_uid, None)

    def get_all_defeated_monsters(self) -> List[Tuple[str, Dict[str, Any]]]:
        with self.defeated_lock:
            return list(self.defeated_monsters.items())

    # --- Trade Accessors (Thread-Safe) ---
    
    def get_pending_trade(self, player_name_lower: str) -> Optional[Dict[str, Any]]:
        with self.trade_lock:
            return self.pending_trades.get(player_name_lower)
            
    def set_pending_trade(self, player_name_lower: str, data: Dict[str, Any]):
        with self.trade_lock:
            self.pending_trades[player_name_lower] = data

    def remove_pending_trade(self, player_name_lower: str) -> Optional[Dict[str, Any]]:
        with self.trade_lock:
            return self.pending_trades.pop(player_name_lower, None)

    # ---
    # --- NEW: Grouping Accessors (Thread-Safe)
    # ---
    
    def get_group(self, group_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not group_id: return None
        with self.group_lock:
            return self.active_groups.get(group_id)

    def set_group(self, group_id: str, data: Dict[str, Any]):
        with self.group_lock:
            self.active_groups[group_id] = data
            
    def remove_group(self, group_id: str) -> Optional[Dict[str, Any]]:
        with self.group_lock:
            return self.active_groups.pop(group_id, None)
            
    def get_pending_group_invite(self, player_name_lower: str) -> Optional[Dict[str, Any]]:
        with self.group_lock:
            # Check for and remove expired invites
            invite = self.pending_group_invites.get(player_name_lower)
            if invite and (time.time() - invite.get("time", 0)) > 30:
                self.pending_group_invites.pop(player_name_lower, None)
                return None
            return invite
    
    def set_pending_group_invite(self, player_name_lower: str, data: Dict[str, Any]):
        with self.group_lock:
            self.pending_group_invites[player_name_lower] = data

    def remove_pending_group_invite(self, player_name_lower: str) -> Optional[Dict[str, Any]]:
        with self.group_lock:
            return self.pending_group_invites.pop(player_name_lower, None)

    # ---
    # --- NEW: Band Accessors (Thread-Safe)
    # ---
    
    def get_band(self, band_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not band_id: return None
        with self.band_lock:
            return self.active_bands.get(band_id)

    def set_band(self, band_id: str, data: Dict[str, Any]):
        with self.band_lock:
            self.active_bands[band_id] = data
            
    def remove_band(self, band_id: str) -> Optional[Dict[str, Any]]:
        with self.band_lock:
            return self.active_bands.pop(band_id, None)
            
    # --- NEW: Helper to find band invites on login ---
    def get_band_invite_for_player(self, player_name_lower: str) -> Optional[Dict[str, Any]]:
        """
        Checks all active bands for a pending invite for the player.
        """
        with self.band_lock:
            for band_data in self.active_bands.values():
                if player_name_lower in band_data.get("pending_invites", {}):
                    return band_data
        return None

    # --- Messaging Helpers ---

    def send_message_to_player(self, player_name_lower: str, message: str, msg_type: str = "message"):
        """Emits a message directly to a player's socket."""
        if not self.socketio:
            if config.DEBUG_MODE:
                print(f"[WORLD/SOCKET-WARN] No socketio object. Cannot send message to {player_name_lower}: {message}")
            return

        player_info = self.get_player_info(player_name_lower)
        if player_info:
            sid = player_info.get("sid")
            if sid:
                self.socketio.emit(msg_type, message, to=sid)
            elif config.DEBUG_MODE:
                    print(f"[WORLD/SOCKET-WARN] Player {player_name_lower} has no SID. Cannot send: {message}")
        elif config.DEBUG_MODE:
                print(f"[WORLD/SOCKET-WARN] Player {player_name_lower} not active. Cannot send: {message}")
    
    def broadcast_to_room(self, room_id: str, message: str, msg_type: str, skip_sid: Optional[str] = None):
        """Emits a message to all players in a room, optionally skipping one."""
        if not self.socketio:
            if config.DEBUG_MODE:
                print(f"[WORLD/BROADCAST-WARN] No socketio object. Cannot broadcast to {room_id}: {message}")
            return
        
        if skip_sid:
            self.socketio.emit(msg_type, message, to=room_id, skip_sid=skip_sid)
        else:
            self.socketio.emit(msg_type, message, to=room_id)

    # ---
    # --- NEW: Group/Band Messaging Helpers
    # ---
    
    def send_message_to_group(self, group_id: str, message: str, msg_type: str = "message", skip_player_key: Optional[str] = None):
        """Sends a message to all *online* members of a group."""
        group = self.get_group(group_id)
        if not group:
            return
            
        for member_key in group["members"]:
            if member_key != skip_player_key:
                self.send_message_to_player(member_key, message, msg_type)

    def send_message_to_band(self, band_id: str, message: str, msg_type: str = "message", skip_player_key: Optional[str] = None):
        """Sends a message to all *online* members of a band."""
        band = self.get_band(band_id)
        if not band:
            return
            
        for member_key in band["members"]:
            if member_key != skip_player_key:
                self.send_message_to_player(member_key, message, msg_type)