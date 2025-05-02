"""Models used in the bridge module."""


from dataclasses import dataclass

from derive_action_signing.module_data import ModuleData
from derive_action_signing.utils import decimal_to_big_int
from eth_abi.abi import encode
from pydantic import BaseModel, ConfigDict
from web3 import Web3
from web3.datastructures import AttributeDict

from .enums import ChainID, Currency

Address = str


@dataclass
class CreateSubAccountDetails:
    amount: int
    base_asset_address: str
    sub_asset_address: str

    def to_eth_tx_params(self):
        return (
            decimal_to_big_int(self.amount),
            Web3.to_checksum_address(self.base_asset_address),
            Web3.to_checksum_address(self.sub_asset_address),
        )


@dataclass
class CreateSubAccountData(ModuleData):
    amount: int
    asset_name: str
    margin_type: str
    create_account_details: CreateSubAccountDetails

    def to_abi_encoded(self):
        return encode(
            ['uint256', 'address', 'address'],
            self.create_account_details.to_eth_tx_params(),
        )

    def to_json(self):
        return {}


class TokenData(BaseModel):
    isAppChain: bool
    connectors: dict[ChainID, dict[str, str]]
    LyraTSAShareHandlerDepositHook: Address | None = None
    LyraTSADepositHook: Address | None = None
    isNewBridge: bool


class MintableTokenData(TokenData):
    Controller: Address
    MintableToken: Address


class NonMintableTokenData(TokenData):
    Vault: Address
    NonMintableToken: Address


class DeriveAddresses(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    chains: dict[ChainID, dict[Currency, MintableTokenData | NonMintableTokenData]]


class TxResult(BaseModel):
    tx_hash: str
    receipt: AttributeDict | None
    exception: Exception | None

    @property
    def is_pending(self) -> bool:
        return self.receipt is None and self.exception is None

    @property
    def is_timed_out(self) -> bool:
        return isinstance(self.exception, TimeoutError)

    @property
    def is_failed(self) -> bool:
        return self.exception is not None and not self.is_timed_out()
