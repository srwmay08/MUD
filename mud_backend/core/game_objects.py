# mud_backend/core/game_objects.py
import math
import time
import copy
import uuid
import threading
from mud_backend import config
from mud_backend.core.utils import calculate_skill_bonus, get_stat_bonus
from mud_backend.core.entities import GameEntity
from typing import Optional, List, Dict, Any, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

class Player(GameEntity):
    def __init__(self, world: 'World', name: str, current_room_id: str, db_data: Optional[dict] = None):
        uid = db_data.get("_id") if db_data else None
        if not uid: uid = uuid.uuid4().hex
        super().__init__(uid=str(uid), name=name, data=db_data)
        
        self.is_player = True
        self.world = world 
        self.lock = threading.RLock()
        
        self.current_room_id = current_room_id
        self.account_username: str = self.data.get("account_username", "")
        self.is_admin: bool = self.data.get("is_admin", False)
        
        if self.account_username.lower() in getattr(config, 'ADMIN_ACCOUNTS', []):
            self.is_admin = True
        
        self.messages = [] 
        
        # --- QoL Storage ---
        self.aliases = self.data.get("aliases", {})
        self.message_history = self.data.get("message_history", [])
        
        # --- NEW: Social Lists ---
        self.friends = self.data.get("friends", [])
        self.ignored = self.data.get("ignored", [])
        # -------------------------

        self._is_dirty = False
        self._last_save_time = time.time()
        self.command_queue: List[str] = [] 

        self.experience: int = self.data.get("experience", 0)
        self.unabsorbed_exp: int = self.data.get("unabsorbed_exp", 0)
        self.level: int = self.data.get("level", 0)
        self.stats: Dict[str, int] = self.data.get("stats", {})
        
        self.current_stat_pool = self.data.get("current_stat_pool", [])
        self.best_stat_pool = self.data.get("best_stat_pool", [])
        self.stats_to_assign = self.data.get("stats_to_assign", [])
        self.ptps = self.data.get("ptps", 0)
        self.mtps = self.data.get("mtps", 0)
        self.stps = self.data.get("stps", 0)
        self.ranks_trained_this_level = self.data.get("ranks_trained_this_level", {})
        
        self.game_state = self.data.get("game_state", "playing")
        self.chargen_step = self.data.get("chargen_step", 0)
        self.appearance = self.data.get("appearance", {})
        self.skills = self.data.get("skills", {})
        self.skill_learning_progress = self.data.get("skill_learning_progress", {})
        
        self._hp = min(self.data.get("hp", 100), self.max_hp)
        self._mana = min(self.data.get("mana", 100), self.max_mana)
        self._stamina = min(self.data.get("stamina", 100), self.max_stamina)
        self._spirit = min(self.data.get("spirit", 10), self.max_spirit)
        
        self.inventory = self.data.get("inventory", [])
        self.worn_items = self.data.get("worn_items", {})
        for slot_key in config.EQUIPMENT_SLOTS.keys():
            if slot_key not in self.worn_items: self.worn_items[slot_key] = None
            
        self.wealth = self.data.get("wealth", {"silvers": 0, "notes": [], "bank_silvers": 0})
        self.stance = self.data.get("stance", "neutral")
        self.posture = self.data.get("posture", "standing")
        self.status_effects = self.data.get("status_effects", [])
        self.next_action_time = self.data.get("next_action_time", 0.0)
        
        self.deaths_recent = self.data.get("deaths_recent", 0)
        self.death_sting_points = self.data.get("death_sting_points", 0)
        self.con_lost = self.data.get("con_lost", 0)
        self.con_recovery_pool = self.data.get("con_recovery_pool", 0)
        
        # --- WOUNDS & SCARS ---
        self.wounds = self.data.get("wounds", {})
        self.scars = self.data.get("scars", {})
        # ----------------------

        self.next_mana_pulse_time = self.data.get("next_mana_pulse_time", 0.0)
        self.mana_pulse_used = self.data.get("mana_pulse_used", False)
        self.last_spellup_use_time = self.data.get("last_spellup_use_time", 0.0)
        self.spellup_uses_today = self.data.get("spellup_uses_today", 0)
        self.last_second_wind_time = self.data.get("last_second_wind_time", 0.0)
        self.stamina_burst_pulses = self.data.get("stamina_burst_pulses", 0) 
        self.prepared_spell = self.data.get("prepared_spell", None)
        self.buffs = self.data.get("buffs", {})
        self.known_spells = self.data.get("known_spells", [])
        self.known_maneuvers = self.data.get("known_maneuvers", [])
        self.completed_quests = self.data.get("completed_quests", [])
        self.factions = self.data.get("factions", {})
        self.deities = self.data.get("deities", []) 
        self.guilds = self.data.get("guilds", [])   
        self.flags = self.data.get("flags", {})
        self.quest_counters = self.data.get("quest_counters", {})
        
        if self.data.get("quest_trip_counter"):
            self.quest_counters["trip_training_attempts"] = self.data.get("quest_trip_counter")

        self.visited_rooms = self.data.get("visited_rooms", [])
        self.is_goto_active = self.data.get("is_goto_active", False)
        self.goto_id = None 
        self.group_id = self.data.get("group_id", None) 
        self.band_id = self.data.get("band_id", None) 
        self.band_xp_bank = self.data.get("band_xp_bank", 0) 
        
        self.locker = self.data.get("locker", {
            "capacity": 50,
            "items": [],
            "rent_due": 0
        })
        
        self.temp_leave_message = None
        self.level_xp_target = self._get_xp_target_for_level(self.level)

    def mark_dirty(self): self._is_dirty = True

    def is_ignoring(self, other_name: str) -> bool:
        return other_name.lower() in self.ignored

    def is_friend(self, other_name: str) -> bool:
        return other_name.lower() in self.friends

    @property
    def race(self) -> str: 
        return self.appearance.get("race", "Human")

    @property
    def race_data(self) -> dict:
        return self.world.game_races.get(self.race, self.world.game_races.get("Human", {}))

    @property
    def stat_modifiers(self) -> dict:
        return self.race_data.get("stat_modifiers", {})

    @property
    def con_bonus(self) -> int: 
        return get_stat_bonus(self.stats.get("CON", 50), "CON", self.stat_modifiers)

    @property
    def base_hp(self) -> int: 
        return math.trunc((self.stats.get("STR", 0) + self.stats.get("CON", 0)) / 10)

    @property
    def max_hp(self) -> int:
        base_hp_val = self.base_hp
        pf_ranks = self.skills.get("physical_fitness", 0)
        hp_gain_rate = self.race_data.get("hp_gain_per_pf_rank", 6)
        return base_hp_val + (pf_ranks * hp_gain_rate)

    @property
    def max_mana(self) -> int:
        int_b = get_stat_bonus(self.stats.get("INT", 50), "INT", self.stat_modifiers)
        log_b = get_stat_bonus(self.stats.get("LOG", 50), "LOG", self.stat_modifiers)
        wis_b = get_stat_bonus(self.stats.get("WIS", 50), "WIS", self.stat_modifiers)
        inf_b = get_stat_bonus(self.stats.get("INF", 50), "INF", self.stat_modifiers)
        hp_ranks = self.skills.get("harness_power", 0)
        mc_ranks = self.skills.get("mana_control", 0)
        hp_bonus = calculate_skill_bonus(hp_ranks)
        mc_bonus = calculate_skill_bonus(mc_ranks)
        stat_avg = math.trunc((log_b + wis_b + inf_b) / 3)
        hp_avg = math.trunc(hp_bonus / 4)
        mc_avg = math.trunc(mc_bonus / 3)
        return int_b + stat_avg + hp_avg + mc_avg

    @property
    def max_stamina(self) -> int:
        con_b = get_stat_bonus(self.stats.get("CON", 50), "CON", self.stat_modifiers)
        str_b = get_stat_bonus(self.stats.get("STR", 50), "STR", self.stat_modifiers)
        agi_b = get_stat_bonus(self.stats.get("AGI", 50), "AGI", self.stat_modifiers)
        dis_b = get_stat_bonus(self.stats.get("DIS", 50), "DIS", self.stat_modifiers)
        pf_ranks = self.skills.get("physical_fitness", 0)
        pf_bonus = calculate_skill_bonus(pf_ranks)
        stat_avg = math.trunc((str_b + agi_b + dis_b) / 3)
        pf_avg = math.trunc(pf_bonus / 3)
        return con_b + stat_avg + pf_avg

    @property
    def max_spirit(self) -> int:
        ess_b = get_stat_bonus(self.stats.get("ESS", 50), "ESS", self.stat_modifiers)
        zea_b = get_stat_bonus(self.stats.get("ZEA", 50), "ZEA", self.stat_modifiers)
        wis_b = get_stat_bonus(self.stats.get("WIS", 50), "WIS", self.stat_modifiers)
        log_b = get_stat_bonus(self.stats.get("LOG", 50), "LOG", self.stat_modifiers)
        hp_ranks = self.skills.get("harness_power", 0)
        sc_ranks = self.skills.get("spiritual_lore", 0) 
        hp_bonus = calculate_skill_bonus(hp_ranks)
        sc_bonus = calculate_skill_bonus(sc_ranks)
        stat_avg = math.trunc((zea_b + wis_b + log_b) / 3)
        hp_avg = math.trunc(hp_bonus / 4)
        sc_avg = math.trunc(sc_bonus / 3)
        return 10 + ess_b + stat_avg + hp_avg + sc_avg

    @property
    def body_weight(self) -> int:
        RACE_WEIGHTS = {
            "Human": 207, "Wildborn": 210, "High Elf": 160, "Dwarf": 180,
            "Gnome": 60, "Halfling": 90, "Dark Elf": 150, "Dark Dwarf": 190,
            "Troll": 360, "Goblin": 100
        }
        return RACE_WEIGHTS.get(self.race, 180)

    @property
    def max_carry_weight(self) -> float:
        str_stat = self.stats.get("STR", 50)
        term_1 = math.trunc((str_stat - 20) / 200.0 * 100) / 100.0 * self.body_weight
        term_2 = self.body_weight / 200.0
        return max(5.0, term_1 + term_2)

    @property
    def current_encumbrance(self) -> float:
        total_weight = 0.0
        for item_id in self.inventory:
            item = self.world.game_items.get(item_id)
            if item: total_weight += item.get("weight", 1) 
        for slot, item_id in self.worn_items.items():
            if item_id:
                item = self.world.game_items.get(item_id)
                if item: total_weight += item.get("weight", 1)
        return total_weight

    @property
    def hp(self): return self._hp
    @hp.setter
    def hp(self, value):
        if self._hp != value:
            self._hp = value
            self.mark_dirty()
    @property
    def mana(self): return self._mana
    @mana.setter
    def mana(self, value):
        if self._mana != value:
            self._mana = value
            self.mark_dirty()
    @property
    def stamina(self): return self._stamina
    @stamina.setter
    def stamina(self, value):
        if self._stamina != value:
            self._stamina = value
            self.mark_dirty()
    @property
    def spirit(self): return self._spirit
    @spirit.setter
    def spirit(self, value):
        if self._spirit != value:
            self._spirit = value
            self.mark_dirty()

    @property
    def hp_regeneration(self) -> int:
        pf_ranks = self.skills.get("physical_fitness", 0)
        base_regen = 2
        regen = base_regen + math.trunc(pf_ranks / 20)
        if self.death_sting_points > 0: regen = math.trunc(regen * 0.5)
        return max(0, regen)

    @property
    def stamina_regen_per_pulse(self) -> int:
        con_b = get_stat_bonus(self.stats.get("CON", 50), "CON", self.stat_modifiers)
        bonus = 0
        if self.posture in ["sitting", "kneeling", "prone"]:
            if self.worn_items.get("mainhand") is None: bonus = 5
        sr_percent = 20 + math.trunc(con_b / 4.5) + bonus
        enhancive_bonus = 0
        if self.stamina_burst_pulses > 0: enhancive_bonus = 15
        elif self.stamina_burst_pulses < 0: enhancive_bonus = -15
        gain = round(self.max_stamina * (sr_percent / 100.0)) + enhancive_bonus
        return int(gain)

    @property
    def mana_regeneration_per_pulse(self) -> int:
        int_b = get_stat_bonus(self.stats.get("INT", 50), "INT", self.stat_modifiers)
        hp_ranks = self.skills.get("harness_power", 0)
        hp_bonus = calculate_skill_bonus(hp_ranks)
        bonus = 0 
        mr_percent = 10 + math.trunc(int_b / 4.5) + math.trunc(hp_bonus / 20) + bonus
        enhancive_bonus = 0
        gain = round(self.max_mana * (mr_percent / 100.0)) + enhancive_bonus
        return int(gain)

    @property
    def spirit_regeneration_per_pulse(self) -> int:
        ess_b = get_stat_bonus(self.stats.get("ESS", 50), "ESS", self.stat_modifiers)
        hp_ranks = self.skills.get("harness_power", 0)
        hp_bonus = calculate_skill_bonus(hp_ranks)
        bonus = 0 
        spr_percent = 10 + math.trunc(ess_b / 4.5) + math.trunc(hp_bonus / 20) + bonus
        enhancive_bonus = 0
        gain = round(self.max_spirit * (spr_percent / 100.0)) + enhancive_bonus
        return int(gain)

    @property
    def effective_mana_control_ranks(self) -> int:
        return self.skills.get("elemental_lore", 0)

    @property
    def armor_rt_penalty(self) -> float:
        armor_id = self.worn_items.get("torso")
        if not armor_id: return 0.0
        armor_data = self.world.game_items.get(armor_id)
        if not armor_data: return 0.0
        base_rt = armor_data.get("armor_rt", 0)
        if base_rt == 0: return 0.0
        armor_use_ranks = self.skills.get("armor_use", 0)
        skill_bonus = calculate_skill_bonus(armor_use_ranks)
        if skill_bonus < 10: return base_rt
        penalty_removed = 1 + math.floor(max(0, skill_bonus - 10) / 20)
        final_penalty = max(0.0, base_rt - penalty_removed)
        return final_penalty

    @property
    def field_exp_capacity(self) -> int:
        return 800 + self.stats.get("LOG", 0) + self.stats.get("DIS", 0)

    @property
    def mind_status(self) -> str:
        if self.unabsorbed_exp <= 0: return "clear as a bell"
        capacity = self.field_exp_capacity
        if capacity == 0: return "completely saturated"
        saturation = self.unabsorbed_exp / capacity
        if saturation > 1.0: return "completely saturated"
        if saturation > 0.9: return "must rest"
        if saturation > 0.75: return "numbed"
        if saturation > 0.62: return "becoming numbed"
        if saturation > 0.5: return "muddled"
        if saturation > 0.25: return "clear"
        return "fresh and clear"

    def grant_experience(self, nominal_amount: int, source: str = "combat", instant: bool = False):
        if self.death_sting_points > 0:
            original_nominal = nominal_amount
            nominal_amount = math.trunc(original_nominal * 0.25)
            points_worked_off = original_nominal - nominal_amount
            old_sting = self.death_sting_points
            self.death_sting_points -= points_worked_off
            if self.death_sting_points <= 0:
                self.death_sting_points = 0
                if old_sting > 0: self.send_message("You feel the last of death's sting fade.")
            else:
                 self.send_message(f"(You work off {points_worked_off} of death's sting.)")
        self.mark_dirty()

        band = self.world.get_band(self.band_id)
        if band:
            num_members = len(band.get("members", []))
            if num_members > 0:
                share = math.trunc(nominal_amount / num_members)
                
                if instant:
                     self.experience += share
                     self.send_message(f"You gain {share} experience from your band (Instant).")
                     self._check_for_level_up()
                else:
                     self.add_field_exp(share, is_band_share=True)

                for member_key in band.get("members", []):
                    if member_key == self.name.lower(): continue 
                    member_obj = self.world.get_player_obj(member_key)
                    if member_obj:
                        if member_obj.death_sting_points > 0:
                            member_obj.band_xp_bank += share
                            member_obj.mark_dirty()
                        else:
                            if instant:
                                member_obj.experience += share
                                member_obj.send_message(f"You gain {share} experience from your band (Instant).")
                                member_obj._check_for_level_up()
                                member_obj.mark_dirty()
                            else:
                                member_obj.add_field_exp(share, is_band_share=True)
                    else:
                        self.world.event_bus.emit("update_band_xp", player_name=member_key, amount=share)
                return 
        
        if instant:
            self.experience += nominal_amount
            self.send_message(f"You gain {nominal_amount} experience.")
            self._check_for_level_up()
        else:
            self.add_field_exp(nominal_amount)

    def add_field_exp(self, nominal_amount: int, is_band_share: bool = False):
        pool_cap = self.field_exp_capacity
        current_pool = self.unabsorbed_exp
        if current_pool >= pool_cap:
            if not is_band_share: self.send_message("Your mind is completely saturated. You can learn no more.")
            return
        accrual_decline_factor = 1.0 - (0.05 * math.floor(current_pool / 100.0))
        actual_gained = math.trunc(nominal_amount * accrual_decline_factor)
        if actual_gained <= 0:
            if not is_band_share and nominal_amount > 0: self.send_message("Your mind is too full to learn from this.")
            return
        if current_pool + actual_gained > pool_cap:
            actual_gained = pool_cap - current_pool
            self.unabsorbed_exp = pool_cap
            if not is_band_share: self.send_message(f"Your mind is saturated! You only gain {actual_gained} experience.")
            else: self.send_message(f"You gain {actual_gained} experience from your band, saturating your mind.")
        else:
            self.unabsorbed_exp += actual_gained
            if not is_band_share: self.send_message(f"You gain {actual_gained} field experience. ({self.mind_status})")
            else: self.send_message(f"You gain {actual_gained} field experience from your band. ({self.mind_status})")
        self.mark_dirty()

    def absorb_exp_pulse(self, room_type: str = "other") -> Optional[str]:
        if self.unabsorbed_exp <= 0: return None
        base_rate = 19
        logic_divisor = 7
        if room_type == "on_node":
            base_rate = 25
            logic_divisor = 5
        elif room_type == "in_town":
            base_rate = 22
            logic_divisor = 5
        logic_bonus = math.floor(self.stats.get("LOG", 0) / logic_divisor)
        pool_bonus = min(10, math.floor(self.unabsorbed_exp / 200.0))
        group_bonus = 0 
        amount_to_absorb = int(base_rate + logic_bonus + pool_bonus + group_bonus)
        amount_to_absorb = min(self.unabsorbed_exp, amount_to_absorb)
        if amount_to_absorb <= 0: return None
        self.unabsorbed_exp -= amount_to_absorb
        self.experience += amount_to_absorb
        self.mark_dirty()
        absorption_msg = None
        if self.con_lost > 0:
            self.con_recovery_pool += amount_to_absorb
            points_to_regain = self.con_recovery_pool // 2000
            if points_to_regain > 0:
                regained = min(points_to_regain, self.con_lost)
                self.stats["CON"] = self.stats.get("CON", 50) + regained
                self.con_lost -= regained
                self.con_recovery_pool -= (regained * 2000)
                absorption_msg = f"You feel some of your vitality return! (Recovered {regained} CON)"
                self.mark_dirty()
        self._check_for_level_up() 
        return absorption_msg

    def _get_xp_target_for_level(self, level: int) -> int:
        table = self.world.game_level_table
        if not table: return (level + 1) * 1000
        if level < 0: return 0
        if level >= 100: return self.experience + 2500 
        if level < len(table): return table[level]
        else: return self.experience + 999999

    def _calculate_tps_per_level(self) -> Tuple[int, int, int]:
        s = self.stats
        hybrid_bonus = (s.get("AUR", 0) + s.get("DIS", 0)) / 2
        mtp_calc = 25 + ((s.get("LOG", 0) + s.get("INT", 0) + s.get("WIS", 0) + s.get("INF", 0) + hybrid_bonus) / 20)
        ptp_calc = 25 + ((s.get("STR", 0) + s.get("CON", 0) + s.get("DEX", 0) + s.get("AGI", 0) + hybrid_bonus) / 20)
        stp_calc = 25 + ((s.get("WIS", 0) + s.get("INF", 0) + s.get("ZEA", 0) + s.get("ESS", 0) + hybrid_bonus) / 20)
        return int(ptp_calc), int(mtp_calc), int(stp_calc)

    def _check_for_level_up(self):
        if self.level_xp_target == 0: self.level_xp_target = self._get_xp_target_for_level(self.level)
        if self.experience >= self.level_xp_target:
            if self.level < 100:
                self.send_message(f"**You have enough experience to advance to level {self.level + 1}!**")
                self.send_message("Visit an inn and <span class='keyword' data-command='checkin'>CHECK IN</span> to train and level up.")
            else:
                self.send_message("**You have enough experience for a post-cap training point!**")
                self.send_message("Visit an inn to train.")

    def send_message(self, message: str):
        self.messages.append(message)
        # --- Update History ---
        self.message_history.append(message)
        # Keep last 100 messages
        if len(self.message_history) > 100:
            self.message_history = self.message_history[-100:]
        # ---------------------------

    def get_equipped_item_data(self, slot: str) -> Optional[dict]:
        item_id = self.worn_items.get(slot) 
        if item_id: return self.world.game_items.get(item_id)
        return None

    def get_armor_type(self) -> str:
        DEFAULT_UNARMORED_TYPE = "unarmed" 
        armor_data = self.get_equipped_item_data("torso")
        if armor_data and armor_data.get("type") == "armor":
            return armor_data.get("armor_type", DEFAULT_UNARMORED_TYPE)
        return DEFAULT_UNARMORED_TYPE
    
    def move_to_room(self, target_room_id: str, move_message: str):
        self.world.stop_combat_for_all(self.name.lower(), "any") 
        
        old_room = self.current_room_id
        
        # --- TABLE LOGIC: GATEKEEPER SUCCESSION (LEAVING) ---
        old_room_obj = self.world.get_active_room_safe(old_room)
        if old_room_obj and getattr(old_room_obj, "is_table", False):
            # If I was the owner, we need to pass the key
            if getattr(old_room_obj, "owner", None) == self.name.lower():
                # Get remaining players (excluding self)
                current_occupants = list(self.world.room_players.get(old_room, []))
                # Note: 'current_occupants' might still contain self depending on when this is called
                remaining = [p for p in current_occupants if p.lower() != self.name.lower()]
                
                if remaining:
                    # Pass key to the first person in list (usually longest standing)
                    new_owner = remaining[0]
                    old_room_obj.owner = new_owner.lower()
                    
                    # Notify new owner
                    new_owner_obj = self.world.get_player_obj(new_owner)
                    if new_owner_obj:
                        new_owner_obj.send_message(f"You are now the head of the table.")
                else:
                    # Table is empty
                    old_room_obj.owner = None
                    old_room_obj.invited_guests = []
        # ----------------------------------------------------

        self.current_room_id = target_room_id
        
        self.world.remove_player_from_room_index(self.name.lower(), old_room)
        self.world.add_player_to_room_index(self.name.lower(), target_room_id)
        
        # --- TABLE LOGIC: GATEKEEPER ASSIGNMENT (ENTERING) ---
        target_room_obj = self.world.get_active_room_safe(target_room_id)
        if target_room_obj and getattr(target_room_obj, "is_table", False):
            # Check if anyone is already there (excluding self)
            existing_occupants = [p for p in self.world.room_players.get(target_room_id, []) if p.lower() != self.name.lower()]
            
            if not existing_occupants:
                target_room_obj.owner = self.name.lower()
                target_room_obj.invited_guests = [] # Reset invite list on new claim
                self.send_message("You take a seat at the empty table.")
            else:
                # SELF-HEALING: If there are occupants but NO owner (e.g. reload or glitch), assign one.
                if not getattr(target_room_obj, "owner", None):
                    # Sort occupants to find longest standing? Or just pick first.
                    # Since existing_occupants is from room_players (set/list), order isn't guaranteed perfectly
                    # but picking one is better than none.
                    new_owner = existing_occupants[0]
                    target_room_obj.owner = new_owner.lower()
        # -----------------------------------------------------
        
        if target_room_id not in self.visited_rooms:
            self.visited_rooms.append(target_room_id)
        self.send_message(move_message)
        self.mark_dirty()

    def to_dict(self) -> dict:
        # Base Entity Data + Player Specifics
        data = super().to_dict() if hasattr(super(), 'to_dict') else self.data.copy()
        
        # Override with current state (ENSURE ALL MUTABLE FIELDS ARE HERE)
        data.update({
            "name": self.name,
            "current_room_id": self.current_room_id,
            "hp": self.hp,
            "mana": self.mana,
            "stamina": self.stamina,
            "spirit": self.spirit,
            "stats": self.stats,
            "skills": self.skills,
            "inventory": self.inventory,
            "worn_items": self.worn_items,
            "wealth": self.wealth,
            "flags": self.flags,
            "quest_counters": self.quest_counters,
            "completed_quests": self.completed_quests,
            "factions": self.factions,
            "deities": self.deities, 
            "guilds": self.guilds, 
            "level": self.level,
            "experience": self.experience,
            "unabsorbed_exp": self.unabsorbed_exp,
            "ptps": self.ptps,
            "mtps": self.mtps,
            "stps": self.stps,
            "game_state": self.game_state,
            "chargen_step": self.chargen_step,
            "appearance": self.appearance,
            "skill_learning_progress": self.skill_learning_progress,
            "ranks_trained_this_level": self.ranks_trained_this_level,
            "deaths_recent": self.deaths_recent,
            "death_sting_points": self.death_sting_points,
            "con_lost": self.con_lost,
            "con_recovery_pool": self.con_recovery_pool,
            "wounds": self.wounds,
            # --- NEW: Scars ---
            "scars": self.scars,
            # ------------------
            "next_mana_pulse_time": self.next_mana_pulse_time,
            "mana_pulse_used": self.mana_pulse_used,
            "last_spellup_use_time": self.last_spellup_use_time,
            "spellup_uses_today": self.spellup_uses_today,
            "stamina_burst_pulses": self.stamina_burst_pulses,
            "prepared_spell": self.prepared_spell,
            "buffs": self.buffs,
            "known_spells": self.known_spells,
            "known_maneuvers": self.known_maneuvers,
            "visited_rooms": self.visited_rooms,
            "is_goto_active": self.is_goto_active,
            "group_id": self.group_id,
            "band_id": self.band_id,
            "band_xp_bank": self.band_xp_bank,
            "is_admin": self.is_admin,
            "locker": self.locker,
            "aliases": self.aliases,
            "message_history": self.message_history,
            "friends": self.friends,
            "ignored": self.ignored
        })
        return data

    def get_vitals(self) -> Dict[str, Any]:
        worn_data = {}
        for slot_id, slot_name in config.EQUIPMENT_SLOTS.items():
            item_ref = self.worn_items.get(slot_id)
            if item_ref:
                # FIX: Handle if the worn item is a dict (instantiated) or ID (template)
                if isinstance(item_ref, dict):
                    item_data = item_ref
                else:
                    item_data = self.world.game_items.get(item_ref)
                
                if item_data:
                    worn_data[slot_id] = {
                        "name": item_data.get("name", "an item"),
                        "slot_display": slot_name
                    }

        combat_state = self.world.get_combat_state(self.name.lower())
        real_next_action = 0.0
        real_rt_type = "hard"
        real_duration = 0.0 
        
        if combat_state:
            real_next_action = combat_state.get("next_action_time", 0.0)
            real_rt_type = combat_state.get("rt_type", "hard")
            real_duration = combat_state.get("duration", max(0, real_next_action - time.time()))

        return {
            "health": self.hp, "max_health": self.max_hp,
            "mana": self.mana, "max_mana": self.max_mana,
            "stamina": self.stamina, "max_stamina": self.max_stamina,
            "spirit": self.spirit, "max_spirit": self.max_spirit,
            "current_room_id": self.current_room_id,
            "stance": self.stance,
            "wounds": self.wounds,
            # --- NEW: Send Scars ---
            "scars": self.scars,
            # -----------------------
            "worn_items": worn_data,
            "exp_to_next": self.level_xp_target - self.experience,
            "exp_percent": (self.experience / self.level_xp_target) * 100,
            "posture": self.posture,
            "status_effects": self.status_effects,
            "rt_end_time_ms": real_next_action * 1000,
            "rt_duration_ms": real_duration * 1000, 
            "rt_type": real_rt_type
        }

class Room(GameEntity):
    def __init__(self, room_id: str, name: str, description: str, db_data: Optional[dict] = None):
        super().__init__(uid=room_id, name=name, data=db_data)
        self.room_id = room_id 
        self.is_room = True
        self.is_table = self.data.get("is_table", False)
        # --- TABLE LOGIC ---
        self.owner = None # Runtime tracking of Gatekeeper
        self.invited_guests = []
        # -------------------
        self.data["description"] = description
        self.exits: Dict[str, str] = self.data.get("exits", {})
        self.triggers: Dict[str, str] = self.data.get("triggers", {})
        self.objects: List[Dict[str, Any]] = []
        self.lock = threading.RLock()
        self.ambient_events = self.data.get("ambient_events", [])
        
        raw_objects = self.data.get("objects", [])
        for obj_stub in raw_objects:
            merged_obj = copy.deepcopy(obj_stub) 
            self.objects.append(merged_obj)

    def to_dict(self) -> dict:
        with self.lock:
            data = {
                **self.data,
                "room_id": self.room_id,
                "name": self.name,
                "description": self.description,
                "objects": self.objects,
                "exits": self.exits,
                "triggers": self.triggers,
                "ambient_events": self.ambient_events 
            }
            if self.uid and not self.uid.startswith("room_"):
                 data["_id"] = self.uid 
            return data