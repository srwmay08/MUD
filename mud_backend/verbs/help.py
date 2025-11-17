# mud_backend/verbs/help.py
from mud_backend.verbs.base_verb import BaseVerb

# ---
# --- MODIFIED: Added GROUP, BAND, WHISPER help
# ---
HELP_TEXT = {
    "look": """
<span class='room-title'>--- Help: LOOK ---</span>
LOOK is the most basic of commands. Almost everything can be the target of this verb, particularly locations, objects, creatures, and characters. Use this command to garner information about every piece of the world.

**Usage:**
* **LOOK**: Displays the room description (what it looks like, what is there, who is there).
* **LOOK {character}**: Displays the description of the person, what they're carrying, what they're wearing, and any wounds or scars they may possess.
* **LOOK {creature}**: Displays what a creature is carrying, what they're wearing, and any wounds or scars they may possess.
* **LOOK {at|on|in|inside|into|under|behind|beneath} {object}**: Displays information pertaining to where you looked or what you looked at.
* **LOOK {up|star|constellation|sky}**: Displays the sky and any adverse weather conditions.
""",

    "examine": """
<span class='room-title'>--- Help: EXAMINE ---</span>
EXAMINE is used to understand the properties of creatures, items, objects, weapons, armor, and magic items you come across.

**Usage:**
* **EXAMINE {creature}**: Used on a target to determine a character's ability in combat against that creature.
* **EXAMINE {item}**: Used on an item to determine its strength, durability, integrity, and any additional properties.
""",

    "investigate": """
<span class='room-title'>--- Help: INVESTIGATE ---</span>
INVESTIGATE is used to find hidden or obscured objects within a room, often at the cost of a roundtime.

**Usage:**
* **INVESTIGATE**: Automatically searches the whole room for all hidden, obscure, or non-obvious creatures, players, objects, and items.
* **INVESTIGATE {target}**: You can also investigate specific things, like `INVESTIGATE DOOR`, `INVESTIGATE CRACK`, or `INVESTIGATE TABLE`.
""",

    "move": """
<span class='room-title'>--- Help: MOVE / GO ---</span>
MOVE (or GO) is a mechanical verb used for movement. It is used to traverse portals, doors, gates, etc.

**Usage:**
* You can type the full direction: `MOVE NORTH`, `GO SOUTH`.
* You can use abbreviations: `N`, `S`, `E`, `W`, `NE`, `NW`, `SE`, `SW`.
* You can also move through special exits: `IN`, `OUT`, 'UP', `DOWN`.
* Often, just typing the exit name is enough: `OUT`.
""",

    "goto": """
<span class='room-title'>--- Help: GOTO ---</span>
GOTO is a fast-travel command that automatically moves you to well-known locations, provided you have a clear path.

**Usage:**
* **GOTO {location}**: Begins automatically walking to the target location (e.g., `GOTO TOWNHALL`, `GOTO INN`).
""",

    "get": """
<span class='room-title'>--- Help: GET / TAKE ---</span>
GET (or TAKE) is used to pick up items from the ground or from containers and place them in your hands.

**Usage:**
* **GET {item}**: Gets an item from the ground and puts it in your free hand. If your hands are full, it goes to your pack.
* **GET {item} FROM {container}**: Gets an item from a container (like a backpack) and moves it to your free hand.
""",

    "stow": """
<span class='room-title'>--- Help: STOW / PUT ---</span>
STOW (or PUT) is used to move items from your hands into a container.

**Usage:**
* **STOW {item}**: Puts an item from your hand into your main backpack.
* **PUT {item} IN {container}**: Puts an item from your hand into a specific container (e.g., `PUT DAGGER IN SHEATH`).
""",

    "inventory": """
<span class='room-title'>--- Help: INVENTORY (INV) ---</span>
Displays what you are currently holding, wearing, and carrying in your containers.

**Usage:**
* **INVENTORY** or **INV**: Shows a list of your items.
""",

    "wealth": """
<span class='room-title'>--- Help: WEALTH ---</span>
Displays how much silver you are currently carrying.

**Usage:**
* **WEALTH**: Shows your silver total.
* **WEALTH LOUD**: Shouts your silver total to the room (not recommended!).
""",

    "talk": """
<span class='room-title'>--- Help: TALK ---</span>
TALK is used to interact with non-player characters (NPCs) in the world. This is the primary way to receive quests and learn information.

**Usage:**
* **TALK TO {npc}**: Initiates a conversation with the target NPC.
* **TALK {npc}**: A shortcut for `TALK TO`.
""",

    "list": """
<span class='room-title'>--- Help: LIST ---</span>
When at a shop, use LIST to see what the merchant is selling.

**Usage:**
* **LIST**: Shows all items for sale and their prices.
""",

    "buy": """
<span class'room-title'>--- Help: BUY ---</span>
When at a shop, use BUY to purchase an item. (You can also use ORDER).

**Usage:**
* **BUY {item name}**: Purchases the specified item from the shop.
* **ORDER {item name}**: An alias for BUY.
""",

    "sell": """
<span class'room-title'>--- Help: SELL ---</span>
When at a shop, use SELL to sell an item *from your hands* to the merchant.

**Usage:**
* **SELL {item name}**: Sells the item you are holding.
* **SELL BACKPACK**: Has the merchant appraise and buy *all* valid items from your backpack.
""",

    "forage": """
<span class'room-title'>--- Help: FORAGE ---</span>
FORAGE allows you to search the area for harvestable herbs and plants. This costs roundtime.

**Usage:**
* **FORAGE**: Searches the area for anything you can find.
""",

    "attack": """
<span class'room-title'>--- Help: ATTACK ---</span>
ATTACK initiates combat with a target. This command will continue to swing at your target automatically until you or the target is defeated, or you `FLEE`.

**Usage:**
* **ATTACK {target}**: Begins combat.
* **FLEE**: (Not yet implemented) Stops combat and attempts to move to a random room.
""",

    "stance": """
<span class'room-title'>--- Help: STANCE ---</span>
STANCE allows you to change your combat footing to be more offensive or defensive.

**Usage:**
* **STANCE {type}**: Changes your stance (e.g., `STANCE OFFENSIVE`, `STANCE DEFENSIVE`, `STANCE NEUTRAL`).
* **STANCE**: Shows your current stance.
""",

    "stats": """
<span class='room-title'>--- Help: Character Attributes ---</span>
Your character is defined by 12 core attributes, grouped into four categories.

<span class='room-title'>--- Physical Attributes (4) ---</span>
* **Strength (STR):** Measures physical prowess, affecting melee Attack Strength and encumbrance.
* **Constitution (CON):** Measures physical durability, affecting maximum Health Points, disease resistance, and critical hits.
* **Dexterity (DEX):** Measures hand-eye coordination and fine motor skills, aiding precision tasks like picking locks, skinning, and ranged/targeted attacks.
* **Agility (AGI):** Measures grace in motion and nimbleness, affecting balance, maneuverability, and Defensive Strength (DS).

<span class='room-title'>--- Mental Attributes (4) ---</span>
* **Logic (LOG):** Measures capacity for critical and rational thought, affecting learn by doing experience, experience absorption, and activating magical items/scrolls.
* **Intuition (INT):** Measures innate "sixth sense," perception, and luck; the ability to "know" without conscious deduction. Tied to the use of Elemental/Sorcerous magic.
* **Wisdom (WIS):** Measures common sense, pragmatism, and a conscious connection with spirituality. Tied to the use of Spiritual magic.
* **Influence (INF):** Measures the ability to affect others through leadership, persuasion, intimidation, or charm. Tied to mind-affecting abilities.

<span class='room-title'>--- Spiritual Attributes (2) ---</span>
* **Zeal (ZEA):** Measures the power of a character's active conviction and divine connection. While Wisdom understands the spiritual, Zeal channels it. This stat could govern the power of divine abilities (like turning undead), the potency of healing magic, and resistance to corrupting or unholy influences.
* **Essence (ESS):** Measures the substance and health of the character's soul. While the Constitution is physical health, Essence is spiritual health. It could determine a character's resistance to life-draining effects, possession, and "soul-damage," and might also serve as a secondary energy pool for certain non-magical abilities.

<span class='room-title'>--- Hybrid Attributes (2) ---</span>
* **Discipline (DIS):** Measures force of will, determination, and focus. A classic hybrid stat bridging Mental and Spiritual, it affects experience-gain limits and resistance to mental/emotional attacks.
* **Aura (AUR):** Measures the innate connection to spiritual, mental, and elemental magic. A hybrid stat bridging Mental and Spiritual, it determines the total pool of Spirit Points (SP).
""",

    "group": """
<span class='room-title'>--- Help: GROUP ---</span>
Manages the online-only grouping system.

**Usage:**
* **GROUP**: Shows your current group status.
* **GROUP OPEN**: Allows others to invite you. (Alias for FLAG GROUPINVITES ON)
* **GROUP CLOSE**: Prevents others from inviting you. (Alias for FLAG GROUPINVITES OFF)
* **GROUP {player}**: Invites {player} to join your group. (Leader only)
* **GROUP LEADER {player}**: Makes {player} the new group leader. (Leader only)
* **GROUP REMOVE {player}**: Removes {player} from the group. (Leader only)
* **JOIN {player}**: Accepts an invitation from {player}.
* **LEAVE**: Leaves your current group.
* **DISBAND**: Disbands a group you are leading.
* **HOLD {player}**: (Roleplay) Invites {player} to join your group.
* **WHISPER GROUP {msg}**: Sends a private message to all group members.
* **WHISPER OOC GROUP {msg}**: Sends a private OOC message to all group members.
""",

    "band": """
<span class='room-title'>--- Help: BAND ---</span>
Manages your persistent Adventuring Band for XP sharing.

**Usage:**
* **BAND CREATE**: Creates a new adventuring band with you as leader.
* **BAND INVITE {name}**: Invites {name} to join your band. (Leader only)
* **BAND JOIN {leader_name}**: Accepts a pending invitation from {leader_name}.
* **BAND LIST**: Lists all members in your band.
* **BAND REMOVE**: Removes you from your adventuring band.
* **BAND KICK {name}**: Kicks {name} from your band. (Leader only)
* **BAND DELETE**: Deletes the entire adventuring band. (Leader only)
* **BT {message}**: (Band Talk) Sends a message to all online band members.
""",

    "whisper": """
<span class='room-title'>--- Help: WHISPER ---</span>
Sends a private message to a player or your group.

**Usage:**
* **WHISPER {player} {message}**: Sends a private message to {player}.
* **WHISPER GROUP {message}**: Sends a private message to all group members.
* **WHISPER OOC GROUP {message}**: Sends a private OOC message to all group members.
"""
}
# --- END NEW ---


class Help(BaseVerb):
    """
    Handles the 'help' command.
    """
    
    def execute(self):
        if not self.args:
            self.player.send_message("What do you need help with? (e.g., HELP LOOK, HELP GET, HELP STATS, HELP GROUP, HELP BAND)")
            # TODO: List all available help topics
            return

        target_topic = " ".join(self.args).lower()
        
        # ---
        # --- MODIFIED: Added new aliases
        # ---
        if target_topic in ["go", "n", "s", "e", "w"]:
            target_topic = "move"
        if target_topic == "take":
            target_topic = "get"
        if target_topic == "put":
            target_topic = "stow"
        if target_topic == "inv":
            target_topic = "inventory"
        if target_topic == "goto":
            target_topic = "goto"
        if target_topic in ["buy", "order"]:
            target_topic = "buy"
        if target_topic == "sell":
            target_topic = "sell"
        if target_topic == "forage":
            target_topic = "forage"
        if target_topic == "attack":
            target_topic = "attack"
        if target_topic == "stance":
            target_topic = "stance"
        if target_topic == "wealth":
            target_topic = "wealth"
            
        # Grouping Aliases
        if target_topic in ["join", "leave", "disband", "hold"]:
            target_topic = "group"
        # Band Aliases
        if target_topic == "bt":
            target_topic = "band"
        # Whisper Alias
        if target_topic == "whisper":
            target_topic = "whisper"
        # ---
        # --- END MODIFIED
        # ---
            
        # --- NEW: Aliases for all 12 stats ---
        if target_topic in [
            "str", "con", "dex", "agi", "log", "int", "wis", "inf",
            "zea", "ess", "dis", "aur", "attributes", "statistics"
        ]:
            target_topic = "stats"
        # --- END NEW ---

        help_content = HELP_TEXT.get(target_topic)
        
        if help_content:
            self.player.send_message(help_content)
        else:
            self.player.send_message(f"Sorry, there is no help topic available for '{target_topic}'.")