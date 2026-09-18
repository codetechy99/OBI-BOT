import json
import os
import datetime

class Ledger:
    def __init__(self, db_path="db.json"):
        self.db_path = db_path
        self._ensure_db_exists()

    def _ensure_db_exists(self):
        if not os.path.exists(self.db_path):
            self._save_db({})

    def _load_db(self):
        if not os.path.exists(self.db_path):
            return {}
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_db(self, data):
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def create_account(self, user_id: str) -> dict:
        data = self._load_db()
        if user_id not in data:
            data[user_id] = {
                "balance": 0.0,
                "reserved": 0.0,
                "history": []
            }
            self._save_db(data)
        else:
            if "reserved" not in data[user_id]:
                data[user_id]["reserved"] = 0.0
                self._save_db(data)
        return data[user_id]

    def get_balance(self, user_id: str) -> float:
        data = self._load_db()
        if user_id not in data:
            return 0.0
        return float(data[user_id].get("balance", 0.0))

    def get_reserved_balance(self, user_id: str) -> float:
        data = self._load_db()
        if user_id not in data:
            return 0.0
        return float(data[user_id].get("reserved", 0.0))

    def get_available_balance(self, user_id: str) -> float:
        data = self._load_db()
        if user_id not in data:
            return 0.0
        balance = float(data[user_id].get("balance", 0.0))
        reserved = float(data[user_id].get("reserved", 0.0))
        return max(0.0, balance - reserved)

    def deposit(self, user_id: str, amount: float, method: str = "MoMo") -> float:
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        data = self._load_db()
        if user_id not in data:
            data[user_id] = {"balance": 0.0, "reserved": 0.0, "history": []}

        data[user_id]["balance"] += float(amount)
        if "reserved" not in data[user_id]:
            data[user_id]["reserved"] = 0.0

        record = {
            "type": "deposit",
            "amount": float(amount),
            "method": method,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "balance_after": data[user_id]["balance"]
        }
        data[user_id]["history"].append(record)
        self._save_db(data)
        return data[user_id]["balance"]

    def withdraw(self, user_id: str, amount: float) -> float:
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        data = self._load_db()
        if user_id not in data:
            raise ValueError("User account does not exist")

        current_balance = float(data[user_id].get("balance", 0.0))
        reserved = float(data[user_id].get("reserved", 0.0))
        available = current_balance - reserved

        if available < amount:
            raise ValueError("Insufficient balance")

        data[user_id]["balance"] = current_balance - float(amount)
        record = {
            "type": "withdraw",
            "amount": float(amount),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "balance_after": data[user_id]["balance"]
        }
        data[user_id]["history"].append(record)
        self._save_db(data)
        return data[user_id]["balance"]

    def reserve(self, user_id: str, amount: float) -> bool:
        if amount <= 0:
            raise ValueError("Reserve amount must be positive")
        data = self._load_db()
        if user_id not in data:
            raise ValueError("User account does not exist")

        current_balance = float(data[user_id].get("balance", 0.0))
        reserved = float(data[user_id].get("reserved", 0.0))
        available = current_balance - reserved

        if available < amount:
            return False

        data[user_id]["reserved"] = reserved + float(amount)
        record = {
            "type": "reserve",
            "amount": float(amount),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "reserved_after": data[user_id]["reserved"]
        }
        data[user_id]["history"].append(record)
        self._save_db(data)
        return True

    def release(self, user_id: str, amount: float) -> bool:
        if amount <= 0:
            raise ValueError("Release amount must be positive")
        data = self._load_db()
        if user_id not in data:
            raise ValueError("User account does not exist")

        reserved = float(data[user_id].get("reserved", 0.0))
        if reserved < amount:
            amount = reserved

        data[user_id]["reserved"] = max(0.0, reserved - float(amount))
        record = {
            "type": "release",
            "amount": float(amount),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "reserved_after": data[user_id]["reserved"]
        }
        data[user_id]["history"].append(record)
        self._save_db(data)
        return True

    def apply_pnl(self, user_id: str, pnl: float) -> float:
        data = self._load_db()
        if user_id not in data:
            raise ValueError("User account does not exist")

        current_balance = float(data[user_id].get("balance", 0.0))
        new_balance = current_balance + float(pnl)
        if new_balance < 0:
            raise ValueError("Insufficient balance for negative PnL")

        data[user_id]["balance"] = new_balance
        record = {
            "type": "pnl",
            "amount": float(pnl),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "balance_after": new_balance
        }
        data[user_id]["history"].append(record)
        self._save_db(data)
        return new_balance

    def get_history(self, user_id: str) -> list:
        data = self._load_db()
        if user_id not in data:
            return []
        return data[user_id].get("history", [])
