import uuid

class MoMoSim:
    """Simulated MTN MoMo payment provider."""

    def request_to_pay(self, amount: float, phone: str, external_id: str) -> dict:
        tx_id = f"SIM-{uuid.uuid4().hex[:8]}"
        return {
            "status": "SUCCESS",
            "tx_id": tx_id,
            "amount": float(amount),
            "phone": phone,
            "external_id": external_id
        }

    def check_status(self, tx_id: str) -> dict:
        return {
            "tx_id": tx_id,
            "status": "SUCCESS"
        }
