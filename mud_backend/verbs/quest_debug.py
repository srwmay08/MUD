# mud_backend/verbs/quest_debug.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core.quest_handler import get_active_quest_for_npc

@VerbRegistry.register(["quest"], admin_only=True)
class QuestDebug(BaseVerb):
    def execute(self):
        if not self.args:
            self.player.send_message("Usage: QUEST DEBUG | QUEST LIST | QUEST CHECK <npc_name>")
            return
            
        sub = self.args[0].lower()
        
        if sub == "list":
            self.player.send_message("--- Loaded Quests ---")
            count = 0
            for qid in self.world.game_quests.keys():
                self.player.send_message(f"- {qid}")
                count += 1
            self.player.send_message(f"Total: {count}")
            
        elif sub == "check":
            target_name = " ".join(self.args[1:]).lower()
            found = None
            for obj in self.room.objects:
                if target_name in obj.get("keywords", []) or target_name == obj.get("name", "").lower():
                    found = obj
                    break
            
            if not found:
                self.player.send_message("NPC not found.")
                return
                
            q_ids = found.get("quest_giver_ids", [])
            self.player.send_message(f"NPC: {found.get('name')} ({found.get('monster_id', 'unknown')})")
            self.player.send_message(f"Quest IDs on NPC: {q_ids}")
            
            if not q_ids:
                self.player.send_message("This NPC has no quests assigned.")
                return

            active = get_active_quest_for_npc(self.player, q_ids)
            if active:
                self.player.send_message(f"Active Quest Returned: {active.get('name')} ({active.get('archetype', 'standard')})")
            else:
                self.player.send_message("No active quest found (Prereqs met? Completed?).")
                
        elif sub == "debug":
            self.player.send_message("--- Quest Debug ---")
            self.player.send_message(f"Completed: {self.player.completed_quests}")
            self.player.send_message(f"Counters: {self.player.quest_counters}")