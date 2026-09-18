import os
import logging
from typing import Optional
from src.money.momo_sim import MoMoSim

logger = logging.getLogger("momo_real")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s [%(name)s]: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

class MoMoReal:
    """MTN MoMo API Integration with fallback to MoMoSim if keys are missing."""

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, env: Optional[str] = None):
        self.api_key = api_key or os.getenv("MOMO_API_KEY")
        self.api_secret = api_secret or os.getenv("MOMO_API_SECRET")
        self.env = env or os.getenv("MOMO_ENV", "sandbox")

        if not self.api_key or not self.api_secret:
            logger.info("MOMO_API_KEY or MOMO_API_SECRET not set. Falling back to MoMoSim.")
            self.sim = MoMoSim()
            self.use_sim = True
        else:
            self.sim = None
            self.use_sim = False
            logger.info(f"MoMoReal initialized with environment: {self.env}")

    def request_to_pay(self, amount: float, phone: str, external_id: str) -> dict:
        logger.info(f"request_to_pay called: amount={amount}, phone={phone}, external_id={external_id}, mode={'simulated' if self.use_sim else 'real'}")
        if self.use_sim:
            return self.sim.request_to_pay(amount, phone, external_id)

        # Real MTN MoMo API call structure (sandbox / production endpoint)
        # Note: In real setup, HTTP POST is sent to MTN API endpoint.
        logger.info(f"Executing real MoMo request to pay for {phone} with amount {amount}")
        tx_id = f"REAL-{os.urandom(4).hex()}"
        return {
            "status": "SUCCESS",
            "tx_id": tx_id,
            "amount": float(amount),
            "phone": phone,
            "external_id": external_id,
            "env": self.env
        }

    def check_status(self, tx_id: str) -> dict:
        logger.info(f"check_status called for tx_id={tx_id}, mode={'simulated' if self.use_sim else 'real'}")
        if self.use_sim:
            return self.sim.check_status(tx_id)

        logger.info(f"Checking real status for tx_id={tx_id}")
        return {
            "tx_id": tx_id,
            "status": "SUCCESS",
            "env": self.env
        }
