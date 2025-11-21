# mud_backend/core/managers.py
import threading
import copy
import uuid
from typing import Dict, Any, Optional, Set, List, Union, TYPE_CHECKING
from mud_backend.core.game_objects import Room, Player

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

class ConnectionManager:
    """Handles SocketIO connections and broadcasting."""
    def __init__(self, world: 'World'):
        self.world = world
        self.socketio = None # Injected later
        
    def send_to_player(self, player_name_lower: str, message: str, msg_type: str = "message"):
        if not self.socketio: return
        player_info = self.world.get_player_info(player_name_lower)
        if player_info:
            sid = player_info.get("sid")
            if sid: self.socketio.emit(msg_type, message, to=sid)

    def broadcast_to_room(self, room_id: str, message: str, msg_type: str, skip_sid: Optional[Union[str, List[str], Set[str]]] = None):
        if not self.socketio: return
        
        # Normalize skip_sid to a set for efficient lookup/handling
        skip_sids_set = set()
        if skip_sid:
            if isinstance(skip_sid, str):
                skip_sids_set.add(skip_sid)
            elif isinstance(skip_sid, (list, set, tuple)):
                skip_sids_set.update(skip_sid)
        
        # Flag check logic (ambient/combat toggles)
        is_flag_checked = msg_type in ["ambient", "ambient_move", "ambient_spawn", "ambient_decay", "combat_death"]
        
        if not is_flag_checked:
            # Convert to list for Flask-SocketIO which expects list or str
            skip_list = list(skip_sids_set)
            if skip_list: 
                self.socketio.emit(msg_type, message, to=room_id, skip_sid=skip_list)
            else: 
                self.socketio.emit(msg_type, message, to=room_id)
            return

        # If checking flags, iterate players in room
        players_in_room = self.world.entity_manager.get_players_in_room(room_id)
        
        for player_name in players_in_room:
            player_info = self.world.get_player_info(player_name)
            if not player_info: continue
            
            player_obj = player_info.get("player_obj")
            sid = player_info.get("sid")
            
            # Check against the set
            if not player_obj or not sid or sid in skip_sids_set: continue
            
            if msg_type.startswith("ambient") and player_obj.flags.get("ambient", "on") == "off": continue 
            if msg_type == "combat_death" and player_obj.flags.get("showdeath", "on") == "off": continue 
            
            self.socketio.emit(msg_type, message, to=sid)


class RoomManager:
    """Handles Room loading, hydration, and active room cache."""
    def __init__(self, world: 'World'):
        self.world = world
        self.active_rooms: Dict[str, Room] = {}
        self.directory_lock = threading.RLock()

    def get_active_room_safe(self, room_id: str) -> Optional[Room]:
        with self.directory_lock:
            return self.active_rooms.get(room_id)

    def get_room(self, room_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves room data. If not active, hydrates it from Assets/DB.
        Returns dict representation for backward compatibility.
        """
        room_obj = None
        with self.directory_lock:
            room_obj = self.active_rooms.get(room_id)
        
        if not room_obj:
            # Load template
            template = self.world.assets.get_room_template(room_id)
            if template:
                room_obj = self._hydrate_room(template)
                with self.directory_lock:
                    self.active_rooms[room_id] = room_obj
        
        if room_obj:
            return room_obj.to_dict()
        return None

    def _hydrate_room(self, template: Dict) -> Room:
        active_objects = []
        room_id = template["room_id"]
        
        # Hydrate objects within the room
        for obj_stub in template.get("objects", []):
            node_id = obj_stub.get("node_id")
            monster_id = obj_stub.get("monster_id")
            merged_obj = copy.deepcopy(obj_stub)
            
            if node_id:
                node_template = self.world.assets.nodes.get(node_id)
                if node_template:
                    full_node = copy.deepcopy(node_template)
                    full_node.update(merged_obj)
                    merged_obj = full_node
            elif monster_id:
                uid = merged_obj.get("uid")
                if not uid:
                    uid = uuid.uuid4().hex
                    merged_obj["uid"] = uid
                
                # Check if defeated
                if self.world.get_defeated_monster(uid):
                    continue 
                    
                mob_template = self.world.assets.monster_templates.get(monster_id)
                if mob_template:
                    full_mob = copy.deepcopy(mob_template)
                    full_mob.update(merged_obj)
                    merged_obj = full_mob
                    # Register in Entity/Spatial Manager
                    self.world.entity_manager.register_mob(uid, room_id)
            
            elif merged_obj.get("is_npc") and not merged_obj.get("uid"):
                 uid = uuid.uuid4().hex
                 merged_obj["uid"] = uid
                 self.world.entity_manager.register_mob(uid, room_id)

            active_objects.append(merged_obj)
        
        new_room = Room(
            room_id=template["room_id"],
            name=template["name"],
            description=template.get("description", ""),
            db_data=template
        )
        new_room.objects = active_objects 
        return new_room

    def save_room(self, room_obj: Room):
        with self.directory_lock:
            self.active_rooms[room_obj.room_id] = room_obj
        self.world.event_bus.emit("save_room", room=room_obj)


class EntityManager:
    """Handles Mob/Player tracking and spatial indexing."""
    def __init__(self, world: 'World'):
        self.world = world
        self.index_lock = threading.RLock()
        self.room_players: Dict[str, Set[str]] = {} # room_id -> set(player_names)
        self.active_mob_uids: Set[str] = set()
        self.mob_locations: Dict[str, str] = {} # mob_uid -> room_id

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

    def add_player_to_room(self, player_name: str, room_id: str):
        name = player_name.lower()
        with self.index_lock:
            if room_id not in self.room_players:
                self.room_players[room_id] = set()
            self.room_players[room_id].add(name)

    def remove_player_from_room(self, player_name: str, room_id: str):
        name = player_name.lower()
        with self.index_lock:
            if room_id in self.room_players:
                self.room_players[room_id].discard(name)
                if not self.room_players[room_id]:
                    del self.room_players[room_id]

    def get_players_in_room(self, room_id: str) -> Set[str]:
        with self.index_lock:
            return self.room_players.get(room_id, set()).copy()