"""
Class to handle base websocket client
"""

import json
import time

from derive_action_signing.utils import sign_ws_login, utc_now_ms
from websocket import WebSocketConnectionClosedException

from derive_client.data_types import InstrumentType, UnderlyingCurrency
from derive_client.exceptions import DeriveJSONRPCException

from .base_client import BaseClient


class WsClient(BaseClient):
    """Websocket client class."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ws = self.connect_ws()
        self.login_client()

    def login_client(
        self,
        retries=3,
    ):
        login_request = {
            "method": "public/login",
            "params": sign_ws_login(
                web3_client=self.web3_client,
                smart_contract_wallet=self.wallet,
                session_key_or_wallet_private_key=self.signer._private_key,
            ),
            "id": str(utc_now_ms()),
        }
        try:
            self.ws.send(json.dumps(login_request))
            # we need to wait for the response
            while True:
                message = json.loads(self.ws.recv())
                if message["id"] == login_request["id"]:
                    if "result" not in message:
                        if self._check_output_for_rate_limit(message):
                            return self.login_client()
                        raise DeriveJSONRPCException(**message["error"])
                    break
        except (WebSocketConnectionClosedException, Exception) as error:
            if retries:
                time.sleep(1)
                self.login_client(retries=retries - 1)
            raise error

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

    def fetch_tickers(
        self,
        instrument_type: InstrumentType = InstrumentType.OPTION,
        currency: UnderlyingCurrency = UnderlyingCurrency.BTC,
    ):
        """
        Fetch tickers using the ws connection
        """
        instruments = self.fetch_instruments(instrument_type=instrument_type, currency=currency)
        instrument_names = [i["instrument_name"] for i in instruments]
        id_base = str(utc_now_ms())
        ids_to_instrument_names = {
            f"{id_base}_{enumerate}": instrument_name for enumerate, instrument_name in enumerate(instrument_names)
        }
        for id, instrument_name in ids_to_instrument_names.items():
            payload = {"instrument_name": instrument_name}
            self.ws.send(json.dumps({"method": "public/get_ticker", "params": payload, "id": id}))
            time.sleep(0.05)  # otherwise we get rate limited...
        results = {}
        while ids_to_instrument_names:
            message = json.loads(self.ws.recv())
            if message["id"] in ids_to_instrument_names:
                if "result" not in message:
                    if self._check_output_for_rate_limit(message):
                        return self.fetch_tickers(instrument_type=instrument_type, currency=currency)
                    raise DeriveJSONRPCException(**message["error"])
                results[message["result"]["instrument_name"]] = message["result"]
                del ids_to_instrument_names[message["id"]]
        return results
