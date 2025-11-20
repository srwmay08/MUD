# mud_backend/core/game_state.py
# FULL FILE REPLACEMENT
import time
import threading
import copy
import uuid
from mud_backend import config
from typing import Dict, Any, Optional, List, Tuple, Set
from mud_backend.core import db
from mud_backend.core.game_objects import Player, Room

class World:
    """
    Holds all mutable game state and provides thread-safe
    methods for accessing and modifying it.
    """
    def __init__(self):
        self.socketio = None
        self.app = None 
        
        # --- State Dictionaries ---
        self.runtime_monster_hp: Dict[str, int] = {}
        self.defeated_monsters: Dict[str, Dict[str, Any]] = {}
        
        # --- PHASE 2: Instance Separation ---
        # active_rooms: Holds instantiated Room objects (Active state)
        self.active_rooms: Dict[str, Room] = {} 
        
        # room_templates: Holds static JSON dicts (Templates)
        self.room_templates: Dict[str, Dict[str, Any]] = {}
        # ------------------------------------

        self.active_players: Dict[str, Dict[str, Any]] = {}
        self.combat_state: Dict[str, Dict[str, Any]] = {}
        self.pending_trades: Dict[str, Dict[str, Any]] = {}
        self.active_groups: Dict[str, Dict[str, Any]] = {}
        self.pending_group_invites: Dict[str, Dict[str, Any]] = {}
        self.active_bands: Dict[str, Dict[str, Any]] = {}

        # --- Phase 1: Spatial & AI Indices ---
        self.room_players: Dict[str, Set[str]] = {}
        self.active_mob_uids: Set[str] = set()
        self.mob_locations: Dict[str, str] = {}

        # --- Global Data Caches ---
        self.game_monster_templates: Dict[str, Dict] = {}
        self.game_loot_tables: Dict[str, List] = {}
        self.game_items: Dict[str, Dict] = {}
        self.game_level_table: List[int] = []
        self.game_skills: Dict[str, Dict] = {}
        self.game_criticals: Dict[str, Any] = {}
        self.game_quests: Dict[str, Any] = {}
        self.game_nodes: Dict[str, Any] = {} 
        self.game_factions: Dict[str, Any] = {}
        self.game_spells: Dict[str, Any] = {}

        # --- Timers ---
        self.last_game_tick_time: float = time.time()
        self.tick_interval_seconds: float = config.TICK_INTERVAL_SECONDS
        self.last_monster_tick_time: float = time.time()
        self.game_tick_counter: int = 0
        self.player_timeout_seconds: int = config.PLAYER_TIMEOUT_SECONDS
        self.last_band_payout_time: float = time.time()

        # --- Locks ---
        self.player_lock = threading.RLock()
        self.combat_lock = threading.RLock()
        self.trade_lock = threading.RLock()
        self.room_lock = threading.RLock()
        self.monster_hp_lock = threading.RLock()
        self.defeated_lock = threading.RLock()
        self.group_lock = threading.RLock()
        self.band_lock = threading.RLock()
        self.index_lock = threading.RLock()

    def load_all_data(self, database):
        if database is None:
            print("[WORLD ERROR] Database is None. Cannot load data.")
            return
            
        print("[WORLD INIT] Loading all room templates...")
        # Load into templates, NOT active rooms
        self.room_templates = db.fetch_all_rooms()
        
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
        print("[WORLD INIT] Loading all spells...")
        self.game_spells = db.fetch_all_spells()
        print("[WORLD INIT] Loading all adventuring bands...")
        self.active_bands = db.fetch_all_bands(database)
        print("[WORLD INIT] Data loaded.")

    # --- Index Management ---
    def register_mob(self, uid: str, room_id: str):
        with self.index_lock:
            self.active_mob_uids.add(uid)
            self.mob_locations[uid] = room_id

    def unregister_mob(self, uid: str):
        with self.index_lock:
            self.active_mob_uids.discard(uid)
            self.mob_locations.pop(uid, None)

    def update_mob_location(self, uid: str, new_room_id: str):
        with self.index_lock:
            if uid in self.active_mob_uids:
                self.mob_locations[uid] = new_room_id

    def add_player_to_room_index(self, player_name_lower: str, room_id: str):
        with self.index_lock:
            if room_id not in self.room_players:
                self.room_players[room_id] = set()
            self.room_players[room_id].add(player_name_lower)

    def remove_player_from_room_index(self, player_name_lower: str, room_id: str):
        with self.index_lock:
            if room_id in self.room_players:
                self.room_players[room_id].discard(player_name_lower)
                if not self.room_players[room_id]:
                    del self.room_players[room_id]

    # --- Player Management ---
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
        player_obj = self.get_player_obj(player_name_lower)
        
        if player_obj:
            self.remove_player_from_room_index(player_name_lower, player_obj.current_room_id)

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
            
        with self.player_lock:
            return self.active_players.pop(player_name_lower, None)

    def get_all_players_info(self) -> List[Tuple[str, Dict[str, Any]]]:
        with self.player_lock:
            return list(self.active_players.items())

    def get_player_group_id_on_load(self, player_name_lower: str) -> Optional[str]:
        with self.group_lock:
            for group_id, group_data in self.active_groups.items():
                if player_name_lower in group_data.get("members", []):
                    return group_id
        return None

    # ---
    # --- PHASE 2: Room Factory / Hydration ---
    # ---
    def get_room(self, room_id: str) -> Optional[Dict[str, Any]]:
        """
        Returns a DICT representing the room. 
        If it's an ActiveRoom, returns its current state.
        If not active, instantiates it from Template.
        """
        with self.room_lock:
            # 1. Check Active Rooms (Cache)
            if room_id in self.active_rooms:
                return self.active_rooms[room_id].to_dict()
            
            # 2. Check Templates
            template = self.room_templates.get(room_id)
            if not template:
                # Fallback: Lazy Load from DB
                template = db.fetch_room_data(room_id)
                if template and template.get("room_id") != "void":
                    self.room_templates[room_id] = template
            
            if template:
                # 3. Hydrate / Instantiate Active Room
                # Deep copy the objects list so we don't mutate the template
                active_objects = []
                for obj_stub in template.get("objects", []):
                    
                    node_id = obj_stub.get("node_id")
                    monster_id = obj_stub.get("monster_id")
                    
                    merged_obj = copy.deepcopy(obj_stub)
                    
                    # A. Hydrate Nodes
                    if node_id:
                        node_template = self.game_nodes.get(node_id)
                        if node_template:
                            # Merge: template first, then stub overrides (like state)
                            full_node = copy.deepcopy(node_template)
                            full_node.update(merged_obj)
                            merged_obj = full_node
                    
                    # B. Hydrate Monsters/NPCs
                    elif monster_id:
                        # Check if this specific UID is dead
                        uid = merged_obj.get("uid")
                        if not uid:
                            # Generate persistent UID for this instance if missing
                            uid = uuid.uuid4().hex
                            merged_obj["uid"] = uid
                            
                        if self.get_defeated_monster(uid):
                            continue # Skip dead mobs
                            
                        mob_template = self.game_monster_templates.get(monster_id)
                        if mob_template:
                            full_mob = copy.deepcopy(mob_template)
                            full_mob.update(merged_obj)
                            merged_obj = full_mob
                            
                            # Register in AI Index
                            self.register_mob(uid, room_id)
                            
                    # C. Ensure NPC UIDs
                    elif merged_obj.get("is_npc") and not merged_obj.get("uid"):
                         uid = uuid.uuid4().hex
                         merged_obj["uid"] = uid
                         self.register_mob(uid, room_id)

                    active_objects.append(merged_obj)
                
                # Create the ActiveRoom Object
                new_active_room = Room(
                    room_id=template["room_id"],
                    name=template["name"],
                    description=template.get("description", ""),
                    db_data=template
                )
                new_active_room.objects = active_objects # Assign hydrated objects
                
                self.active_rooms[room_id] = new_active_room
                
                return new_active_room.to_dict()

        return None

    def get_all_rooms(self) -> Dict[str, Dict[str, Any]]:
        """
        Returns a dict of ALL rooms (Active + Templates).
        Used for global iterations (like AI checks).
        """
        with self.room_lock:
            # Start with templates
            all_rooms = copy.deepcopy(self.room_templates)
            # Overlay active rooms
            for rid, room_obj in self.active_rooms.items():
                all_rooms[rid] = room_obj.to_dict()
            return all_rooms
            
    def update_room_cache(self, room_id: str, room_data: Dict[str, Any]):
        # Phase 2: We update the ActiveRoom object
        with self.room_lock:
            if room_id in self.active_rooms:
                room_obj = self.active_rooms[room_id]
                # Update fields
                room_obj.objects = room_data.get("objects", [])
                # (Add other fields if needed)

    def save_room(self, room_obj):
        # Update the ActiveRoom in memory
        with self.room_lock:
            self.active_rooms[room_obj.room_id] = room_obj
        # Save to DB (Persistent World)
        db.save_room_state(room_obj) 

    def move_object_between_rooms(self, obj_to_move: Dict, from_room_id: str, to_room_id: str) -> bool:
        with self.room_lock:
            # Force hydration of both rooms
            source_data = self.get_room(from_room_id)
            dest_data = self.get_room(to_room_id)
            
            if not source_data or not dest_data: return False
            
            source_room = self.active_rooms[from_room_id]
            dest_room = self.active_rooms[to_room_id]

            # Find object in source
            found_index = -1
            uid = obj_to_move.get("uid")
            
            for i, obj in enumerate(source_room.objects):
                if obj is obj_to_move: # Identity check
                    found_index = i
                    break
                if uid and obj.get("uid") == uid:
                    found_index = i
                    break
            
            if found_index == -1:
                return False

            # Move
            real_obj = source_room.objects.pop(found_index)
            dest_room.objects.append(real_obj)
            
            return True

    # --- Combat, Trade, Groups (Unchanged) ---
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
    
    def get_pending_trade(self, player_name_lower: str) -> Optional[Dict[str, Any]]:
        with self.trade_lock:
            return self.pending_trades.get(player_name_lower)
            
    def set_pending_trade(self, player_name_lower: str, data: Dict[str, Any]):
        with self.trade_lock:
            self.pending_trades[player_name_lower] = data

    def remove_pending_trade(self, player_name_lower: str) -> Optional[Dict[str, Any]]:
        with self.trade_lock:
            return self.pending_trades.pop(player_name_lower, None)
    
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
            
    def get_band_invite_for_player(self, player_name_lower: str) -> Optional[Dict[str, Any]]:
        with self.band_lock:
            for band_data in self.active_bands.values():
                if player_name_lower in band_data.get("pending_invites", {}):
                    return band_data
        return None

    def send_message_to_player(self, player_name_lower: str, message: str, msg_type: str = "message"):
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
        if not self.socketio:
            if config.DEBUG_MODE:
                print(f"[WORLD/BROADCAST-WARN] No socketio object. Cannot broadcast to {room_id}: {message}")
            return
        
        # Flag Check
        is_flag_checked = msg_type in ["ambient", "ambient_move", "ambient_spawn", "ambient_decay", "combat_death"]
        
        if not is_flag_checked:
            if skip_sid:
                self.socketio.emit(msg_type, message, to=room_id, skip_sid=skip_sid)
            else:
                self.socketio.emit(msg_type, message, to=room_id)
            return

        # Spatial Index Check
        with self.index_lock:
            players_in_room = self.room_players.get(room_id, set()).copy()
        
        for player_name in players_in_room:
            player_info = self.get_player_info(player_name)
            if not player_info: continue
            
            player_obj = player_info.get("player_obj")
            sid = player_info.get("sid")
            
            if not player_obj or not sid or sid == skip_sid:
                continue

            if msg_type.startswith("ambient") and player_obj.flags.get("ambient", "on") == "off":
                continue 
            
            if msg_type == "combat_death" and player_obj.flags.get("showdeath", "on") == "off":
                continue 
                
            self.socketio.emit(msg_type, message, to=sid)
    
    def send_message_to_group(self, group_id: str, message: str, msg_type: str = "message", skip_player_key: Optional[str] = None):
        group = self.get_group(group_id)
        if not group:
            return
            
        for member_key in group["members"]:
            if member_key != skip_player_key:
                self.send_message_to_player(member_key, message, msg_type)

    def send_message_to_band(self, band_id: str, message: str, msg_type: str = "message", skip_player_key: Optional[str] = None):
        band = self.get_band(band_id)
        if not band:
            return
            
        for member_key in band["members"]:
            if member_key != skip_player_key:
                self.send_message_to_player(member_key, message, msg_type)