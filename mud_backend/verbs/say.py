# mud_backend/verbs/say.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry

@VerbRegistry.register(["say"])
class Say(BaseVerb):
    """
    Handles the 'say' command.
    Respects ignore lists.
    """
    
    def execute(self):
        if not self.args:
            self.player.send_message("What do you want to say?")
            return

        message = " ".join(self.args)
        self.player.send_message(f"You say, \"{message}\"")
        
        # Check for ignores in the room
        players_in_room = self.world.entity_manager.get_players_in_room(self.room.room_id)
        skip_sids = {self.player.uid} # Always skip self
        
        for p_name in players_in_room:
            p_info = self.world.get_player_info(p_name)
            if not p_info: continue
            
            p_obj = p_info.get("player_obj")
            if p_obj and p_obj.is_ignoring(self.player.name):
                sid = p_info.get("sid")
                if sid: skip_sids.add(sid)
        
        self.world.broadcast_to_room(
            self.room.room_id, 
            f"{self.player.name} says, \"{message}\"", 
            "message", 
            skip_sid=list(skip_sids)
        )