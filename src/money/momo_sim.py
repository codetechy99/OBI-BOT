import asyncio
import uuid
from typing import Dict, Any

class MoMoSim:
    def __init__(self, ledger):
        self.ledger = ledger
        self.transactions: Dict[str, Dict[str, Any]] = {}

    async def request_deposit(self, user_id: str, amount: float, phone: str) -> dict:
        transaction_id = f"momo_{uuid.uuid4().hex[:8]}"
        tx_info = {
            "transaction_id": transaction_id,
            "user_id": user_id,
            "amount": amount,
            "phone": phone,
            "status": "pending"
        }
        self.transactions[transaction_id] = tx_info

        # Schedule background confirmation after 2 seconds
        asyncio.create_task(self._process_deposit(transaction_id, user_id, amount))

        return tx_info

    async def _process_deposit(self, transaction_id: str, user_id: str, amount: float):
        await asyncio.sleep(2)
        if transaction_id in self.transactions:
            self.ledger.deposit(user_id=user_id, amount=amount, method="MoMo")
            self.transactions[transaction_id]["status"] = "confirmed"
