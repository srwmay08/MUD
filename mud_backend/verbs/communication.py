# mud_backend/verbs/communication.py
import time
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
        
        # Broadcast via Manager (3 room radius)
        self.world.connection_manager.broadcast_to_radius(
            start_room_id=self.player.current_room_id,
            radius=3,
            message=f"{self.player.name} {self.command}s, \"{message}\"",
            msg_type="message", 
            skip_player_name=self.player.name
        )
        
        # Yelling is exhausting
        _set_action_roundtime(self.player, 2.0, rt_type="soft")


# --- SIGNET RING MECHANICS ---

CHANNELS = ["General", "Trade", "Newbie", "OOC", "Guild"]

@VerbRegistry.register(["twist"])
class Twist(BaseVerb):
    """
    Mechanic: TWIST RING
    Activates the ring.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"): return

        target_name = " ".join(self.args).lower()
        
        # Validate they are targeting the ring
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
    """
    Mechanic: TAP RING
    Deactivates the ring.
    """
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
    """
    Mechanic: TURN RING
    Cycles the active channel.
    """
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
    Sends a message to the global channel if the ring is active.
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
        
        # --- Special Handling for Guild Channel ---
        if channel == "Guild":
            # Only send to members of the same group/band/guild
            # Since we don't have a formal "Guild" object separate from Band/Group yet, 
            # we will treat "Guild" channel as Band Chat for now.
            if not self.player.band_id:
                self.player.send_message("You focus on the Guild frequency, but you aren't in a Band (Guild).")
                return
            
            self.world.send_message_to_band(
                self.player.band_id,
                f"[Guild] {self.player.name}: {message}",
                msg_type="band_chat"
            )
            self.player.send_message(f"You focus on the ring (Guild): \"{message}\"")
            _set_action_roundtime(self.player, 1.0, rt_type="soft")
            return

        # --- Global Broadcast for other channels ---
        
        # Format: [General] Player: Message
        formatted_msg = f"<span class='comm-channel'>[{channel}]</span> <span class='comm-name'>{self.player.name}</span>: {message}"
        
        self.player.send_message(f"You focus on the ring ({channel}): \"{message}\"")
        
        # 5. Broadcast Global
        self.world.connection_manager.broadcast_to_world(formatted_msg, "global_chat")
        
        # Anti-spam RT
        _set_action_roundtime(self.player, 1.0, rt_type="soft")