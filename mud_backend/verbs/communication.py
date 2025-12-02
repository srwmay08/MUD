# mud_backend/verbs/communication.py
import time
from collections import deque
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.registry import VerbRegistry

# --- HELPERS ---

def _find_item_worn(player, target_name: str) -> str | None:
    """Finds an item worn by the player matching the name."""
    for slot, item_id in player.worn_items.items():
        if item_id:
            item_data = player.world.game_items.get(item_id)
            if item_data:
                if (target_name == item_data.get("name", "").lower() or 
                    target_name in item_data.get("keywords", [])):
                    return item_id
    return None

# --- AREA COMMUNICATION ---

@VerbRegistry.register(["yell", "shout"]) 
class Yell(BaseVerb):
    """
    Broadcasts a message to rooms within a 3-movement radius.
    Outdoor <-> Indoor transitions reduce the range by 1.
    Ignores apply.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="speak"):
            return

        if not self.args:
            self.player.send_message(f"What do you want to {self.command}?")
            return

        message = " ".join(self.args)
        
        # Feedback to self
        self.player.send_message(f"You {self.command} loudly, \"{message}\"")
        
        # BFS to find rooms in range (Radius 3)
        radius = 3
        start_room_id = self.player.current_room_id
        rooms_in_range = set()
        queue = deque([(start_room_id, 0)])
        visited_costs = {start_room_id: 0}
        
        while queue:
            curr_id, curr_cost = queue.popleft()
            if curr_cost <= radius: rooms_in_range.add(curr_id)
            if curr_cost >= radius: continue

            curr_room = self.world.room_manager.get_room(curr_id)
            if not curr_room: continue
            is_curr_outdoor = curr_room.get("is_outdoor", False)
            
            for direction, next_room_id in curr_room.get("exits", {}).items():
                next_room = self.world.room_manager.get_room(next_room_id)
                if not next_room: continue
                is_next_outdoor = next_room.get("is_outdoor", False)
                move_cost = 1
                if is_curr_outdoor != is_next_outdoor: move_cost += 1
                new_total_cost = curr_cost + move_cost
                
                if next_room_id not in visited_costs or new_total_cost < visited_costs[next_room_id]:
                    visited_costs[next_room_id] = new_total_cost
                    queue.append((next_room_id, new_total_cost))

        # Broadcast with Ignore Check
        all_players = self.world.get_all_players_info()
        sender_name = self.player.name
        
        for p_name, p_info in all_players:
            if p_name == sender_name.lower(): continue
            
            p_room_id = p_info.get("current_room_id")
            if p_room_id in rooms_in_range:
                player_obj = p_info.get("player_obj")
                # Check Ignore
                if player_obj and player_obj.is_ignoring(sender_name):
                    continue
                    
                sid = p_info.get("sid")
                if sid:
                    self.world.socketio.emit("message", f"{sender_name} {self.command}s, \"{message}\"", to=sid)
        
        # Yelling is exhausting
        _set_action_roundtime(self.player, 2.0, rt_type="soft")


# --- SIGNET RING MECHANICS ---

CHANNELS = ["General", "Trade", "Newbie", "OOC", "Guild"]

@VerbRegistry.register(["twist"])
class Twist(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"): return

        target_name = " ".join(self.args).lower()
        if "ring" not in target_name and "signet" not in target_name:
            self.player.send_message("Twist what?")
            return

        item_id = _find_item_worn(self.player, "signet")
        if not item_id:
            self.player.send_message("You aren't wearing a signet ring to twist.")
            return

        if self.player.flags.get('comm_ring_active'):
            self.player.send_message("The ring is already active and humming.")
            return

        self.player.flags['comm_ring_active'] = True
        
        self.player.send_message("You twist the outer band of your iron signet. It clicks satisfyingly into place.")
        self.player.send_message("The ring begins to hum with a faint vibration.")
        self.world.broadcast_to_room(
            self.room.room_id, 
            f"{self.player.name} twists the band of their iron ring.", 
            "message", 
            skip_sid=self.player.uid
        )
        _set_action_roundtime(self.player, 1.0)

@VerbRegistry.register(["tap"])
class Tap(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"): return

        target_name = " ".join(self.args).lower()
        if "ring" not in target_name and "signet" not in target_name:
            self.player.send_message("Tap what?")
            return

        item_id = _find_item_worn(self.player, "signet")
        if not item_id:
            self.player.send_message("You aren't wearing a signet ring.")
            return

        if not self.player.flags.get('comm_ring_active'):
            self.player.send_message("The ring is already dormant.")
            return

        self.player.flags['comm_ring_active'] = False
        self.player.send_message("You tap your iron signet. The humming fades as the runes go dormant.")
        _set_action_roundtime(self.player, 0.5)

@VerbRegistry.register(["turn"])
class Turn(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"): return

        target_name = " ".join(self.args).lower()
        if "ring" not in target_name and "signet" not in target_name:
            self.player.send_message("Turn what?")
            return

        item_id = _find_item_worn(self.player, "signet")
        if not item_id:
            self.player.send_message("You aren't wearing a signet ring.")
            return

        # Cycle Channel
        current_idx = self.player.flags.get('comm_channel_idx', 0)
        next_idx = (current_idx + 1) % len(CHANNELS)
        self.player.flags['comm_channel_idx'] = next_idx
        
        channel_name = CHANNELS[next_idx]
        self.player.send_message(f"You turn the dial on your signet. It locks onto the **{channel_name}** frequency.")
        _set_action_roundtime(self.player, 0.5)


@VerbRegistry.register(["focus", "send"])
class Focus(BaseVerb):
    """
    Mechanic: FOCUS <message>
    Sends a message to the global channel. Ignores apply.
    """
    def execute(self):
        # 1. Check if wearing ring
        item_id = _find_item_worn(self.player, "signet")
        if not item_id:
            self.player.send_message("You focus your mind... but without a Signet of Communion, nothing happens.")
            return

        if not self.args:
            self.player.send_message("What message do you wish to send?")
            return

        # 2. Check if active
        if not self.player.flags.get('comm_ring_active'):
            self.player.send_message("You try to send a thought, but the ring feels cold and dormant.")
            self.player.send_message("(You must **TWIST** the ring to activate it.)")
            return

        # 3. Get Channel
        idx = self.player.flags.get('comm_channel_idx', 0)
        if idx >= len(CHANNELS): idx = 0
        channel = CHANNELS[idx]
        message = " ".join(self.args)
        sender_name = self.player.name

        # --- Special Handling for Guild Channel ---
        if channel == "Guild":
            if not self.player.band_id:
                self.player.send_message("You focus on the Guild frequency, but you aren't in a Band (Guild).")
                return
            self.world.send_message_to_band(
                self.player.band_id,
                f"[Guild] {sender_name}: {message}",
                msg_type="band_chat"
            )
            self.player.send_message(f"You focus on the ring (Guild): \"{message}\"")
            _set_action_roundtime(self.player, 1.0, rt_type="soft")
            return

        # --- Global Broadcast with Ignore Check ---
        formatted_msg = f"<span class='comm-channel'>[{channel}]</span> <span class='comm-name'>{sender_name}</span>: {message}"
        self.player.send_message(f"You focus on the ring ({channel}): \"{message}\"")
        
        all_players = self.world.get_all_players_info()
        for p_name, p_info in all_players:
            if p_name == sender_name.lower(): continue
            
            player_obj = p_info.get("player_obj")
            if player_obj and player_obj.is_ignoring(sender_name):
                continue
                
            sid = p_info.get("sid")
            if sid:
                self.world.socketio.emit("global_chat", formatted_msg, to=sid)
        
        _set_action_roundtime(self.player, 1.0, rt_type="soft")