# mud_backend/verbs/talk.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.quest_handler import get_active_quest_for_npc
from typing import Dict, Any, Optional
from mud_backend.core.registry import VerbRegistry 
from mud_backend.verbs.foraging import _check_action_roundtime

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
            self._handle_active_quest(active_quest, npc_name)
        else:
            # No active quest, show idle message
            all_quests_done_message = target_npc.get("all_quests_done_message", f"The {npc_name} nods at you politely.")
            self.player.send_message(all_quests_done_message)

    def _handle_active_quest(self, quest, npc_name):
        """
        Checks requirements and triggers completion if met.
        """
        requirements_met = True
        progress_report = []
        
        archetype = quest.get("archetype", "standard")

        # --- A. CHECK REQUIREMENTS ---
        
        # 1. Standard Counters (Kill X) & Syntax Kill
        req_counters = quest.get("req_counters", {})
        for key, req_val in req_counters.items():
            curr_val = self.player.quest_counters.get(key, 0)
            if curr_val < req_val:
                requirements_met = False
                progress_report.append(f"- {key.replace('_', ' ').title()}: {curr_val}/{req_val}")

        # 2. Social Duel (Auto-detect counter)
        if archetype == "social_duel":
            target_id = quest.get("social_target_id")
            action = quest.get("social_action_type")
            req_val = quest.get("req_counter_value", 1)
            
            if target_id and action:
                key = f"social_{target_id}_{action}"
                curr_val = self.player.quest_counters.get(key, 0)
                if curr_val < req_val:
                    requirements_met = False
                    progress_report.append(f"- Social Successes ({action}): {curr_val}/{req_val}")

        # 3. Cartographer (Auto-detect rooms)
        if archetype == "cartographer" or archetype == "ghost_walk":
            req_rooms = quest.get("required_rooms_visited", [])
            for rid in req_rooms:
                key = f"visited_{rid}"
                if not self.player.quest_counters.get(key):
                    requirements_met = False
                    progress_report.append(f"- Scout {rid}: Incomplete")
        
        # 4. Item Requirements (Fetch Quest)
        # If the quest requires an item, we usually wait for GIVE command.
        # However, if it's a "Have item in inventory" check (burden/crafting), we check here.
        item_needed = quest.get("item_needed")
        if item_needed and not quest.get("give_target_name"): # If no give target, it's a check
             # Check inventory count
             count = 0
             for iid in self.player.inventory:
                 if iid == item_needed: count += 1
             # Also check hands
             if self.player.worn_items.get("mainhand") == item_needed: count += 1
             if self.player.worn_items.get("offhand") == item_needed: count += 1
             
             req_qty = quest.get("item_quantity", 1)
             if count < req_qty:
                 requirements_met = False
                 progress_report.append(f"- Possess {item_needed}: {count}/{req_qty}")

        # --- B. HANDLE STATUS ---

        if not requirements_met:
            # Quest In Progress
            progress_prompt = quest.get("progress_prompt", quest.get("talk_prompt", "You have tasks remaining."))
            self.player.send_message(f"The {npc_name} says, \"{progress_prompt}\"")
            if progress_report:
                self.player.send_message("Remaining Tasks:")
                for line in progress_report:
                    self.player.send_message(line)
            
            # Grant Start Item if applicable (and not already had)
            grant_item = quest.get("grant_item_on_talk")
            if grant_item:
                self._handle_item_grant(grant_item, npc_name)
                
        else:
            # --- C. QUEST COMPLETE! ---
            
            # 1. Consume Items (if it was a crafting/burden quest that didn't use GIVE)
            # If it was a standard fetch quest, GIVE handled this. 
            # For Burden quests, we might want to remove the item now.
            if archetype == "burden":
                 burden_item = quest.get("burden_item_id")
                 if burden_item:
                     self._remove_item_from_player(burden_item)
                     self.player.send_message(f"The {burden_item} is taken from you.")

            # 2. Send Reward Message
            reward_msg = quest.get("reward_message", "The task is done. Well done.")
            self.player.send_message(reward_msg)
            
            # 3. Grant Rewards
            
            # XP
            xp = quest.get("reward_xp", 0)
            if xp > 0:
                # Check Reward Type
                xp_type = quest.get("reward_xp_type", "field")
                is_instant = (xp_type == "instant")
                self.player.grant_experience(xp, source="quest", instant=is_instant)
            
            # Silver
            silver = quest.get("reward_silver", 0)
            if silver > 0:
                self.player.wealth["silvers"] += silver
                self.player.send_message(f"You receive {silver} silver.")
            
            # Item
            reward_item = quest.get("reward_item")
            if reward_item:
                self.player.inventory.append(reward_item)
                item_name = self.world.game_items.get(reward_item, {}).get("name", "an item")
                self.player.send_message(f"You receive {item_name}.")

            # Spell
            reward_spell = quest.get("reward_spell")
            if reward_spell and reward_spell not in self.player.known_spells:
                self.player.known_spells.append(reward_spell)
                spell_name = self.world.game_spells.get(reward_spell, {}).get("name", "Unknown Spell")
                self.player.send_message(f"You have learned the spell **{spell_name}**!")

            # Maneuver
            reward_maneuver = quest.get("reward_maneuver")
            if reward_maneuver and reward_maneuver not in self.player.known_maneuvers:
                self.player.known_maneuvers.append(reward_maneuver)
                self.player.send_message(f"You have learned the maneuver **{reward_maneuver}**!")

            # 4. Mark Complete
            self.player.completed_quests.append(quest.get("id", quest.get("name")))
            self.player.mark_dirty()

    def _handle_item_grant(self, grant_item_id, npc_name):
        has_item = False
        if grant_item_id in self.player.inventory: has_item = True
        for slot in ["mainhand", "offhand"]:
            if self.player.worn_items.get(slot) == grant_item_id: has_item = True
        
        if not has_item:
            item_data = self.world.game_items.get(grant_item_id, {})
            item_name = item_data.get("name", "an item")
            
            if self.player.worn_items.get("mainhand") is None:
                self.player.worn_items["mainhand"] = grant_item_id
                self.player.send_message(f"The {npc_name} hands you {item_name}.")
            elif self.player.worn_items.get("offhand") is None:
                self.player.worn_items["offhand"] = grant_item_id
                self.player.send_message(f"The {npc_name} hands you {item_name}.")
            else:
                self.player.inventory.append(grant_item_id)
                self.player.send_message(f"The {npc_name} puts {item_name} in your pack.")

    def _remove_item_from_player(self, item_id):
        if item_id in self.player.inventory:
            self.player.inventory.remove(item_id)
            return
        for slot, iid in self.player.worn_items.items():
            if iid == item_id:
                self.player.worn_items[slot] = None
                return