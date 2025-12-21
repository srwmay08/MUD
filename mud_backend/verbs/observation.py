# mud_backend/verbs/observation.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.room_handler import show_room_to_player
from mud_backend.core.chargen_handler import format_player_description
import random
from mud_backend.core.skill_handler import attempt_skill_learning
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.utils import calculate_skill_bonus, get_stat_bonus
from mud_backend.core.registry import VerbRegistry
from mud_backend.verbs.shop import _get_shop_data, _get_item_buy_price, _get_item_type
import re

def _clean_name(name: str) -> str:
    if not name:
        return ""
    return re.sub(r'^(my|the|a|an)\s+', '', name.strip().lower()).strip()

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
    target_room_id = table_obj.get("target_room") or _resolve_interaction_target(table_obj, "enter")

    if not target_room_id:
        # Fallback: check table proxy naming convention if no direct link
        table_name_lower = table_obj.get("name", "").lower()
        for rid, room in world.active_rooms.items():
            if room.name.lower() == table_name_lower and getattr(room, "is_table", False):
                target_room_id = rid
                break

    if target_room_id:
        player_names = world.room_players.get(target_room_id, [])
        return list(player_names)
    return []

def _resolve_interaction_target(obj, verb):
    """Helper to find move targets from interactions."""
    interactions = obj.get("interactions", {})
    if verb in interactions and interactions[verb].get("type") == "move":
        return interactions[verb].get("value")
    # Legacy fallback
    if verb == "enter" and "target_room" in obj:
        return obj["target_room"]
    return None

def _get_item_data_safe(item_ref, world):
    if isinstance(item_ref, dict):
        return item_ref
    return world.game_items.get(item_ref, {})

def _list_container_storage(player, obj, prep):
    """Lists items stored ON/UNDER/IN/BEHIND an object via container_storage."""
    storage = obj.get("container_storage", {})
    items = storage.get(prep, [])

    if not items:
        return False

    # Display Header
    prep_display = prep.upper()
    obj_name = obj.get('name', 'Object')
    player.send_message(f"--- {prep_display} the {obj_name} ---")
    
    # List Items
    for item_ref in items:
        item_data = _get_item_data_safe(item_ref, player.world)
        if item_data:
            name = item_data.get('name', 'something')
            player.send_message(f"- <span class='keyword' data-command='look at {name}'>{name}</span>")
            
    return True

def _list_items_on_table(player, room, table_obj):
    shop_data = _get_shop_data(room)
    has_shop_items = False

    # 1. Shop Items
    if shop_data:
        category = "misc"
        keywords = table_obj.get("keywords", [])
        if "weapon" in keywords or "weapons" in keywords:
            category = "weapon"
        elif "armor" in keywords or "armors" in keywords:
            category = "armor"
        elif "magic" in keywords or "arcane" in keywords or "scrolls" in keywords:
            category = "magic"

        items_on_table = []
        game_items = player.world.game_items
        displayed_names = set()

        for item_ref in shop_data.get("inventory", []):
            if isinstance(item_ref, dict):
                item_data = item_ref
            else:
                item_data = game_items.get(item_ref, {})

            if not item_data:
                continue

            itype = _get_item_type(item_data)
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
                if name not in displayed_names:
                    price = _get_item_buy_price(item_ref, game_items, shop_data)
                    items_on_table.append((name, price))
                    displayed_names.add(name)

        if items_on_table:
            has_shop_items = True
            player.send_message(f"--- On the {table_obj.get('name', 'Table')} (For Sale) ---")
            for name, price in items_on_table:
                player.send_message(f"- <span class='keyword' data-command='buy {name}'>{name}</span> : {price} silver")

    # 2. Player Placed Items (container_storage)
    has_placed_items = _list_container_storage(player, table_obj, "on")

    # 3. Occupants (if no items)
    if not has_shop_items and not has_placed_items:
        if "table" in table_obj.get("keywords", []):
            occupants = _get_table_occupants(player.world, table_obj)
            if occupants:
                count = len(occupants)
                player.send_message(f"It is occupied by {count} person{'s' if count > 1 else ''}.")
            else:
                player.send_message(f"The {table_obj.get('name', 'Table')} is currently empty.")

def _show_room_filtered(player, room, world):
    """
    Local replacement for show_room_to_player to filter hidden entities and provide HTML.
    """
    player.send_message(f"<span class='room-title'>[ {room.name} ]</span>")

    desc = room.description
    if isinstance(desc, dict):
        desc = desc.get('default', list(desc.values())[0] if desc else "")

    player.send_message(f"<span class='room-desc'>{desc}</span>")

    # Highlight Exits
    exit_list = []
    if room.exits:
        for direction, _ in room.exits.items():
            exit_html = f"<span class='keyword' data-command='move {direction}'>{direction.capitalize()}</span>"
            exit_list.append(exit_html)
    exit_str = ", ".join(exit_list) if exit_list else "None"
    player.send_message(f"<span class='room-exits'>Obvious exits: {exit_str}</span>")

    # Highlight Objects (No grouping)
    visible_objects = []
    for obj in room.objects:
        obj_name = obj.get("name", "something")
        obj_html = f"<span class='keyword' data-command='look at {obj_name}'>{obj_name}</span>"
        visible_objects.append(obj_html)

    if visible_objects:
        player.send_message(f"You also see: {', '.join(visible_objects)}.")

    # Highlight Players
    room_players = world.room_players.get(room.room_id, [])
    visible_players = []

    for p_name in room_players:
        if p_name == player.name.lower():
            continue

        target_obj = world.get_player_obj(p_name)
        if not target_obj:
            continue

        if target_obj.is_hidden:
            if target_obj.uid in player.detected_hiders:
                visible_players.append(f"({target_obj.name})")
            continue

        visible_players.append(f"<span class='keyword' data-command='look at {target_obj.name}'>{target_obj.name}</span>")

    if visible_players:
        player.send_message(f"<span class='room-players'>Also here: {', '.join(visible_players)}</span>")


@VerbRegistry.register(["examine", "x"])
class Examine(BaseVerb):
    def execute(self):
        if not self.args:
            self.player.send_message("Examine what?")
            return

        target_name = " ".join(self.args).lower()
        if target_name.startswith("at "):
            target_name = target_name[3:]

        # Clean articles from examine target
        target_name = _clean_name(target_name)

        found_object = None
        for obj in self.room.objects:
            if (target_name == obj.get("name", "").lower() or
                    target_name in obj.get("keywords", [])):
                found_object = obj
                break

        if not found_object:
            # Check inventory/worn
            item_data, loc = _find_item_on_player(self.player, target_name)
            if item_data:
                found_object = item_data
            else:
                self.player.send_message(f"You do not see a **{target_name}** here.")
                return

        self.player.send_message(f"You examine the **{found_object.get('name', 'object')}**.")
        self.player.send_message(found_object.get('description', 'It is a nondescript object.'))

        # Check table contents
        if "table" in found_object.get("keywords", []) and _get_shop_data(self.room):
            _list_items_on_table(self.player, self.room, found_object)
        elif "table" in found_object.get("keywords", []) or found_object.get("is_table_proxy"):
            # Check for placed items first
            if not _list_container_storage(self.player, found_object, "on"):
                occupants = _get_table_occupants(self.world, found_object)
                if occupants:
                    count = len(occupants)
                    self.player.send_message(f"It is occupied by {count} person{'s' if count > 1 else ''}.")
                else:
                    self.player.send_message("It is currently empty.")

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
            _show_room_filtered(self.player, self.room, self.world)
            return

        full_command = " ".join(self.args).lower()

        # 1. Parse Prepositions
        prepositions = ["inside", "into", "under", "behind", "beneath", "in", "on", "at"]
        found_prep = None
        target_name = full_command

        for prep in prepositions:
            if full_command.startswith(f"{prep} "):
                found_prep = prep
                target_name = full_command[len(prep)+1:].strip()
                break
            elif f" {prep} " in full_command:
                # Handle mid-sentence if needed, but strict startswith is safer for LOOK
                pass

        # Clean articles
        target_name = _clean_name(target_name)

        # 2. Find Target
        found_obj = None
        source_loc = "room"

        for obj in self.room.objects:
            if (target_name == obj.get("name", "").lower() or
                target_name in obj.get("keywords", [])):
                found_obj = obj
                break

        if not found_obj:
            item_data, loc = _find_item_on_player(self.player, target_name)
            if item_data:
                found_obj = item_data
                source_loc = loc

        if not found_obj:
            if target_name == "self" or target_name == self.player.name.lower():
                self.player.send_message(f"You see **{self.player.name}** (that's you!).")
                self.player.send_message(format_player_description(self.player.to_dict()))
                return

            target_player_obj = self.world.get_player_obj(target_name)
            if target_player_obj and target_player_obj.current_room_id == self.room.room_id:
                if target_player_obj.is_hidden and target_player_obj.uid not in self.player.detected_hiders:
                    self.player.send_message(f"You do not see a '{target_name}' here.")
                    return
                self.player.send_message(f"You see **{target_player_obj.name}**.")
                self.player.send_message(format_player_description(target_player_obj.to_dict()))
                return

        if not found_obj:
            self.player.send_message(f"You do not see a '{target_name}' here.")
            return

        # 3. Handle Prepositions
        if found_prep:
            if found_prep in ["inside", "into"]:
                found_prep = "in"
            if found_prep == "beneath":
                found_prep = "under"

            found_any = False
            
            # A) Check Interactions (Static) - Display first to give context
            interactions = found_obj.get("interactions", {})
            look_key = f"look {found_prep}"
            if look_key in interactions:
                val = interactions[look_key]
                if val.get("type") == "text":
                    self.player.send_message(val.get("value"))
                    found_any = True

            # B) Check Container Storage (Dynamic)
            # This handles listing items put BEHIND/ON/UNDER/IN the object
            has_items = _list_container_storage(self.player, found_obj, found_prep)
            if has_items:
                found_any = True

            # C) Special case for ON (Tables/Shop) - Legacy support
            if found_prep == "on" and "table" in found_obj.get("keywords", []) and not has_items:
                _list_items_on_table(self.player, self.room, found_obj)
                return

            # D) Container Default
            if found_prep == "in":
                if found_obj.get("is_container"):
                    if found_obj.get("wearable_slot") == "back" and source_loc == "worn":
                        self.player.send_message(f"You look in your {found_obj['name']}:")
                        if not self.player.inventory:
                            self.player.send_message("It is empty.")
                        else:
                            for item_id in self.player.inventory:
                                if isinstance(item_id, dict):
                                    i_d = item_id
                                else:
                                    i_d = self.world.game_items.get(item_id, {})
                                if i_d:
                                    self.player.send_message(f"- {i_d.get('name', 'item')}")
                    else:
                        if not has_items and not found_any:
                             self.player.send_message(f"You look in the {found_obj['name']}.")
                             self.player.send_message("It is empty.")
                    return
                elif not found_any:
                    self.player.send_message(f"You cannot look inside the {found_obj['name']}.")
                    return

            if not found_any:
                self.player.send_message(f"You see nothing special {found_prep} the {found_obj['name']}.")
            return

        # 4. Default Look At
        self.player.send_message(f"You look at the **{found_obj.get('name', 'object')}**.")
        self.player.send_message(found_obj.get('description', 'It is a nondescript object.'))

        if "table" in found_obj.get("keywords", []):
            _list_items_on_table(self.player, self.room, found_obj)


@VerbRegistry.register(["investigate"])
class Investigate(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"):
            return
        _set_action_roundtime(self.player, 3.0)

        self.player.send_message("You investigate the area...")
        attempt_skill_learning(self.player, "investigation")

        # 1. Reveal Hidden Objects
        found_obj = False
        hidden_objects = self.room.data.get("hidden_objects", [])
        if hidden_objects:
            for i in range(len(hidden_objects) - 1, -1, -1):
                obj = hidden_objects[i]
                if obj.get("node_id") or obj.get("node_type"):
                    continue

                dc = obj.get("perception_dc", 100)
                skill_rank = self.player.skills.get("investigation", 0)
                skill_bonus = calculate_skill_bonus(skill_rank)
                roll = random.randint(1, 100) + skill_bonus

                if roll >= dc:
                    found_item = self.room.data["hidden_objects"].pop(i)
                    self.room.objects.append(found_item)
                    found_obj = True
                    self.player.send_message(f"Your investigation reveals: **{found_item.get('name', 'an item')}**!")

        if found_obj:
            self.world.save_room(self.room)

        # 2. Reveal Hidden Players
        per_rank = self.player.skills.get("perception", 0)
        per_bonus = calculate_skill_bonus(per_rank)
        wis_bonus = get_stat_bonus(self.player.stats.get("WIS", 50), "WIS", self.player.stat_modifiers)
        searcher_roll = random.randint(1, 100) + per_bonus + wis_bonus

        found_person = False
        room_players = self.world.room_players.get(self.room.room_id, [])
        for p_name in room_players:
            if p_name == self.player.name.lower():
                continue
            target_obj = self.world.get_player_obj(p_name)
            if not target_obj or not target_obj.is_hidden:
                continue
            if target_obj.uid in self.player.detected_hiders:
                continue

            dis_b = get_stat_bonus(target_obj.stats.get("DIS", 50), "DIS", target_obj.stat_modifiers)
            dex_b = get_stat_bonus(target_obj.stats.get("DEX", 50), "DEX", target_obj.stat_modifiers)
            sh_rank = target_obj.skills.get("stalking_and_hiding", 0)
            sh_bonus = calculate_skill_bonus(sh_rank)
            hider_roll = random.randint(1, 100) + dis_b + dex_b + sh_bonus

            if searcher_roll > hider_roll:
                self.player.detected_hiders.append(target_obj.uid)
                self.player.send_message(f"You notice the distinct outline of **{target_obj.name}** hiding nearby!")
                target_obj.send_message(f"**{self.player.name}** looks right at your hiding spot!")
                found_person = True

        if not found_obj and not found_person:
            self.player.send_message("...but you don't find anything unusual.")

@VerbRegistry.register(["point"])
class Point(BaseVerb):
    def execute(self):
        if not self.args:
            self.player.send_message("Point at whom?")
            return
        target_name = " ".join(self.args).lower()
        target_obj = self.world.get_player_obj(target_name)

        if not target_obj or target_obj.current_room_id != self.room.room_id:
            self.player.send_message(f"You do not see {target_name} here.")
            return

        if not target_obj.is_hidden:
            self.player.send_message(f"You point at {target_obj.name}.")
            self.world.broadcast_to_room(self.room.room_id, f"{self.player.name} points at {target_obj.name}.", "message", skip_sid=self.player.get("sid"))
        elif target_obj.uid in self.player.detected_hiders:
            target_obj.is_hidden = False
            self.player.send_message(f"You point triumphantly at {target_obj.name}, revealing their location!")
            target_obj.send_message(f"**{self.player.name}** points right at you, revealing you!")
            self.world.broadcast_to_room(self.room.room_id, f"{self.player.name} points at a shadow, revealing {target_obj.name}!", "message", skip_sid=self.player.get("sid"))
            if target_obj.uid in self.player.detected_hiders:
                self.player.detected_hiders.remove(target_obj.uid)
        else:
            self.player.send_message(f"You do not see {target_name} here.")

@VerbRegistry.register(["inspect"])
class Inspect(BaseVerb):
    def execute(self):
        if not self.args:
            self.player.send_message("Inspect what?")
            return
        target_name = " ".join(self.args).lower()
        item_data, loc = _find_item_on_player(self.player, target_name)

        if not item_data:
            shop_data = _get_shop_data(self.room)
            if shop_data:
                for item_ref in shop_data.get("inventory", []):
                    t_data = item_ref if isinstance(item_ref, dict) else self.world.game_items.get(item_ref, {})
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

        shop_data = _get_shop_data(self.room)
        if shop_data:
            price = _get_item_buy_price(item_data, self.world.game_items, shop_data)
            self.player.send_message(f"Estimated Shop Price: {price} silver")