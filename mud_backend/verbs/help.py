# mud_backend/verbs/help.py
from mud_backend.verbs.base_verb import BaseVerb

# --- NEW: Help text data ---
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

**Example (Item):**
> Careful examination indicates the grey leather has a base strength of 20 and a base durability of 285. You also determine the current integrity of the grey leather to be at 100.0%.
> You examine the grey leather closely, lightly running your fingers over the material.
> You sense that the leather is imbued with the magic of nature...
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
* You can also move through special exits: `IN`, `OUT`, `UP`, `DOWN`.
* Often, just typing the exit name is enough: `OUT`.
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
* **INVENTORY FULL**: (Not yet implemented) Shows a detailed list.
""",

    # ---
    # --- NEW: Help for TALK
    # ---
    "talk": """
<span class='room-title'>--- Help: TALK ---</span>
TALK is used to interact with non-player characters (NPCs) in the world. This is the primary way to receive quests and learn information.

**Usage:**
* **TALK TO {npc}**: Initiates a conversation with the target NPC.
* **TALK {npc}**: A shortcut for `TALK TO`.

**Example:**
> TALK TO INNKEEPER
""",
    # ---
    # --- END NEW
    # ---

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
"""
}
# --- END HELP TEXT ---


class Help(BaseVerb):
    """
    Handles the 'help' command.
    """
    
    def execute(self):
        if not self.args:
            self.player.send_message("What do you need help with? (e.g., HELP LOOK, HELP GET, HELP STATS)")
            # TODO: List all available help topics
            return

        target_topic = " ".join(self.args).lower()
        
        # Simple alias check
        if target_topic in ["go", "n", "s", "e", "w"]:
            target_topic = "move"
        if target_topic == "take":
            target_topic = "get"
        if target_topic == "put":
            target_topic = "stow"
        if target_topic == "inv":
            target_topic = "inventory"
            
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