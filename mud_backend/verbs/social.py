# mud_backend/verbs/social.py
import random
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.utils import get_stat_bonus

@VerbRegistry.register(["bribe", "threaten", "plead", "flatter"])
class SocialCombat(BaseVerb):
    """
    Handles social interactions (The Social Duel).
    Compares Player Stats vs NPC Resistance.
    """
    
    STATS_MAP = {
        "bribe": {"offense": "INF", "defense": "WIS", "resource": "wealth"},
        "threaten": {"offense": "STR", "defense": "DIS", "resource": None},
        "plead": {"offense": "INF", "defense": "WIS", "resource": None},
        "flatter": {"offense": "INF", "defense": "INT", "resource": None}
    }

    def execute(self):
        if _check_action_roundtime(self.player, action_type="speak"): return
        if not self.args:
            self.player.send_message(f"{self.command.capitalize()} whom?")
            return

        target_name = " ".join(self.args).lower()
        target_npc = None
        
        # Find NPC
        for obj in self.room.objects:
            if obj.get("is_npc") or obj.get("is_monster"):
                if target_name in obj.get("keywords", []) or target_name == obj.get("name", "").lower():
                    target_npc = obj
                    break
        
        if not target_npc:
            self.player.send_message(f"You don't see {target_name} here.")
            return

        action = self.command.lower()
        config = self.STATS_MAP.get(action)
        
        # 1. Resource Check (Bribe)
        if action == "bribe":
            amount = 50 # Default bribe cost, or parse from args
            if self.player.wealth["silvers"] < amount:
                self.player.send_message(f"You don't have enough silver ({amount}) to bribe them.")
                return
            self.player.wealth["silvers"] -= amount
            self.player.send_message(f"You slip {amount} silver to the {target_npc['name']}...")

        # 2. Resolve 'Combat'
        player_stat = self.player.stats.get(config["offense"], 50)
        npc_stat = target_npc.get("stats", {}).get(config["defense"], 50)
        
        # Modifiers
        player_bonus = get_stat_bonus(player_stat, config["offense"], self.player.stat_modifiers)
        npc_bonus = (npc_stat - 50) // 2
        
        roll = random.randint(1, 100)
        result = roll + player_bonus - npc_bonus
        
        # Difficulty check (default 50)
        difficulty = target_npc.get("social_difficulty", 50)
        
        if result >= difficulty:
            self.player.send_message(f"Success! The {target_npc['name']} seems swayed by your {action}.")
            
            # EMIT EVENT for Quest Handler
            # We try 'monster_id' first (standard for NPCs), then 'uid' (standard for runtime objs)
            npc_id = target_npc.get("monster_id") or target_npc.get("uid")
            
            self.world.event_bus.emit("social_success", player=self.player, npc_id=npc_id, action_type=action)
            
            # If not a quest NPC, maybe generic flavor
            if not target_npc.get("quest_giver_ids"):
                self.player.send_message("They nod in agreement, though it achieves little else.")
        else:
            self.player.send_message(f"Failure. The {target_npc['name']} is unimpressed.")
            # Potential consequence: Aggro?
            if action == "threaten" and random.random() < 0.3:
                self.player.send_message("They take offense to your threat!")
                # Trigger combat logic here if desired

        _set_action_roundtime(self.player, 3.0, rt_type="soft")