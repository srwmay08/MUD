# mud_backend/verbs/observation.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.room_handler import show_room_to_player
from mud_backend.core.chargen_handler import format_player_description
import random 
from mud_backend.core.skill_handler import attempt_skill_learning
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.utils import calculate_skill_bonus
from mud_backend.core.game_loop import environment
from mud_backend.core.registry import VerbRegistry

def _find_item_on_player(player, target_name):
    """Checks worn items and inventory for a match."""
    # Fix: Ensure we don't crash if worn_items contains malformed data (dicts instead of strings)
    for slot, item_id in player.worn_items.items():
        if item_id and isinstance(item_id, str):
            item_data = player.world.game_items.get(item_id)
            if item_data:
                if target_name in item_data.get("keywords", []) or target_name == item_data['name'].lower():
                    return item_data, "worn"
                    
    # Fix: Ensure we don't crash if inventory contains malformed data
    for item_id in player.inventory:
        if item_id and isinstance(item_id, str):
            item_data = player.world.game_items.get(item_id)
            if item_data:
                if target_name in item_data.get("keywords", []) or target_name == item_data['name'].lower():
                    return item_data, "inventory"
                
    return None, None

def _get_weather_message_for_window() -> str:
    """Gets a simple description of the current weather for an indoor window."""
    weather = environment.current_weather
    if weather == "clear": return "Through the glass, you see the sky is clear."
    if weather == "light clouds": return "Through the glass, you see a few wispy clouds drifting by."
    if weather == "overcast": return "Through the glass, you see a grey, overcast sky."
    if weather == "fog": return "Through the glass, you see a thick fog obscuring the view."
    if weather == "light rain": return "Through the glass, you see a light rain pattering against the pane."
    if weather == "rain": return "Through the glass, you see a steady rain falling."
    if weather == "heavy rain": return "Through the glass, you see a heavy downpour lashing against the window."
    if weather == "storm": return "Through the glass, you see a fierce storm raging. A flash of lightning brightens the sky!"
    return "You glance out the window." 

def _get_table_occupants(world, table_obj):
    """
    Helper to find players sitting at a specific table object.
    Strategy:
    1. Check if object has 'target_room' defined.
    2. Fallback: Search all rooms for one with a matching name.
    """
    target_room_id = table_obj.get("target_room")
    
    # Fallback: Try to match by name if target_room isn't set
    if not target_room_id:
        table_name_lower = table_obj.get("name", "").lower()
        # This iteration might be slow if you have thousands of rooms, 
        # ideally add 'target_room' to your JSON objects!
        for rid, room in world.rooms.items():
            if room.name.lower() == table_name_lower and room.is_table:
                target_room_id = rid
                break
    
    if target_room_id:
        # Get players in that room
        # room_players is usually a dict of {room_id: {player_name, ...}} or list
        player_names = world.room_players.get(target_room_id, [])
        return list(player_names)
    
    return []

@VerbRegistry.register(["examine", "x"]) 
class Examine(BaseVerb):
    def execute(self):
        if not self.args:
            self.player.send_message("Examine what?")
            return

        target_name = " ".join(self.args).lower()
        if target_name.startswith("at "): target_name = target_name[3:]
            
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

        # --- Table Check for Examine ---
        if "table" in found_object.get("keywords", []) or found_object.get("is_table_proxy"):
            occupants = _get_table_occupants(self.world, found_object)
            if occupants:
                formatted_names = [f"**{name.capitalize()}**" for name in occupants]
                self.player.send_message(f"Seated here: {', '.join(formatted_names)}")
            else:
                self.player.send_message("It is currently empty.")
        # -------------------------------

        player_log_stat = self.player.stats.get("LOG", 0)
        hidden_details = found_object.get("details", [])
        
        found_something = False
        for detail in hidden_details:
            dc = detail.get("dc", 100) 
            if player_log_stat >= dc:
                self.player.send_message(detail.get("description", "You notice a hidden detail."))
                found_something = True
        
        if hidden_details and not found_something:
            self.player.send_message("You don't notice anything else unusual about it.")


@VerbRegistry.register(["look", "l"]) 
class Look(BaseVerb):
    def execute(self):
        if not self.args:
            show_room_to_player(self.player, self.room)
            return

        full_command = " ".join(self.args).lower()

        # --- NEW: LOOK TABLES ---
        if full_command == "tables" or full_command == "at tables":
            tables_found = []
            for obj in self.room.objects:
                # Identify if object is a table based on keywords
                if "table" in obj.get("keywords", []):
                    tables_found.append(obj)
            
            if not tables_found:
                self.player.send_message("You don't see any tables here.")
                return

            self.player.send_message("--- Tables in the Room ---")
            for table in tables_found:
                occupants = _get_table_occupants(self.world, table)
                if occupants:
                    count = len(occupants)
                    people_str = "person" if count == 1 else "people"
                    self.player.send_message(f"- **{table['name']}**: Occupied by {count} {people_str}.")
                else:
                    self.player.send_message(f"- **{table['name']}**: Empty")
            return
        # ---------------------------

        # --- NEW: LOOK IN LOCKER ---
        if "in locker" in full_command or "in vault" in full_command:
            # Check if allowed room
            if "vault" not in self.room.name.lower() and "locker" not in self.room.name.lower():
                 self.player.send_message("You must be at the Town Hall Vaults to access your locker.")
                 return
            
            locker = self.player.locker
            items = locker.get("items", [])
            capacity = locker.get("capacity", 50)
            self.player.send_message(f"--- Your Locker ({len(items)}/{capacity}) ---")
            if not items: self.player.send_message("  (Empty)")
            for item in items: self.player.send_message(f"- {item['name']}")
            return
        # ---------------------------

        if full_command.startswith("in "):
            container_name = full_command[3:].strip()
            if container_name.startswith("my "): container_name = container_name[3:].strip()
            
            container_data, location = _find_item_on_player(self.player, container_name)
            
            if not container_data or not container_data.get("is_container"):
                self.player.send_message(f"You don't see a container called '{container_name}' here.")
                return

            if container_data.get("wearable_slot") == "back":
                if not self.player.inventory:
                    self.player.send_message(f"Your {container_data['name']} is empty.")
                    return
                self.player.send_message(f"You look in your {container_data['name']}:")
                for item_id in self.player.inventory:
                    # Fix: Handle malformed inventory
                    if not isinstance(item_id, str): continue 
                    item_data = self.world.game_items.get(item_id)
                    if item_data: self.player.send_message(f"- {item_data.get('name', 'an item')}")
                    else: self.player.send_message(f"- Unknown Item ({item_id})")
                return
            else:
                self.player.send_message(f"You look in {container_data['name']}.")
                self.player.send_message("It is empty.")
                return
                
        target_name = full_command
        if target_name.startswith("at "): target_name = target_name[3:]

        # Check room objects
        for obj in self.room.objects:
            if (target_name == obj.get("name", "").lower() or 
                target_name in obj.get("keywords", [])):
            
                self.player.send_message(f"You investigate the **{obj['name']}**.")
                self.player.send_message(obj.get('description', 'It is a nondescript object.'))
                
                # --- NEW: Check Table Occupants on specific Look ---
                if "table" in obj.get("keywords", []) or obj.get("is_table_proxy"):
                    occupants = _get_table_occupants(self.world, obj)
                    if occupants:
                        formatted_names = [f"**{name.capitalize()}**" for name in occupants]
                        self.player.send_message(f"Seated here: {', '.join(formatted_names)}")
                    else:
                        self.player.send_message("It appears to be empty.")
                # ---------------------------------------------------

                if "FISH" in obj.get("verbs", []):
                    if (self.room.data.get("is_fishing_spot", False) and self.room.data.get("fishing_loot_table_id")):
                        self.player.send_message("Upon closer inspection, you sense that it contains fish.")
                    else:
                        self.player.send_message("You look, but don't see any fish.")

                if 'verbs' in obj:
                    verb_list = ", ".join([f'<span class="keyword">{v}</span>' for v in obj['verbs']])
                    self.player.send_message(f"You could try: {verb_list}")
                
                return 

        # Check player items
        item_data, location = _find_item_on_player(self.player, target_name)
        if item_data:
            self.player.send_message(f"You look at your **{item_data['name']}**.")
            self.player.send_message(item_data.get('description', 'It is a nondescript object.'))
            return

        # Check self
        if target_name == self.player.name.lower() or target_name == "self":
            self.player.send_message(f"You see **{self.player.name}** (that's you!).")
            self.player.send_message(format_player_description(self.player.to_dict()))
            return
                
        # Check other players
        target_player_obj = self.world.get_player_obj(target_name)
        if target_player_obj and target_player_obj.current_room_id == self.room.room_id:
            target_player_data = target_player_obj.to_dict() 
            self.player.send_message(f"You see **{target_player_data['name']}**.")
            description = format_player_description(target_player_data)
            self.player.send_message(description)
            return
            
        self.player.send_message(f"You do not see a **{target_name}** here.")


@VerbRegistry.register(["investigate"]) 
class Investigate(BaseVerb):
    def execute(self):
        attempt_skill_learning(self.player, "investigation")
        if _check_action_roundtime(self.player, action_type="other"): return
        _set_action_roundtime(self.player, 3.0) 

        if self.args:
            # Delegate to examine logic if args present
            Examine(self.world, self.player, self.room, self.args, "examine").execute()
            return

        self.player.send_message("You investigate the room...")
        hidden_objects = self.room.data.get("hidden_objects", [])
        if not hidden_objects:
            self.player.send_message("...but you don't find anything unusual.")
            return
            
        found_something = False
        for i in range(len(hidden_objects) - 1, -1, -1):
            obj = hidden_objects[i]
            if obj.get("node_id") or obj.get("node_type"): continue
            
            dc = obj.get("perception_dc", 100)
            skill_rank = self.player.skills.get("investigation", 0)
            skill_bonus = calculate_skill_bonus(skill_rank)
            roll = random.randint(1, 100) + skill_bonus
            
            if roll >= dc:
                found_obj = self.room.data["hidden_objects"].pop(i)
                self.room.objects.append(found_obj)
                found_something = True
                self.player.send_message(f"Your investigation reveals: **{found_obj.get('name', 'an item')}**!")
        
        if found_something:
            self.world.save_room(self.room)
        else:
            self.player.send_message("...but you don't find anything new.")