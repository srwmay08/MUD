# mud_backend/verbs/talk.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.quest_handler import get_active_quest_for_npc
from typing import Dict, Any, Optional

def _find_npc_in_room(room, target_name: str) -> Optional[Dict[str, Any]]:
    """Finds an NPC object in the room by name or keyword."""
    for obj in room.objects:
        # Check for quest givers that are not monsters
        if obj.get("quest_giver_ids") and not obj.get("is_monster"):
            if (target_name == obj.get("name", "").lower() or 
                target_name in obj.get("keywords", [])):
                return obj
    return None

class Talk(BaseVerb):
    """
    Handles the 'talk' command.
    TALK TO <npc>
    """
    def execute(self):
        if not self.args:
            self.player.send_message("Who do you want to talk to?")
            return
            
        target_name = " ".join(self.args).lower()
        if target_name.startswith("to "):
            target_name = target_name[3:].strip()

        # 1. Find the NPC
        target_npc = _find_npc_in_room(self.room, target_name)
        if not target_npc:
            self.player.send_message(f"You don't see anyone named '{target_name}' here to talk to.")
            return
            
        npc_name = target_npc.get("name", "the NPC")
        npc_quest_ids = target_npc.get("quest_giver_ids", [])

        # 2. Find the active quest
        active_quest = get_active_quest_for_npc(self.player, npc_quest_ids)
        
        if active_quest:
            # 3. Get the detailed talk prompt from the quest
            talk_prompt = active_quest.get("talk_prompt")
            if talk_prompt:
                self.player.send_message(f"You talk to the {npc_name}.")
                self.player.send_message(f"The {npc_name} says, \"{talk_prompt}\"")
            else:
                self.player.send_message(f"The {npc_name} doesn't seem to have much to say.")
        else:
            # 4. No active quest, check for a "completed all" message
            all_quests_done_message = target_npc.get("all_quests_done_message", f"The {npc_name} nods at you politely.")
            
            # Check if all quests for this NPC are *actually* done
            all_done = True
            for q_id in npc_quest_ids:
                quest_data = self.world.game_quests.get(q_id)
                if not quest_data: continue
                reward = quest_data.get("reward_spell")
                if (reward and reward not in self.player.known_spells) and (q_id not in self.player.completed_quests):
                    all_done = False # Found one not completed
                    break
            
            if all_done:
                 self.player.send_message(all_quests_done_message)
            else:
                # Default "busy" message if there are quests, but none are active for the player
                self.player.send_message(f"The {npc_name} seems busy with other tasks.")