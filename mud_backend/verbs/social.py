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

@VerbRegistry.register(["invite"])
class Invite(BaseVerb):
    """
    Allows players at a private table to invite others in.
    Usage: INVITE <PLAYER> or INVITE GROUP <PLAYER>
    """
    def execute(self):
        if not getattr(self.room, "is_table", False):
            self.player.send_message("You are not at a private table.")
            return
            
        if not self.args:
            self.player.send_message("Invite whom? (e.g. INVITE <PLAYER> or INVITE GROUP <PLAYER>)")
            return
            
        invite_group = False
        target_name = ""
        
        if self.args[0].lower() == "group" and len(self.args) > 1:
            invite_group = True
            target_name = " ".join(self.args[1:]).lower()
        else:
            target_name = " ".join(self.args).lower()
            
        # Look for player in the room the table exits to (usually 'out')
        outside_room_id = self.room.exits.get("out")
        if not outside_room_id:
            self.player.send_message("There is no one nearby to invite.")
            return
            
        # Check players in outside room
        target_player = None
        players_outside_names = self.world.room_players.get(outside_room_id, set())
        
        # Simple fuzzy match for name
        for name in players_outside_names:
            if name.lower() == target_name or target_name in name.lower().split():
                target_player = self.world.get_player_obj(name)
                break
        
        if not target_player:
            self.player.send_message(f"You don't see '{target_name}' nearby.")
            return
            
        targets_to_invite = [target_player]
        
        if invite_group and target_player.group_id:
            group = self.world.get_group(target_player.group_id)
            if group:
                for member_name in group["members"]:
                    member_obj = self.world.get_player_obj(member_name)
                    if member_obj and member_obj not in targets_to_invite:
                        targets_to_invite.append(member_obj)
        
        invited_names = []
        for p in targets_to_invite:
            if p.name.lower() not in self.room.invited_guests:
                self.room.invited_guests.append(p.name.lower())
                invited_names.append(p.name)
                
                # Send actionable notification to the invited player
                p.send_message(
                    f"{self.player.name} waves to you, inviting you to join them at {self.room.name}. "
                    f"You may now <span class='keyword' data-command='enter {self.room.name}'>ENTER {self.room.name}</span>."
                )
        
        if invited_names:
            self.player.send_message(f"You wave at {', '.join(invited_names)} and invite them to sit with you.")
            self.world.broadcast_to_room(self.room.room_id, f"{self.player.name} invites {', '.join(invited_names)} to the table.", "message", skip_sid=None)
        else:
            self.player.send_message(f"{target_player.name} is already invited.")