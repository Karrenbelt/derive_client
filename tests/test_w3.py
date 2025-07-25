import threading
import time
import warnings
from http import HTTPStatus

import pytest
from requests.exceptions import RequestException
from web3 import Web3
from web3.providers import HTTPProvider

from derive_client.constants import DEFAULT_RPC_ENDPOINTS
from derive_client.data_types import ChainID
from derive_client.utils import get_logger, load_rpc_endpoints, make_rotating_provider_middleware

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
def test_rpc_endpoints_reachability_and_chain_id(chain, rpc_endpoints):

    success = {}
    failed = {}
    rate_limited = set()

    request_kwargs = {"timeout": 1}
    providers = [HTTPProvider(url, request_kwargs) for url in rpc_endpoints]
    for provider in providers:
        w3 = Web3(provider)
        if not w3.is_connected:
            continue
        try:
            success[w3.provider.endpoint_uri] = w3.eth.chain_id
        except RequestException as e:
            status = getattr(e.response, "status_code", None)
            if status == HTTPStatus.TOO_MANY_REQUESTS:
                rate_limited.add(w3.provider.endpoint_uri)
                continue
            failed[w3.provider.endpoint_uri] = e
        except Exception as e:
            failed[w3.provider.endpoint_uri] = e

    not_connected = set(rpc_endpoints) - set(success) - set(failed) - set(rate_limited)
    assert not not_connected, f"Not connected: {not_connected}"

    if failed:
        details = "\n".join(f"  {u} → chain_id {cid}" for u, cid in failed.items())
        pytest.fail(f"[{chain}] endpoints failures:\n{details}")

    expected = ChainID[chain]
    incorrect_chains = {k: v for k, v in success.items() if v != expected}
    assert not incorrect_chains, f"Incorrect chain, expected {expected.name} ({expected}) got: {incorrect_chains}"

    if rate_limited:
        warnings.warn(f"[{chain}] endpoints rate-limited: {rate_limited}", UserWarning)

    max_unresponsive = len(rpc_endpoints) // 3
    if len(rate_limited) > max_unresponsive:
        msg = "\n".join(f"  {url}" for url in rate_limited)
        pytest.fail(f"[{chain}] Too many unresponsive endpoints " f"({len(rate_limited)}/{len(rpc_endpoints)}):\n{msg}")


@pytest.mark.parametrize("chain, rpc_endpoints", RPC_ENDPOINTS)
def test_rotating_middelware(chain, rpc_endpoints):
    # --------------------
    # -- USAGE in v6.11 --
    # --------------------

    # 0) Timeout fast, otherwise any ReadTimeout (default 10s) will cause failure
    request_kwargs = {"timeout": 1}

    # 1) Build your list of HTTPProvider, based on your RPCEndpoints
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

    # 4) Test: rotation through all providers
    expected = {p.endpoint_uri for p in providers}
    timeout = time.monotonic() + len(providers)
    while used != expected and time.monotonic() < timeout:
        try:
            _ = w3.eth.get_block("latest")
        except Exception:
            pass

    unused = expected - used
    assert not unused, f"Unused {chain} endpoints:\n{unused}"
