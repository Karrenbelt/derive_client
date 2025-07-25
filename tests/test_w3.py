import threading
import time

import pytest
from web3 import Web3
from web3.providers import HTTPProvider

from derive_client.constants import DEFAULT_RPC_ENDPOINTS
from derive_client.utils import load_rpc_endpoints, make_rotating_provider_middleware, get_logger

RPC_ENDPOINTS = list(load_rpc_endpoints(DEFAULT_RPC_ENDPOINTS).model_dump().items())


class TrackingHTTPProvider(HTTPProvider):

    def __init__(self, endpoint_uri: str, request_kwargs: dict, used: set):
        super().__init__(endpoint_uri, request_kwargs=request_kwargs)
        self.used = used
        self.lock = threading.Lock()

    def make_request(self, method, params):
        with self.lock:
            self.used.add(self.endpoint_uri)
        return super().make_request(method, params)


@pytest.mark.flaky(reruns=3, reruns_delay=1)
@pytest.mark.parametrize("chain, rpc_endpoints", RPC_ENDPOINTS)
def test_rotating_middelware(chain, rpc_endpoints):
    # --------------------
    # -- USAGE in v6.11 --
    # --------------------

    # 0) Timeout fast, otherwise any ReadTimeout (default 10s) will cause failure
    request_kwargs = {"timeout": 1}

    # 1) Build your list of HTTPProvider, based on your RPCEndpoints:
    used = set()
    providers = [TrackingHTTPProvider(url, request_kwargs, used) for url in rpc_endpoints]

    # 2) Create Web3 (initial provider is a no-op once middleware is in place)
    w3 = Web3()

    # 3) Register the rotating-backoff middleware
    rotator = make_rotating_provider_middleware(
        providers,
        initial_backoff=2.0,
        max_backoff=30.0,
        logger=get_logger(),
    )
    w3.middleware_onion.add(rotator)

    # 4) Test: fail if less than 2/3rd of endpoints were used
    expected = {p.endpoint_uri for p in providers}
    max_fail = max(1, len(providers) // 3)
    timeout = time.monotonic() + len(providers)
    while used != expected and time.monotonic() < timeout:
        try:
            _ = w3.eth.get_block("latest")
        except Exception:
            pass

    unused = expected - used
    assert len(unused) <= max_fail, f"Unused {chain} endpoints:\n{unused}"
