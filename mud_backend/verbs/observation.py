# mud_backend/verbs/observation.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.db import fetch_player_data
# --- FIX: Removed .py extension from import ---
from mud_backend.core.chargen_handler import format_player_description
# --- END FIX ---
from mud_backend.core.room_handler import show_room_to_player
import math
import random 
from mud_backend.core.skill_handler import attempt_skill_learning
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.utils import calculate_skill_bonus
from mud_backend.core.game_loop import environment

@VerbRegistry.register(["look", "l"]) 
@VerbRegistry.register(["examine", "x"]) 
@VerbRegistry.register(["investigate"])

class Examine(BaseVerb):
    """
    Handles the 'examine' command.
    Checks a player's Investigation (LOG) skill against hidden object details.
    """
    
    def execute(self):
        if not self.args:
            self.player.send_message("Examine what?")
            return

        target_name = " ".join(self.args).lower()
        if target_name.startswith("at "):
            target_name = target_name[3:]
            
        found_object = None
        for obj in self.room.objects:
            if (target_name == obj.get("name", "").lower() or 
                target_name in obj.get("keywords", [])):
                found_object = obj
                break

        if not found_object:
            self.player.send_message(f"You do not see a **{target_name}** here.")
            return

        self.player.send_message(f"You examine the **{found_object['name']}**.")
        self.player.send_message(found_object.get('description', 'It is a nondescript object.'))

        player_log_stat = self.player.stats.get("LOG", 0)
        hidden_details = found_object.get("details", [])
        
        if not hidden_details:
            self.player.send_message("You don't notice anything else unusual about it.")
            return
            
        found_something = False
        for detail in hidden_details:
            dc = detail.get("dc", 100) 
            
            if player_log_stat >= dc:
                self.player.send_message(detail.get("description", "You notice a hidden detail."))
                found_something = True
        
        if not found_something:
            self.player.send_message("You don't notice anything else unusual about it.")

def _find_item_on_player(player, target_name):
    """Checks worn items and inventory for a match."""
    for slot, item_id in player.worn_items.items():
        if item_id:
            item_data = player.world.game_items.get(item_id)
            if item_data:
                if target_name in item_data.get("keywords", []) or target_name == item_data['name'].lower():
                    return item_data, "worn"
                    
    for item_id in player.inventory:
        item_data = player.world.game_items.get(item_id)
        if item_data:
            if target_name in item_data.get("keywords", []) or target_name == item_data['name'].lower():
                return item_data, "inventory"
                
    return None, None

def _get_weather_message_for_window() -> str:
    """Gets a simple description of the current weather for an indoor window."""
    weather = environment.current_weather
    
    if weather == "clear":
        return "Through the glass, you see the sky is clear."
    if weather == "light clouds":
        return "Through the glass, you see a few wispy clouds drifting by."
    if weather == "overcast":
        return "Through the glass, you see a grey, overcast sky."
    if weather == "fog":
        return "Through the glass, you see a thick fog obscuring the view."
    if weather == "light rain":
        return "Through the glass, you see a light rain pattering against the pane."
    if weather == "rain":
        return "Through the glass, you see a steady rain falling."
    if weather == "heavy rain":
        return "Through the glass, you see a heavy downpour lashing against the window."
    if weather == "storm":
        return "Through the glass, you see a fierce storm raging. A flash of lightning brightens the sky!"
        
    return "You glance out the window." 

class Look(BaseVerb):
    """Handles the 'look' command."""
    
    def execute(self):
        
        # --- 1. LOOK (no args) ---
        if not self.args:
            show_room_to_player(self.player, self.room)
            
            # --- MODIFIED: Show Investigate Help AFTER Room Description ---
            if (self.player.current_room_id == "inn_room" and
                "intro_investigate" not in self.player.completed_quests):
                self.player.send_message(
                    "\n<span class='keyword' data-command='help investigate'>[Help: INVESTIGATE]</span> - Things are not always as they seem. "
                    "LOOK gives you a basic view, but you should "
                    "<span class='keyword' data-command='investigate'>INVESTIGATE</span> if you think there is more to be found."
                )
                self.player.completed_quests.append("intro_investigate")
            # --- END MODIFIED ---
            return

        full_command = " ".join(self.args).lower()

        # ---
        # --- MODIFICATION: Handle LOOK IN PACK
        # ---
        if full_command.startswith("in "):
            container_name = full_command[3:].strip()
            if container_name.startswith("my "):
                container_name = container_name[3:].strip()
            
            # Find the container on the player
            container_data, location = _find_item_on_player(self.player, container_name)
            
            if not container_data or not container_data.get("is_container"):
                self.player.send_message(f"You don't see a container called '{container_name}' here.")
                return

            # This logic is specifically for the backpack
            if container_data.get("wearable_slot") == "back":
                if not self.player.inventory:
                    self.player.send_message(f"Your {container_data['name']} is empty.")
                    return
                
                self.player.send_message(f"You look in your {container_data['name']}:")
                for item_id in self.player.inventory:
                    item_data = self.world.game_items.get(item_id)
                    # --- THIS IS THE FIX ---
                    # Check if item_data exists before trying to access it
                    if item_data:
                        self.player.send_message(f"- {item_data.get('name', 'an item')}")
                    else:
                        self.player.send_message(f"- Unknown Item ({item_id})")
                    # --- END FIX ---
                
                # ---
                # --- MODIFIED: Tutorial Hook (Step 5: Stow)
                # ---
                if ("intro_lookinpack" in self.player.completed_quests and
                    "intro_stow" not in self.player.completed_quests):
                    
                    self.player.send_message(
                        "\n<span class='keyword' data-command='help stow'>[Help: STOW]</span> - You can see the dagger in your pack, and you are (presumably) holding the note. "
                        "To put an item *from your hand* into your pack, you can "
                        "<span class='keyword' data-command='stow note'>STOW NOTE</span>. "
                        "Try it now, and then <span class='keyword' data-command='get note'>GET NOTE</span> to pick it back up."
                    )
                    self.player.completed_quests.append("intro_stow")
                # ---
                # --- END MODIFIED
                # ---
                return
            else:
                self.player.send_message(f"You look in {container_data['name']}.")
                self.player.send_message("It is empty.")
                return
        # ---
        # --- END MODIFICATION
        # ---
                
        # --- 3. LOOK <TARGET> ---
        target_name = full_command
        if target_name.startswith("at "):
            target_name = target_name[3:]

        # A. Check room objects
        for obj in self.room.objects:
            if (target_name == obj.get("name", "").lower() or 
                target_name in obj.get("keywords", [])):
            
                self.player.send_message(f"You investigate the **{obj['name']}**.")
                self.player.send_message(obj.get('description', 'It is a nondescript object.'))
                
                # --- SPECIAL LOOK: WINDOW ---
                if (self.player.current_room_id == "inn_room" and 
                    "window" in obj.get("keywords", [])):
                    self.player.send_message(_get_weather_message_for_window())
                
                # ---
                # --- NEW: SPECIAL LOOK: FISHING SPOT
                # ---
                if "FISH" in obj.get("verbs", []):
                    # It's a fishable object. Now check the room.
                    if (self.room.db_data.get("is_fishing_spot", False) and
                        self.room.db_data.get("fishing_loot_table_id")):
                        self.player.send_message("Upon closer inspection, you sense that it contains fish.")
                    else:
                        self.player.send_message("You look, but don't see any fish.")
                # ---
                # --- END NEW
                # ---

                if 'verbs' in obj:
                    verb_list = ", ".join([f'<span class="keyword">{v}</span>' for v in obj['verbs']])
                    self.player.send_message(f"You could try: {verb_list}")
                
                # --- THIS IS THE FIX: Check if Looking At Note ---
                item_id = obj.get("item_id")
                if item_id == "inn_note":
                    # 1. Mark look-at-note as done (if not already)
                    if "intro_lookatnote" not in self.player.completed_quests:
                        self.player.completed_quests.append("intro_lookatnote")
                    
                    # 2. Trigger next step (if not already done)
                    if "intro_leave_room_tasks" not in self.player.completed_quests:
                        self.player.send_message(
                            "\nAs you read the note, you think about paying the bill for your room. "
                            "You can check your <span class='keyword' data-command='wealth'>WEALTH</span> to see how much money you have, "
                            "or check your <span class='keyword' data-command='inventory'>INVENTORY</span> to see what you're carrying. "
                            "\nWhen you're ready, you should <span class='keyword' data-command='out'>OUT</span> to leave the room and <span class='keyword' data-command='talk to innkeeper'>TALK</span> to the innkeeper. <span class='keyword' data-command='help talk'>[Help: TALK]</span>"
                        )
                        self.player.completed_quests.append("intro_leave_room_tasks")
                # --- END FIX ---

                return 

        # B. Check player's own items (worn or inventory)
        item_data, location = _find_item_on_player(self.player, target_name)
        if item_data:
            self.player.send_message(f"You look at your **{item_data['name']}**.")
            self.player.send_message(item_data.get('description', 'It is a nondescript object.'))

            # ---
            # --- THIS IS THE FIX: Find real item ID and check tutorial ---
            # ---
            real_item_id = None
            if location == "worn":
                for slot, i_id in self.player.worn_items.items():
                    if i_id:
                        d = self.world.game_items.get(i_id, {})
                        if (target_name in d.get("keywords", []) or target_name == d.get("name", "").lower()):
                            real_item_id = i_id
                            break
            elif location == "inventory":
                 for i_id in self.player.inventory:
                    d = self.world.game_items.get(i_id, {})
                    if (target_name in d.get("keywords", []) or target_name == d.get("name", "").lower()):
                        real_item_id = i_id
                        break
            
            if real_item_id == "inn_note":
                # 1. Mark look-at-note as done
                if "intro_lookatnote" not in self.player.completed_quests:
                    self.player.completed_quests.append("intro_lookatnote")

                # 2. Trigger next step
                if "intro_leave_room_tasks" not in self.player.completed_quests:
                    self.player.send_message(
                        "\nAs you read the note, you think about paying the bill for your room. "
                        "You can check your <span class='keyword' data-command='wealth'>WEALTH</span> to see how much money you have, "
                        "or check your <span class='keyword' data-command='inventory'>INVENTORY</span> to see what you're carrying. "
                        "\nWhen you're ready, you should <span class='keyword' data-command='out'>OUT</span> to leave the room and <span class='keyword' data-command='talk to innkeeper'>TALK</span> to the innkeeper. <span class='keyword' data-command='help talk'>[Help: TALK]</span>"
                    )
                    self.player.completed_quests.append("intro_leave_room_tasks")
            # ---
            # --- END FIX
            # ---
            return

        # C. Check if target is 'self'
        if target_name == self.player.name.lower() or target_name == "self":
            self.player.send_message(f"You see **{self.player.name}** (that's you!).")
            self.player.send_message(format_player_description(self.player.to_dict()))
            return
                
        # D. Check if target is another player
        target_player_obj = self.world.get_player_obj(target_name)
        
        if target_player_obj and target_player_obj.current_room_id == self.room.room_id:
            target_player_data = target_player_obj.to_dict() 
            self.player.send_message(f"You see **{target_player_data['name']}**.")
            description = format_player_description(target_player_data)
            self.player.send_message(description)
            return
            
        # --- E. Not found ---
        self.player.send_message(f"You do not see a **{target_name}** here.")


class Investigate(BaseVerb):
    """
    Handles the 'investigate' command.
    Calls LBD for 'investigation'.
    If no args, searches for hidden objects.
    If args, performs an 'examine'.
    """
    
    def execute(self):
        attempt_skill_learning(self.player, "investigation")
        
        if _check_action_roundtime(self.player, action_type="other"):
            return
            
        _set_action_roundtime(self.player, 3.0) 

        if self.args:
            
            target_name = " ".join(self.args).lower()
            if target_name.startswith("at "):
                target_name = target_name[3:]
                
            found_object = None
            for obj in self.room.objects:
                if (target_name == obj.get("name", "").lower() or 
                    target_name in obj.get("keywords", [])):
                    found_object = obj
                    break

            if not found_object:
                self.player.send_message(f"You do not see a **{target_name}** here.")
                return

            self.player.send_message(f"You investigate the **{found_object['name']}**.")
            self.player.send_message(found_object.get('description', 'It is a nondescript object.'))

            player_log_stat = self.player.stats.get("LOG", 0)
            hidden_details = found_object.get("details", [])
            
            if not hidden_details:
                self.player.send_message("You don't notice anything else unusual about it.")
                return
                
            found_something = False
            for detail in hidden_details:
                dc = detail.get("dc", 100)
                
                if player_log_stat >= dc:
                    self.player.send_message(detail.get("description", "You notice a hidden detail."))
                    found_something = True
            
            if not found_something:
                self.player.send_message("You don't notice anything else unusual about it.")
            
            return

        self.player.send_message("You investigate the room...")
        
        hidden_objects = self.room.db_data.get("hidden_objects", [])
        if not hidden_objects:
            self.player.send_message("...but you don't find anything unusual.")
            return
            
        found_something = False
        for i in range(len(hidden_objects) - 1, -1, -1):
            obj = hidden_objects[i]
            
            # ---
            # --- THIS IS THE FIX: Skip nodes
            # ---
            if obj.get("node_id") or obj.get("node_type"):
                continue
            # ---
            # --- END FIX
            # ---
            
            dc = obj.get("perception_dc", 100)
            
            skill_rank = self.player.skills.get("investigation", 0)
            skill_bonus = calculate_skill_bonus(skill_rank)
            roll = random.randint(1, 100) + skill_bonus
            
            if roll >= dc:
                found_obj = self.room.db_data["hidden_objects"].pop(i)
                self.room.objects.append(found_obj)
                found_something = True
                
                self.player.send_message(f"Your investigation reveals: **{found_obj.get('name', 'an item')}**!")
                
                # ---
                # --- MODIFIED: Tutorial Hook (Step 1: Get)
                # ---
                if (found_obj.get("item_id") == "inn_note" and
                    "intro_get" not in self.player.completed_quests):
                    self.player.send_message(
                         "\n<span class='keyword' data-command='help get'>[Help: GET]</span> - You found a note! "
                         "To pick it up, you can <span class='keyword' data-command='get note'>GET NOTE</span>."
                    )
                    self.player.completed_quests.append("intro_get")
                # --- END MODIFIED ---
        
        if found_something:
            self.world.save_room(self.room)
        else:
            self.player.send_message("...but you don't find anything new.")