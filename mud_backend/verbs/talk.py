# mud_backend/verbs/talk.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.quest_handler import get_active_quest_for_npc
from typing import Dict, Any, Optional

def _find_npc_in_room(room, target_name: str) -> Optional[Dict[str, Any]]:
    """Finds an NPC object in the room by name or keyword."""
    for obj in room.objects:
        # ---
        # --- THIS IS THE FIX ---
        # We now find any object that has quest IDs OR is flagged as an NPC
        if obj.get("quest_giver_ids") or obj.get("is_npc"):
        # --- END FIX ---
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
            
        # --- NEW: Handle "talk a grizzled warrior" ---
        if target_name.startswith("a "):
            target_name = target_name[2:].strip()
        # --- END NEW ---

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
                
                # ---
                # --- THIS IS THE FIX: Grant item on talk
                # ---
                grant_item_id = active_quest.get("grant_item_on_talk")
                if grant_item_id:
                    # Check if player already has it (in inventory or hands)
                    has_item = False
                    if grant_item_id in self.player.inventory:
                        has_item = True
                    else:
                        for slot in ["mainhand", "offhand"]:
                            if self.player.worn_items.get(slot) == grant_item_id:
                                has_item = True
                                break
                    
                    if not has_item:
                        item_data = self.world.game_items.get(grant_item_id, {})
                        item_name = item_data.get("name", "an item")

                        # --- New Logic: Try hands first ---
                        target_hand_slot = None
                        if self.player.worn_items.get("mainhand") is None:
                            target_hand_slot = "mainhand"
                        elif self.player.worn_items.get("offhand") is None:
                            target_hand_slot = "offhand"

                        if target_hand_slot:
                            self.player.worn_items[target_hand_slot] = grant_item_id
                            self.player.send_message(f"The {npc_name} hands you {item_name}, which you hold.")
                            # --- STOW tutorial hook ---
                            if "intro_stow" not in self.player.completed_quests:
                                 self.player.send_message(
                                    "\n<span class='keyword' data-command='help stow'>[Help: STOW]</span> - You are now holding the item. "
                                    "To put it in your backpack, you can "
                                    f"<span class='keyword' data-command='stow {item_name.lower()}'>STOW {item_name.upper()}</span>."
                                 )
                                 self.player.completed_quests.append("intro_stow")
                        else:
                            # Hands are full, put in pack
                            self.player.inventory.append(grant_item_id)
                            self.player.send_message(f"The {npc_name} hands you {item_name}. Your hands are full, so you put it in your pack.")
                # ---
                # --- END FIX
                # ---
                
                # --- NEW: Grant "trip_training" maneuver ---
                reward_maneuver = active_quest.get("reward_maneuver")
                if reward_maneuver and reward_maneuver not in self.player.known_maneuvers:
                    self.player.known_maneuvers.append(reward_maneuver)
                    self.player.send_message(f"You feel you understand the basics of **{reward_maneuver.replace('_', ' ').title()}**.")
                    # Initialize the counter
                    if reward_maneuver == "trip_training":
                        self.player.quest_trip_counter = 0
                # --- END NEW ---
            else:
                self.player.send_message(f"The {npc_name} doesn't seem to have much to say.")
        else:
            # 4. No active quest, check for a "completed all" message
            # --- MODIFIED: Use the message from monsters.json ---
            all_quests_done_message = target_npc.get("all_quests_done_message", f"The {npc_name} nods at you politely.")
            
            # Check if all quests for this NPC are *actually* done
            all_done = True
            for q_id in npc_quest_ids:
                quest_data = self.world.game_quests.get(q_id)
                if not quest_data: continue
                
                # --- NEW: Check spells and maneuvers ---
                reward_spell = quest_data.get("reward_spell")
                reward_maneuver = quest_data.get("reward_maneuver")
                
                is_done = False
                if (q_id in self.player.completed_quests) or \
                   (reward_spell and reward_spell in player.known_spells) or \
                   (reward_maneuver and reward_maneuver in player.known_maneuvers) or \
                   (reward_maneuver == "trip_training" and "trip" in player.known_maneuvers):
                    is_done = True
                
                if not is_done:
                    all_done = False # Found one not completed
                    break
                # --- END NEW ---
            
            if all_done:
                 self.player.send_message(all_quests_done_message)
            else:
                # Default "busy" message if there are quests, but none are active for the player
                self.player.send_message(f"The {npc_name} seems busy with other tasks.")