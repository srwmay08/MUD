# mud_backend/verbs/who.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry

@VerbRegistry.register(["who", "online"])
class Who(BaseVerb):
    """
    Shows a list of currently online players.
    """
    def execute(self):
        active_players = self.world.get_all_players_info()
        
        # Filter invisible admins unless the looker is an admin
        visible_players = []
        for name, info in active_players:
            p_obj = info.get("player_obj")
            if not p_obj: continue
            
            # Skip if invisible and viewer is not admin
            if p_obj.flags.get("invisible") == "on" and not self.player.is_admin:
                continue
                
            visible_players.append(p_obj)
            
        visible_players.sort(key=lambda p: p.level, reverse=True)
        
        self.player.send_message("\n--- Citizens of Aethelgard ---")
        
        for p in visible_players:
            flags = []
            if p.is_admin: flags.append("[ADMIN]")
            if p.flags.get("idlekick") == "off": flags.append("[AFK]")
            
            # Check relationships
            if self.player.is_friend(p.name): flags.append("[FRIEND]")
            if self.player.is_ignoring(p.name): flags.append("[IGNORED]")
            
            flag_str = " ".join(flags)
            
            # Format: [Lvl 50] Sevax [ADMIN] - Human
            row = f"[Lvl {p.level:<2}] {p.name} {flag_str}"
            self.player.send_message(row)
            
        self.player.send_message(f"\nTotal Online: {len(visible_players)}")