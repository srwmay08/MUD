# mud_backend/verbs/banking.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core import game_state
import math

def _find_teller(room_objects: list) -> bool:
    """Checks if a teller is present in the room."""
    for obj in room_objects:
        if "teller" in obj.get("keywords", []):
            return True
    return False

@VerbRegistry.register(["deposit"]) # <--- Added
class Deposit(BaseVerb):
    """
    Handles the 'deposit' command.
    DEPOSIT <amount>
    DEPOSIT ALL
    """
    def execute(self):
        if not _find_teller(self.room.objects):
            self.player.send_message("You can only do that at a bank.")
            return
            
        if not self.args:
            self.player.send_message("How much silver do you want to deposit? (e.g., DEPOSIT 100 or DEPOSIT ALL)")
            return

        current_silver = self.player.wealth.get("silvers", 0)
        amount_str = self.args[0].lower()

        if current_silver == 0:
            self.player.send_message("You have no silver to deposit.")
            return

        amount = 0
        if amount_str == "all":
            amount = current_silver
        else:
            try:
                amount = int(amount_str)
                if amount <= 0:
                    self.player.send_message("You must deposit a positive amount.")
                    return
                if amount > current_silver:
                    self.player.send_message(f"You only have {current_silver} silver on you.")
                    return
            except ValueError:
                self.player.send_message("That is not a valid amount.")
                return
        
        # Perform transaction
        self.player.wealth["silvers"] = self.player.wealth.get("silvers", 0) - amount
        self.player.wealth["bank_silvers"] = self.player.wealth.get("bank_silvers", 0) + amount
        
        self.player.send_message(f"You deposit {amount} silver into your account.")
        self.player.send_message(f"Your new balance is {self.player.wealth['bank_silvers']} silver.")

@VerbRegistry.register(["withdraw"]) # <--- Added
class Withdraw(BaseVerb):
    """
    Handles the 'withdraw' command.
    WITHDRAW <amount>
    """
    def execute(self):
        if not _find_teller(self.room.objects):
            self.player.send_message("You can only do that at a bank.")
            return
            
        if not self.args:
            self.player.send_message("How much silver do you want to withdraw? (e.g., WITHDRAW 100)")
            return

        bank_balance = self.player.wealth.get("bank_silvers", 0)
        amount_str = self.args[0].lower()

        if bank_balance == 0:
            self.player.send_message("You have no silver in your account.")
            return

        amount = 0
        try:
            amount = int(amount_str)
            if amount <= 0:
                self.player.send_message("You must withdraw a positive amount.")
                return
            if amount > bank_balance:
                self.player.send_message(f"You only have {bank_balance} silver in your account.")
                return
        except ValueError:
            self.player.send_message("That is not a valid amount.")
            return
        
        # Perform transaction
        self.player.wealth["bank_silvers"] = self.player.wealth.get("bank_silvers", 0) - amount
        self.player.wealth["silvers"] = self.player.wealth.get("silvers", 0) + amount
        
        self.player.send_message(f"You withdraw {amount} silver from your account.")
        self.player.send_message(f"You now have {self.player.wealth['silvers']} silver on hand.")

@VerbRegistry.register(["balance"])
class Balance(BaseVerb):
    """
    Handles the 'balance' command.
    """
    def execute(self):
        if not _find_teller(self.room.objects):
            self.player.send_message("You can only do that at a bank.")
            return
            
        bank_balance = self.player.wealth.get("bank_silvers", 0)
        self.player.send_message(f"You check your account balance.")
        self.player.send_message(f"Your account holds {bank_balance} silver.")