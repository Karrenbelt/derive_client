"""
Class to handle base websocket client
"""

import json

from derive_action_signing.utils import utc_now_ms

from .base_client import BaseClient
from derive_client.exceptions import DeriveJSONRPCException


class WsClient(BaseClient):
    """Websocket client class."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ws = self.connect_ws()
        self.login_client()

    def submit_order(self, order):
        id = str(utc_now_ms())
        self.ws.send(json.dumps({"method": "private/order", "params": order, "id": id}))
        while True:
            message = json.loads(self.ws.recv())
            if message["id"] == id:
                try:
                    if "result" not in message:
                        if self._check_output_for_rate_limit(message):
                            return self.submit_order(order)
                        raise DeriveJSONRPCException(**message["error"])
                    return message["result"]["order"]
                except KeyError as error:
                    raise Exception(f"Unable to submit order {message}") from error

    def cancel(self, order_id, instrument_name):
        """
        Cancel an order
        """

        id = str(utc_now_ms())
        payload = {
            "order_id": order_id,
            "subaccount_id": self.subaccount_id,
            "instrument_name": instrument_name,
        }
        self.ws.send(json.dumps({"method": "private/cancel", "params": payload, "id": id}))
        while True:
            message = json.loads(self.ws.recv())
            if message["id"] == id:
                return message["result"]

    def cancel_all(self):
        """
        Cancel all orders
        """
        id = str(utc_now_ms())
        payload = {"subaccount_id": self.subaccount_id}
        self.login_client()
        self.ws.send(json.dumps({"method": "private/cancel_all", "params": payload, "id": id}))
        while True:
            message = json.loads(self.ws.recv())
            if message["id"] == id:
                if "result" not in message:
                    if self._check_output_for_rate_limit(message):
                        return self.cancel_all()
                    raise DeriveJSONRPCException(**message["error"])
                return message["result"]
