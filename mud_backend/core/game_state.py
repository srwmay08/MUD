# mud_backend/core/game_state.py
import time
import threading
import copy
import uuid
from mud_backend import config
from typing import Dict, Any, Optional, List, Tuple, Set
from mud_backend.core.game_objects import Player, Room
from mud_backend.core.asset_manager import AssetManager 
from mud_backend.core.events import EventBus # <--- NEW IMPORT

class ShardedStore:
    def __init__(self, num_shards=16):
        self.num_shards = num_shards
        self.shards = [{} for _ in range(num_shards)]
        self.locks = [threading.RLock() for _ in range(num_shards)]

    def _get_shard(self, key: str):
        idx = hash(key) % self.num_shards
        return self.shards[idx], self.locks[idx]

    def get(self, key: str, default=None):
        data, lock = self._get_shard(key)
        with lock:
            return data.get(key, default)

    def set(self, key: str, value: Any):
        data, lock = self._get_shard(key)
        with lock:
            data[key] = value

    def pop(self, key: str, default=None):
        data, lock = self._get_shard(key)
        with lock:
            return data.pop(key, default)
            
    def contains(self, key: str) -> bool:
        data, lock = self._get_shard(key)
        with lock:
            return key in data

    def get_all_items(self) -> List[Tuple[str, Any]]:
        all_items = []
        for i in range(self.num_shards):
            with self.locks[i]:
                all_items.extend(list(self.shards[i].items()))
        return all_items

class World:
    def __init__(self):
        self.socketio = None
        self.app = None 
        self.assets = AssetManager() 
        
        # --- NEW: Event Bus ---
        self.event_bus = EventBus()
        # ----------------------

        self.room_directory_lock = threading.RLock()
        self.active_rooms: Dict[str, Room] = {} 
        
        self.player_directory_lock = threading.RLock()
        self.active_players: Dict[str, Dict[str, Any]] = {}
        
        self.runtime_monster_hp = ShardedStore(num_shards=16)
        self.defeated_monsters = ShardedStore(num_shards=8)
        self.combat_state = ShardedStore(num_shards=32)
        
        self.trade_lock = threading.RLock()
        self.pending_trades: Dict[str, Dict[str, Any]] = {}
        
        self.group_lock = threading.RLock()
        self.active_groups: Dict[str, Dict[str, Any]] = {}
        self.pending_group_invites: Dict[str, Dict[str, Any]] = {}
        
        self.band_lock = threading.RLock()
        self.active_bands: Dict[str, Dict[str, Any]] = {}

        self.index_lock = threading.RLock()
        self.room_players: Dict[str, Set[str]] = {}
        self.active_mob_uids: Set[str] = set()
        self.mob_locations: Dict[str, str] = {}

        self.last_game_tick_time: float = time.time()
        self.tick_interval_seconds: float = config.TICK_INTERVAL_SECONDS
        self.last_monster_tick_time: float = time.time()
        self.game_tick_counter: int = 0
        self.player_timeout_seconds: int = config.PLAYER_TIMEOUT_SECONDS
        self.last_band_payout_time: float = time.time()

    @property
    def game_rooms(self): return self.get_all_rooms()
    @property
    def game_items(self): return self.assets.items
    @property
    def game_monster_templates(self): return self.assets.monster_templates
    @property
    def game_loot_tables(self): return self.assets.loot_tables
    @property
    def game_level_table(self): return self.assets.level_table
    @property
    def game_skills(self): return self.assets.skills
    @property
    def game_criticals(self): return self.assets.criticals
    @property
    def game_quests(self): return self.assets.quests
    @property
    def game_nodes(self): return self.assets.nodes
    @property
    def game_factions(self): return self.assets.factions
    @property
    def game_spells(self): return self.assets.spells
    @property
    def room_templates(self): return self.assets.room_templates
    @property
    def game_spells(self): return self.assets.spells
    @property
    def game_rules(self): return self.assets.combat_rules # <--- NEW

    # --- REFACTORED: Use Dependency Injection ---
    def load_all_data(self, data_source):
        """
        Loads all data using the provided data_source (the db module).
        """
        if data_source is None:
            print("[WORLD ERROR] DataSource is None. Cannot load data.")
            return
        
        # Inject loaders into AssetManager
        self.assets.set_room_loader(data_source.fetch_room_data)
        self.assets.load_all_assets(data_source)
        
        print("[WORLD INIT] Loading active adventuring bands...")
        # We need the raw mongo db object for this specific call if fetch_all_bands expects it
        # Assuming data_source.get_db() returns the mongo client/db object
        self.active_bands = data_source.fetch_all_bands(data_source.get_db())
        print("[WORLD INIT] Initialization complete.")
    # ---------------------------------------------

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
        with self.player_directory_lock:
            return self.active_players.get(player_name_lower)

    def get_player_obj(self, player_name_lower: str) -> Optional['Player']:
        with self.player_directory_lock:
            info = self.active_players.get(player_name_lower)
            if info:
                return info.get("player_obj")
        return None

    def set_player_info(self, player_name_lower: str, data: Dict[str, Any]):
        with self.player_directory_lock:
            self.active_players[player_name_lower] = data
            
    def remove_player(self, player_name_lower: str) -> Optional[Dict[str, Any]]:
        player_obj = self.get_player_obj(player_name_lower)
        if player_obj:
            self.remove_player_from_room_index(player_name_lower, player_obj.current_room_id)

        if player_obj and player_obj.group_id:
            self._handle_player_disconnect_group(player_obj, player_name_lower)
            
        with self.player_directory_lock:
            return self.active_players.pop(player_name_lower, None)

    def _handle_player_disconnect_group(self, player_obj, player_name_lower):
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

    def get_all_players_info(self) -> List[Tuple[str, Dict[str, Any]]]:
        with self.player_directory_lock:
            return list(self.active_players.items())

    def get_player_group_id_on_load(self, player_name_lower: str) -> Optional[str]:
        with self.group_lock:
            for group_id, group_data in self.active_groups.items():
                if player_name_lower in group_data.get("members", []):
                    return group_id
        return None

    # --- Room Factory ---
    def get_active_room_safe(self, room_id: str) -> Optional[Room]:
        with self.room_directory_lock:
            return self.active_rooms.get(room_id)

    def get_room(self, room_id: str) -> Optional[Dict[str, Any]]:
        room_obj = None
        with self.room_directory_lock:
            room_obj = self.active_rooms.get(room_id)
        
        if not room_obj:
            template = self.assets.get_room_template(room_id)
            if template:
                room_obj = self._hydrate_room(template)
                with self.room_directory_lock:
                    self.active_rooms[room_id] = room_obj
        
        if room_obj:
            return room_obj.to_dict()
        return None

    def _hydrate_room(self, template: Dict) -> Room:
        active_objects = []
        room_id = template["room_id"]
        
        for obj_stub in template.get("objects", []):
            node_id = obj_stub.get("node_id")
            monster_id = obj_stub.get("monster_id")
            merged_obj = copy.deepcopy(obj_stub)
            
            if node_id:
                node_template = self.game_nodes.get(node_id)
                if node_template:
                    full_node = copy.deepcopy(node_template)
                    full_node.update(merged_obj)
                    merged_obj = full_node
            elif monster_id:
                uid = merged_obj.get("uid")
                if not uid:
                    uid = uuid.uuid4().hex
                    merged_obj["uid"] = uid
                    
                if self.get_defeated_monster(uid):
                    continue 
                    
                mob_template = self.game_monster_templates.get(monster_id)
                if mob_template:
                    full_mob = copy.deepcopy(mob_template)
                    full_mob.update(merged_obj)
                    merged_obj = full_mob
                    self.register_mob(uid, room_id)
            elif merged_obj.get("is_npc") and not merged_obj.get("uid"):
                 uid = uuid.uuid4().hex
                 merged_obj["uid"] = uid
                 self.register_mob(uid, room_id)

            active_objects.append(merged_obj)
        
        new_active_room = Room(
            room_id=template["room_id"],
            name=template["name"],
            description=template.get("description", ""),
            db_data=template
        )
        new_active_room.objects = active_objects 
        return new_active_room

    def get_all_rooms(self) -> Dict[str, Dict[str, Any]]:
        with self.room_directory_lock:
            all_rooms = copy.deepcopy(self.assets.room_templates)
            for rid, room_obj in self.active_rooms.items():
                all_rooms[rid] = room_obj.to_dict()
            return all_rooms
            
    def update_room_cache(self, room_id: str, room_data: Dict[str, Any]):
        with self.room_directory_lock:
            room_obj = self.active_rooms.get(room_id)
        if room_obj:
            with room_obj.lock:
                room_obj.objects = room_data.get("objects", [])

    def save_room(self, room_obj):
        """Updates the directory and emits a save event."""
        with self.room_directory_lock:
            self.active_rooms[room_obj.room_id] = room_obj
        # --- FIX: Emit event instead of calling db directly ---
        self.event_bus.emit("save_room", room=room_obj)
        # ----------------------------------------------------

    def move_object_between_rooms(self, obj_to_move: Dict, from_room_id: str, to_room_id: str) -> bool:
        with self.room_directory_lock:
            source_room = self.active_rooms.get(from_room_id)
            dest_room = self.active_rooms.get(to_room_id)
            
        if not source_room or not dest_room:
            if not source_room: self.get_room(from_room_id); 
            if not dest_room: self.get_room(to_room_id);
            with self.room_directory_lock:
                source_room = self.active_rooms.get(from_room_id)
                dest_room = self.active_rooms.get(to_room_id)
            if not source_room or not dest_room: return False

        first_lock = source_room if from_room_id < to_room_id else dest_room
        second_lock = dest_room if from_room_id < to_room_id else source_room

        with first_lock.lock:
            with second_lock.lock:
                found_index = -1
                uid = obj_to_move.get("uid")
                for i, obj in enumerate(source_room.objects):
                    if obj is obj_to_move: 
                        found_index = i
                        break
                    if uid and obj.get("uid") == uid:
                        found_index = i
                        break
                if found_index == -1: return False
                real_obj = source_room.objects.pop(found_index)
                dest_room.objects.append(real_obj)
                return True

    # --- Combat/States ---
    def get_combat_state(self, combatant_id: str) -> Optional[Dict[str, Any]]:
        return self.combat_state.get(combatant_id)
    def set_combat_state(self, combatant_id: str, data: Dict[str, Any]):
        self.combat_state.set(combatant_id, data)
    def remove_combat_state(self, combatant_id: str) -> Optional[Dict[str, Any]]:
        return self.combat_state.pop(combatant_id)
    def get_all_combat_states(self) -> List[Tuple[str, Dict[str, Any]]]:
        return self.combat_state.get_all_items()
    def stop_combat_for_all(self, combatant_id_1: str, combatant_id_2: str):
        self.combat_state.pop(combatant_id_1)
        self.combat_state.pop(combatant_id_2)
    def get_monster_hp(self, monster_uid: str) -> Optional[int]:
        return self.runtime_monster_hp.get(monster_uid)
    def set_monster_hp(self, monster_uid: str, hp: int):
        self.runtime_monster_hp.set(monster_uid, hp)
    def modify_monster_hp(self, monster_uid: str, max_hp: int, damage: int) -> int:
        data, lock = self.runtime_monster_hp._get_shard(monster_uid)
        with lock:
            if monster_uid not in data: 
                data[monster_uid] = max_hp
            data[monster_uid] -= damage
            return data[monster_uid]
    def remove_monster_hp(self, monster_uid: str):
        self.runtime_monster_hp.pop(monster_uid)
    def get_defeated_monster(self, monster_uid: str) -> Optional[Dict[str, Any]]:
        return self.defeated_monsters.get(monster_uid)
    def set_defeated_monster(self, monster_uid: str, data: Dict[str, Any]):
        self.defeated_monsters.set(monster_uid, data)
    def remove_defeated_monster(self, monster_uid: str) -> Optional[Dict[str, Any]]:
        return self.defeated_monsters.pop(monster_uid)
    def get_all_defeated_monsters(self) -> List[Tuple[str, Dict[str, Any]]]:
        return self.defeated_monsters.get_all_items()
    
    def get_pending_trade(self, player_name_lower: str) -> Optional[Dict[str, Any]]:
        with self.trade_lock: return self.pending_trades.get(player_name_lower)
    def set_pending_trade(self, player_name_lower: str, data: Dict[str, Any]):
        with self.trade_lock: self.pending_trades[player_name_lower] = data
    def remove_pending_trade(self, player_name_lower: str) -> Optional[Dict[str, Any]]:
        with self.trade_lock: return self.pending_trades.pop(player_name_lower, None)
    
    def get_group(self, group_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not group_id: return None
        with self.group_lock: return self.active_groups.get(group_id)
    def set_group(self, group_id: str, data: Dict[str, Any]):
        with self.group_lock: self.active_groups[group_id] = data
    def remove_group(self, group_id: str) -> Optional[Dict[str, Any]]:
        with self.group_lock: return self.active_groups.pop(group_id, None)
    def get_pending_group_invite(self, player_name_lower: str) -> Optional[Dict[str, Any]]:
        with self.group_lock:
            invite = self.pending_group_invites.get(player_name_lower)
            if invite and (time.time() - invite.get("time", 0)) > 30:
                self.pending_group_invites.pop(player_name_lower, None)
                return None
            return invite
    def set_pending_group_invite(self, player_name_lower: str, data: Dict[str, Any]):
        with self.group_lock: self.pending_group_invites[player_name_lower] = data
    def remove_pending_group_invite(self, player_name_lower: str) -> Optional[Dict[str, Any]]:
        with self.group_lock: return self.pending_group_invites.pop(player_name_lower, None)
    
    def get_band(self, band_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not band_id: return None
        with self.band_lock: return self.active_bands.get(band_id)
    def set_band(self, band_id: str, data: Dict[str, Any]):
        with self.band_lock: self.active_bands[band_id] = data
    def remove_band(self, band_id: str) -> Optional[Dict[str, Any]]:
        with self.band_lock: return self.active_bands.pop(band_id, None)
    def get_band_invite_for_player(self, player_name_lower: str) -> Optional[Dict[str, Any]]:
        with self.band_lock:
            for band_data in self.active_bands.values():
                if player_name_lower in band_data.get("pending_invites", {}):
                    return band_data
        return None

    def send_message_to_player(self, player_name_lower: str, message: str, msg_type: str = "message"):
        if not self.socketio: return
        player_info = self.get_player_info(player_name_lower)
        if player_info:
            sid = player_info.get("sid")
            if sid: self.socketio.emit(msg_type, message, to=sid)
    
    def broadcast_to_room(self, room_id: str, message: str, msg_type: str, skip_sid: Optional[str] = None):
        if not self.socketio: return
        is_flag_checked = msg_type in ["ambient", "ambient_move", "ambient_spawn", "ambient_decay", "combat_death"]
        if not is_flag_checked:
            if skip_sid: self.socketio.emit(msg_type, message, to=room_id, skip_sid=skip_sid)
            else: self.socketio.emit(msg_type, message, to=room_id)
            return
        with self.index_lock:
            players_in_room = self.room_players.get(room_id, set()).copy()
        for player_name in players_in_room:
            player_info = self.get_player_info(player_name)
            if not player_info: continue
            player_obj = player_info.get("player_obj")
            sid = player_info.get("sid")
            if not player_obj or not sid or sid == skip_sid: continue
            if msg_type.startswith("ambient") and player_obj.flags.get("ambient", "on") == "off": continue 
            if msg_type == "combat_death" and player_obj.flags.get("showdeath", "on") == "off": continue 
            self.socketio.emit(msg_type, message, to=sid)
    
    def send_message_to_group(self, group_id: str, message: str, msg_type: str = "message", skip_player_key: Optional[str] = None):
        group = self.get_group(group_id)
        if not group: return
        for member_key in group["members"]:
            if member_key != skip_player_key: self.send_message_to_player(member_key, message, msg_type)

    def send_message_to_band(self, band_id: str, message: str, msg_type: str = "message", skip_player_key: Optional[str] = None):
        band = self.get_band(band_id)
        if not band: return
        for member_key in band["members"]:
            if member_key != skip_player_key: self.send_message_to_player(member_key, message, msg_type)