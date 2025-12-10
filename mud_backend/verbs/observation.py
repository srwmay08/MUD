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
from mud_backend.verbs.shop import _get_shop_data, _get_item_buy_price


def _find_item_on_player(player, target_name):
    """Checks worn items and inventory for a match."""
    for slot, item_id in player.worn_items.items():
        if item_id:
            if isinstance(item_id, dict):
                item_data = item_id
            else:
                item_data = player.world.game_items.get(item_id)

            if item_data:
                if target_name in item_data.get("keywords", []) or target_name == item_data['name'].lower():
                    return item_data, "worn"

    for item_id in player.inventory:
        if item_id:
            if isinstance(item_id, dict):
                item_data = item_id
            else:
                item_data = player.world.game_items.get(item_id)

            if item_data:
                if target_name in item_data.get("keywords", []) or target_name == item_data['name'].lower():
                    return item_data, "inventory"

    return None, None


def _get_table_occupants(world, table_obj):
    target_room_id = table_obj.get("target_room")

    if not target_room_id:
        table_name_lower = table_obj.get("name", "").lower()
        # FIX: Access active_rooms instead of rooms
        for rid, room in world.active_rooms.items():
            if room.name.lower() == table_name_lower and getattr(room, "is_table", False):
                target_room_id = rid
                break

    if target_room_id:
        player_names = world.room_players.get(target_room_id, [])
        return list(player_names)

    return []


def _list_items_on_table(player, room, table_obj):
    """
    Helper to list items associated with a specific display table.
    """
    shop_data = _get_shop_data(room)

    # If no shop data, just check for occupants (Standard Table)
    if not shop_data:
        if "table" in table_obj.get("keywords", []):
            occupants = _get_table_occupants(player.world, table_obj)
            if occupants:
                count = len(occupants)
                player.send_message(f"It is occupied by {count} person{'s' if count > 1 else ''}.")
            else:
                player.send_message("It is currently empty.")
        return

    # Determine Category based on table keywords
    category = "misc"
    keywords = table_obj.get("keywords", [])
    if "weapon" in keywords or "weapons" in keywords:
        category = "weapon"
    elif "armor" in keywords or "armors" in keywords:
        category = "armor"
    elif "magic" in keywords or "arcane" in keywords or "scrolls" in keywords:
        category = "magic"

    # Filter Inventory
    items_on_table = []
    game_items = player.world.game_items
    
    # Track displayed names to deduplicate
    displayed_names = set()

    for item_ref in shop_data.get("inventory", []):
        # Resolve Item Data
        if isinstance(item_ref, dict):
            item_data = item_ref
        else:
            item_data = game_items.get(item_ref, {})

        if not item_data:
            continue

        # Check Type
        itype = item_data.get("type", "misc")
        if "weapon_type" in item_data:
            itype = "weapon"
        elif "armor_type" in item_data:
            itype = "armor"
        elif "spell" in item_data or "scroll" in item_data.get("keywords", []):
            itype = "magic"

        # Categorization Logic
        match = False
        if category == "weapon" and itype == "weapon":
            match = True
        elif category == "armor" and itype == "armor":
            match = True
        elif category == "magic" and itype == "magic":
            match = True
        elif category == "misc" and itype not in ["weapon", "armor", "magic"]:
            match = True

        if match:
            name = item_data.get('name', 'Item')
            # Deduplication: Only show one of each item name
            if name not in displayed_names:
                price = _get_item_buy_price(item_ref, game_items, shop_data)
                items_on_table.append((name, price))
                displayed_names.add(name)

    if items_on_table:
        player.send_message(f"--- On the {table_obj.get('name', 'Table')} ---")
        for name, price in items_on_table:
            player.send_message(f"- {name:<30} {price} silver")
    else:
        player.send_message(f"The {table_obj.get('name', 'Table')} is currently empty.")


@VerbRegistry.register(["examine", "x"])
class Examine(BaseVerb):
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

        self.player.send_message(f"You examine the **{found_object.get('name', 'object')}**.")
        self.player.send_message(found_object.get('description', 'It is a nondescript object.'))

        # --- Table Check for Examine ---
        # If it's a shop table, list items
        if "table" in found_object.get("keywords", []) and _get_shop_data(self.room):
            _list_items_on_table(self.player, self.room, found_object)
        # Else standard table occupants
        elif "table" in found_object.get("keywords", []) or found_object.get("is_table_proxy"):
            occupants = _get_table_occupants(self.world, found_object)
            if occupants:
                count = len(occupants)
                self.player.send_message(f"It is occupied by {count} person{'s' if count > 1 else ''}.")
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

        # --- LOOK ON TABLE (Pawnshop) ---
        target_on = None
        if full_command.startswith("on "):
            target_on = full_command[3:].strip()
        elif " on " in full_command:
            parts = full_command.split(" on ", 1)
            target_on = parts[1].strip()

        if target_on:
            table_obj = None
            for obj in self.room.objects:
                if (target_on == obj.get("name", "").lower() or target_on in obj.get("keywords", [])):
                    table_obj = obj
                    break

            if table_obj:
                _list_items_on_table(self.player, self.room, table_obj)
                return
            else:
                self.player.send_message(f"You don't see a '{target_on}' here.")
                return
        # --------------------------------

        if full_command.startswith("in "):
            container_name = full_command[3:].strip()
            if container_name.startswith("my "):
                container_name = container_name[3:].strip()

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
                    if isinstance(item_id, dict):
                        item_data = item_id
                    else:
                        item_data = self.world.game_items.get(item_id, {})

                    if item_data:
                        self.player.send_message(f"- {item_data.get('name', 'an item')}")
                    else:
                        self.player.send_message(f"- Unknown Item ({item_id})")
                return
            else:
                self.player.send_message(f"You look in {container_data['name']}.")
                self.player.send_message("It is empty.")
                return

        target_name = full_command
        if target_name.startswith("at "):
            target_name = target_name[3:]

        # Check room objects
        for obj in self.room.objects:
            if (target_name == obj.get("name", "").lower() or
                    target_name in obj.get("keywords", [])):

                self.player.send_message(f"You investigate the **{obj.get('name', 'object')}**.")
                self.player.send_message(obj.get('description', 'It is a nondescript object.'))

                # --- NEW: If shop table, list items ---
                if "table" in obj.get("keywords", []) and _get_shop_data(self.room):
                    _list_items_on_table(self.player, self.room, obj)
                # --- OLD: Standard Table Occupants ---
                elif "table" in obj.get("keywords", []) or obj.get("is_table_proxy"):
                    occupants = _get_table_occupants(self.world, obj)
                    if occupants:
                        count = len(occupants)
                        self.player.send_message(f"It is occupied by {count} person{'s' if count > 1 else ''}.")
                    else:
                        self.player.send_message("It is currently empty.")
                # -------------------------------------

                return

        # Check player items
        item_data, location = _find_item_on_player(self.player, target_name)
        if item_data:
            self.player.send_message(f"You look at your **{item_data.get('name', 'item')}**.")
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
        if _check_action_roundtime(self.player, action_type="other"):
            return
        _set_action_roundtime(self.player, 3.0)

        if self.args:
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
            if obj.get("node_id") or obj.get("node_type"):
                continue

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


@VerbRegistry.register(["inspect"])
class Inspect(BaseVerb):
    """
    Shows detailed attributes of an item (Weapon/Armor stats).
    """

    def execute(self):
        if not self.args:
            self.player.send_message("Inspect what?")
            return

        target_name = " ".join(self.args).lower()

        # Check Hands/Inventory/Worn
        item_data, loc = _find_item_on_player(self.player, target_name)

        # Check Shop/Tables if not found on player
        if not item_data:
            shop_data = _get_shop_data(self.room)
            if shop_data:
                for item_ref in shop_data.get("inventory", []):
                    if isinstance(item_ref, dict):
                        t_data = item_ref
                    else:
                        t_data = self.world.game_items.get(item_ref, {})

                    if t_data and (target_name == t_data.get("name", "").lower() or target_name in t_data.get("keywords", [])):
                        item_data = t_data
                        break

        if not item_data:
            self.player.send_message(f"You don't see a '{target_name}' to inspect.")
            return

        self.player.send_message(f"--- Inspection: {item_data.get('name')} ---")
        self.player.send_message(f"Type: {item_data.get('type', 'Unknown')}")
        self.player.send_message(f"Base Value: {item_data.get('base_value', 0)}")
        self.player.send_message(f"Weight: {item_data.get('weight', 0)} lbs")

        if "damage_type" in item_data:
            self.player.send_message(f"Damage Type: {item_data['damage_type']}")
        if "base_damage" in item_data:
            self.player.send_message(f"Base Damage: {item_data['base_damage']}")
        if "armor_type" in item_data:
            self.player.send_message(f"Armor Type: {item_data['armor_type']}")
        if "armor_class" in item_data:
            self.player.send_message(f"Armor Class: {item_data['armor_class']}")

        # Pawnshop Note
        shop_data = _get_shop_data(self.room)
        if shop_data:
            price = _get_item_buy_price(item_data, self.world.game_items, shop_data)
            self.player.send_message(f"Estimated Shop Price: {price} silver")