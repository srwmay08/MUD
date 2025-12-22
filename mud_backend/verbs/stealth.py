# mud_backend/verbs/stealth.py
import random
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core.utils import check_action_roundtime, set_action_roundtime
from mud_backend.core.skill_handler import attempt_skill_learning
from mud_backend.core.stealth_system import calculate_hide_result

@VerbRegistry.register(["hide"])
class Hide(BaseVerb):
    """
    Attempts to place the character into stealth.
    Success determined by: Stalking & Hiding Skill + Discipline Bonus + Racial Modifier.
    Gains a significant bonus if no players or monsters are observing.
    """
    def execute(self):
        # 1. Check RT
        if check_action_roundtime(self.player, action_type="physical"):
            return

        if self.player.is_hidden:
            self.player.send_message("You are already hidden.")
            return

        # 2. Use Core Stealth Logic
        success, msg, rt = calculate_hide_result(self.player, self.room, self.world)

        # 3. Result
        # Fetch correct SID to skip broadcast for self
        player_info = self.world.get_player_info(self.player.name.lower())
        sid = player_info.get("sid") if player_info else None

        if success:
            self.player.is_hidden = True
            
            # Send message from core calculation
            self.player.send_message(msg)
            
            # Apply RT
            set_action_roundtime(self.player, float(rt))
            
            # Broadcast to room (Third person)
            self.world.broadcast_to_room(
                self.room.room_id, 
                f"{self.player.name} slips into a hiding place.", 
                "message", 
                skip_sid=sid
            )
            
            # Learning chance
            attempt_skill_learning(self.player, "stalking_and_hiding")
            
        else:
            # Send failure message from core calculation
            self.player.send_message(msg)
            
            # Apply RT
            set_action_roundtime(self.player, float(rt))

            # Broadcast failure
            self.world.broadcast_to_room(
                self.room.room_id, 
                f"{self.player.name} looks around suspiciously and tries to hide, but fails.", 
                "message", 
                skip_sid=sid
            )

@VerbRegistry.register(["unhide"])
class Unhide(BaseVerb):
    def execute(self):
        if not self.player.is_hidden:
            self.player.send_message("You are not hidden.")
            return

        self.player.is_hidden = False
        
        # Fetch correct SID to skip broadcast for self
        player_info = self.world.get_player_info(self.player.name.lower())
        sid = player_info.get("sid") if player_info else None
        
        self.player.send_message("You step out of the shadows.")
        self.world.broadcast_to_room(
            self.room.room_id, 
            f"{self.player.name} reveals themselves from the shadows.", 
            "message", 
            skip_sid=sid
        )

@VerbRegistry.register(["stalk"])
class Stalk(BaseVerb):
    """
    Sets the player to stalk another character.
    If the target moves, the stalker will attempt to follow surreptitiously.
    """
    def execute(self):
        if not self.args:
            if self.player.stalking_target_uid:
                self.player.stalking_target_uid = None
                self.player.send_message("You stop stalking anyone.")
            else:
                self.player.send_message("Stalk whom?")
            return

        target_name = " ".join(self.args).lower()
        
        # Look for target in room
        target_obj = self.world.get_player_obj(target_name)
        
        if not target_obj or target_obj.current_room_id != self.room.room_id:
            self.player.send_message(f"You do not see {target_name} here to stalk.")
            return
            
        if target_obj.name.lower() == self.player.name.lower():
            self.player.send_message("You cannot stalk yourself.")
            return

        # Determine visibility
        if target_obj.is_hidden:
            # Must detect them to stalk
            if target_obj.uid not in self.player.detected_hiders:
                self.player.send_message(f"You do not see {target_name} here.")
                return

        self.player.stalking_target_uid = target_obj.uid
        self.player.send_message(f"You begin to secretly stalk {target_obj.name}.")

@VerbRegistry.register(["sneak"])
class Sneak(BaseVerb):
    """
    Wrapper verb that triggers the Move verb with sneak_override=True.
    Usage: SNEAK NORTH, SNEAK <dir>
    """
    def execute(self):
        # We need to import Move locally to avoid circular dependency loop at top level
        from mud_backend.verbs.movement import Move as MoveVerb
        
        if not self.args:
            self.player.send_message("Sneak where?")
            return
            
        # Delegate to Move verb with sneak flag
        # We reuse the arguments passed to sneak (e.g., "north")
        move_instance = MoveVerb(self.world, self.player, self.room, self.args)
        
        # Pass the override flag.
        move_instance.force_sneak = True
        move_instance.execute()