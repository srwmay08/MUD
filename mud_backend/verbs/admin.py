# mud_backend/verbs/admin.py
import time
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend import config
from mud_backend.core import db

@VerbRegistry.register(["teleport", "goto_player"], admin_only=True)
class Teleport(BaseVerb):
    def execute(self):
        if not self.args:
            self.player.send_message("Usage: TELEPORT <room_id> | <player_name>")
            return
        
        target = " ".join(self.args)
        
        # 1. Try Room ID
        room = self.world.get_room(target)
        if room:
            self.player.move_to_room(target, "You fade out and reappear elsewhere.")
            return

        # 2. Try Player
        target_player = self.world.get_player_obj(target.lower())
        if target_player:
            self.player.move_to_room(target_player.current_room_id, f"You teleport to {target_player.name}.")
            return
            
        self.player.send_message("Target not found.")

@VerbRegistry.register(["summon"], admin_only=True)
class Summon(BaseVerb):
    def execute(self):
        if not self.args:
            self.player.send_message("Summon who?")
            return
        
        target_name = " ".join(self.args).lower()
        target_player = self.world.get_player_obj(target_name)
        
        if not target_player:
            self.player.send_message("Player not found.")
            return
            
        target_player.move_to_room(self.player.current_room_id, "You are magically summoned!")
        self.player.send_message(f"You summoned {target_player.name}.")

@VerbRegistry.register(["wiz", "invis", "inviz"], admin_only=True)
class Wiz(BaseVerb):
    def execute(self):
        current = self.player.flags.get("invisible", "off")
        if current == "off":
            self.player.flags["invisible"] = "on"
            self.player.send_message("You fade from sight (Admin Invisibility ON).")
            # Broadcast disappearance
            self.world.broadcast_to_room(self.room.room_id, f"{self.player.name} fades into thin air.", "ambient")
        else:
            self.player.flags["invisible"] = "off"
            self.player.send_message("You reappear (Admin Invisibility OFF).")
            self.world.broadcast_to_room(self.room.room_id, f"{self.player.name} appears out of thin air.", "ambient")

@VerbRegistry.register(["restore", "heal_target"], admin_only=True)
class Restore(BaseVerb):
    def execute(self):
        target = self.player
        if self.args:
            name = " ".join(self.args).lower()
            found = self.world.get_player_obj(name)
            if found: target = found
            else: 
                self.player.send_message("Player not found.")
                return

        target.hp = target.max_hp
        target.mana = target.max_mana
        target.stamina = target.max_stamina
        target.spirit = target.max_spirit
        target.wounds = {}
        target.status_effects = []
        target.con_lost = 0
        target.death_sting_points = 0
        
        target.send_message("You feel a divine energy fully restore you.")
        if target != self.player:
            self.player.send_message(f"You restored {target.name}.")

@VerbRegistry.register(["force"], admin_only=True)
class Force(BaseVerb):
    def execute(self):
        if len(self.args) < 2:
            self.player.send_message("Usage: FORCE <player> <command>")
            return
            
        target_name = self.args[0].lower()
        command_str = " ".join(self.args[1:])
        
        target_player = self.world.get_player_obj(target_name)
        if not target_player:
            self.player.send_message("Player not found.")
            return
            
        self.player.send_message(f"Forcing {target_player.name} to: {command_str}")
        target_player.command_queue.append(command_str)

@VerbRegistry.register(["kick"], admin_only=True)
class Kick(BaseVerb):
    def execute(self):
        if not self.args: return
        target_name = self.args[0].lower()
        target_player = self.world.get_player_obj(target_name)
        
        if target_player:
            # Get SID
            p_info = self.world.get_player_info(target_name)
            if p_info and p_info.get("sid"):
                self.world.socketio.disconnect(p_info["sid"])
                self.player.send_message(f"Kicked {target_player.name}.")
            else:
                self.player.send_message("Could not find socket connection.")
        else:
            self.player.send_message("Player not active.")

@VerbRegistry.register(["freeze"], admin_only=True)
class Freeze(BaseVerb):
    def execute(self):
        if not self.args: return
        target_name = self.args[0].lower()
        target_player = self.world.get_player_obj(target_name)
        
        if target_player:
            current = target_player.flags.get("frozen", "off")
            if current == "off":
                target_player.flags["frozen"] = "on"
                self.player.send_message(f"{target_player.name} is now frozen.")
                target_player.send_message("You have been frozen by an administrator.")
            else:
                target_player.flags["frozen"] = "off"
                self.player.send_message(f"{target_player.name} is thawed.")
                target_player.send_message("You can move again.")

@VerbRegistry.register(["advance", "givexp", "level"], admin_only=True)
class Advance(BaseVerb):
    def execute(self):
        if len(self.args) < 3:
            self.player.send_message("Usage: ADVANCE <player> <type> <amount>")
            self.player.send_message("Types: xp, level, ptp, mtp, stp, money")
            return
            
        target_name = self.args[0].lower()
        adv_type = self.args[1].lower()
        try:
            amount = int(self.args[2])
        except:
            self.player.send_message("Amount must be a number.")
            return
            
        target = self.world.get_player_obj(target_name)
        if not target:
            self.player.send_message("Player not found.")
            return
            
        if adv_type == "xp":
            target.experience += amount
            target.send_message(f"An admin granted you {amount} XP.")
        elif adv_type == "level":
            old_level = target.level
            target.level = max(0, target.level + amount)
            
            # --- FIX: Calculate TPs for gained levels ---
            if target.level > old_level:
                levels_gained = target.level - old_level
                ptps, mtps, stps = target._calculate_tps_per_level()
                target.ptps += ptps * levels_gained
                target.mtps += mtps * levels_gained
                target.stps += stps * levels_gained
                target.send_message(f"You have been adjusted to level {target.level}. (Gained TPs for {levels_gained} levels)")
            else:
                target.send_message(f"You have been adjusted to level {target.level}.")
            # --------------------------------------------
            
        elif adv_type == "ptp":
            target.ptps += amount
        elif adv_type == "mtp":
            target.mtps += amount
        elif adv_type == "stp":
            target.stps += amount
        elif adv_type == "money":
            target.wealth["silvers"] += amount
            
        self.player.send_message(f"Adjusted {target.name}: {amount} {adv_type}.")
        target.mark_dirty()

@VerbRegistry.register(["snoop"], admin_only=True)
class Snoop(BaseVerb):
    def execute(self):
        if not self.args:
            self.player.send_message("Snoop who?")
            return
        
        target_name = self.args[0].lower()
        if target_name == "off":
            # Find who we are snooping
            targets = []
            for p_name, info in self.world.get_all_players_info():
                p = info.get("player_obj")
                if p and self.player.name.lower() in p.flags.get("snooped_by", []):
                    p.flags["snooped_by"].remove(self.player.name.lower())
                    targets.append(p.name)
            self.player.send_message(f"Stopped snooping: {', '.join(targets)}")
            return

        target = self.world.get_player_obj(target_name)
        if not target:
            self.player.send_message("Player not found.")
            return
            
        # Initialize snoop list if needed
        if "snooped_by" not in target.flags: target.flags["snooped_by"] = []
        
        target.flags["snooped_by"].append(self.player.name.lower())
        self.player.send_message(f"You are now snooping {target.name}.")