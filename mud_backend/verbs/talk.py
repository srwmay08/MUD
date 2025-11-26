# mud_backend/verbs/talk.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.quest_handler import get_active_quest_for_npc
from typing import Dict, Any, Optional
from mud_backend.core.registry import VerbRegistry # <-- Added

def _find_npc_in_room(room, target_name: str) -> Optional[Dict[str, Any]]:
    """Finds an NPC object in the room by name or keyword."""
    for obj in room.objects:
        if obj.get("quest_giver_ids") or obj.get("is_npc"):
            if (target_name == obj.get("name", "").lower() or 
                target_name in obj.get("keywords", [])):
                return obj
    return None

@VerbRegistry.register(["talk"]) 
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
        if target_name.startswith("a "):
            target_name = target_name[2:].strip()

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
            # 3. Check Counter Progress (for multi-step quests)
            req_counters = active_quest.get("req_counters", {})
            progress_report = []
            requirements_met = True
            
            # Check multiple counters
            for key, req_val in req_counters.items():
                curr_val = self.player.quest_counters.get(key, 0)
                if curr_val < req_val:
                    requirements_met = False
                    progress_report.append(f"- {key.replace('_', ' ').title()}: {curr_val}/{req_val}")
            
            # Check single counter (Legacy)
            req_counter_key = active_quest.get("req_counter")
            if req_counter_key:
                req_val = active_quest.get("req_counter_value", 1)
                curr_val = self.player.quest_counters.get(req_counter_key, 0)
                if curr_val < req_val:
                    requirements_met = False
                    progress_report.append(f"- {req_counter_key.replace('_', ' ').title()}: {curr_val}/{req_val}")

            # Check Item Requirement (if 'grant_quest_on_talk' is NOT true, we expect user to use GIVE)
            # But if talk_prompt is just chatter, we show it.
            # The GIVE logic is in trading.py. Here we mostly handle "return for reward" or "get info".

            # If requirements NOT met, show progress
            if not requirements_met:
                progress_prompt = active_quest.get("progress_prompt", "You have tasks remaining.")
                self.player.send_message(f"The {npc_name} says, \"{progress_prompt}\"")
                if progress_report:
                    self.player.send_message("Remaining Tasks:")
                    for line in progress_report:
                        self.player.send_message(line)
                return

            # 4. Process Completion / Dialogue
            talk_prompt = active_quest.get("talk_prompt")
            give_target = active_quest.get("give_target_name")
            # If quest requires giving an item, TALK is just for hints, unless we are the giver
            is_just_receiver = (give_target and give_target == npc_name.lower() and active_quest.get("item_needed"))

            if talk_prompt and not is_just_receiver: 
                self.player.send_message(f"You talk to the {npc_name}.")
                self.player.send_message(f"The {npc_name} says, \"{talk_prompt}\"")
                
                # --- REWARD: SPELL BESTOWAL ---
                reward_spell = active_quest.get("reward_spell")
                if reward_spell and reward_spell not in self.player.known_spells:
                    self.player.known_spells.append(reward_spell)
                    spell_name = self.world.game_spells.get(reward_spell, {}).get("name", "Unknown")
                    self.player.send_message(f"\nThe {npc_name} places a hand upon your forehead and chants a prayer...")
                    self.player.send_message(f"A surge of divine energy rushes through you! You have been granted the ability to cast **{spell_name}**.")
                    
                    # Mark complete immediately if it was just a "talk to get reward" step
                    if active_quest.get("name") not in self.player.completed_quests:
                         # For simplicity, assume ID is active_quest["name"] which is usually the key in JSON loading, 
                         # but strictly we need the ID. Since get_active_quest_for_npc returns the data dict, 
                         # ideally it should return the ID too. 
                         # Workaround: Loop through npc_quest_ids to find which ID matches this data object.
                         found_id = None
                         for qid in npc_quest_ids:
                             if self.world.game_quests.get(qid) == active_quest:
                                 found_id = qid
                                 break
                         if found_id:
                             self.player.completed_quests.append(found_id)

                # --- REWARD: MANEUVER ---
                reward_maneuver = active_quest.get("reward_maneuver")
                if reward_maneuver and reward_maneuver not in self.player.known_maneuvers:
                    self.player.known_maneuvers.append(reward_maneuver)
                    self.player.send_message(f"You feel you understand the basics of **{reward_maneuver.replace('_', ' ').title()}**.")
                    if reward_maneuver == "trip_training":
                        self.player.quest_trip_counter = 0

                # --- REWARD: ITEMS ---
                grant_item_id = active_quest.get("grant_item_on_talk")
                if grant_item_id:
                    self._handle_item_grant(grant_item_id, npc_name)
            
            elif is_just_receiver:
                self.player.send_message(f"You talk to the {npc_name}.")
                item_needed_id = active_quest.get("item_needed")
                if item_needed_id:
                    item_name = self.world.game_items.get(item_needed_id, {}).get("name", "an item")
                    item_keyword = item_name.split()[-1].lower() 
                    self.player.send_message(f"The {npc_name} seems to be waiting for something... perhaps you should <span class='keyword' data-command='give {npc_name.lower().split()[-1]} {item_keyword}'>GIVE</span> them {item_name}?")
                else:
                     self.player.send_message(f"The {npc_name} doesn't seem to have much to say.")
        else:
            all_quests_done_message = target_npc.get("all_quests_done_message", f"The {npc_name} nods at you politely.")
            self.player.send_message(all_quests_done_message)

    def _handle_item_grant(self, grant_item_id, npc_name):
        has_item = False
        if grant_item_id in self.player.inventory: has_item = True
        for slot in ["mainhand", "offhand"]:
            if self.player.worn_items.get(slot) == grant_item_id: has_item = True
        
        if not has_item:
            item_data = self.world.game_items.get(grant_item_id, {})
            item_name = item_data.get("name", "an item")
            target_hand_slot = None
            if self.player.worn_items.get("mainhand") is None: target_hand_slot = "mainhand"
            elif self.player.worn_items.get("offhand") is None: target_hand_slot = "offhand"

            if target_hand_slot:
                self.player.worn_items[target_hand_slot] = grant_item_id
                self.player.send_message(f"The {npc_name} hands you {item_name}, which you hold.")
            else:
                self.player.inventory.append(grant_item_id)
                self.player.send_message(f"The {npc_name} hands you {item_name}. Your hands are full, so you put it in your pack.")