"""Enums used in the derive_client module."""

import sys
from enum import Enum, IntEnum, auto

if sys.version_info < (3, 11):

    class StrEnum(str, Enum):
        @staticmethod
        def _generate_next_value_(name, start, count, last_values):
            return name.lower()

        def __str__(self):
            return self.value

else:
    from enum import StrEnum


class TxStatus(IntEnum):
    FAILED = 0
    SUCCESS = 1


class ChainID(IntEnum):
    ETH = 1
    OPTIMISM = 10
    LYRA = 957
    BASE = 8453
    MODE = 34443
    ARBITRUM = 42161
    BLAST = 81457

    @classmethod
    def _missing_(cls, value):
        try:
            int_value = int(value)
            return next(member for member in cls if member == int_value)
        except (ValueError, TypeError, StopIteration):
            return super()._missing_(value)


class Currency(StrEnum):
    @staticmethod
    def _generate_next_value_(name: str, start: int, count: int, last_values: list[str]):
        return name

    weETH = auto()
    rswETH = auto()
    rsETH = auto()
    USDe = auto()
    deUSD = auto()
    PYUSD = auto()
    sUSDe = auto()
    SolvBTC = auto()
    SolvBTCBBN = auto()
    LBTC = auto()
    OP = auto()
    DAI = auto()
    sDAI = auto()
    cbBTC = auto()
    eBTC = auto()


class RPCEndPoints(StrEnum):
    ETH = "https://eth.drpc.org"
    OPTIMISM = "https://optimism.drpc.org"
    BASE = "https://base.drpc.org"
    MODE = "https://mode.drpc.org"
    ARBITRUM = "https://arbitrum.drpc.org"
    BLAST = "https://blast.drpc.org"
    LYRA = "https://rpc.lyra.finance"


class InstrumentType(Enum):
    """Instrument types."""

    ERC20 = "erc20"
    OPTION = "option"
    PERP = "perp"


class UnderlyingCurrency(Enum):
    """Underlying currencies."""

    ETH = "eth"
    BTC = "btc"
    USDC = "usdc"
    LBTC = "lbtc"
    WEETH = "weeth"
    OP = "op"
    DRV = "drv"
    rswETH = "rseeth"
    rsETH = "rseth"
    DAI = "dai"
    USDT = "usdt"


class OrderSide(Enum):
    """Order sides."""

    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order types."""

    LIMIT = "limit"
    MARKET = "market"


class OrderStatus(Enum):
    """Order statuses."""

    OPEN = "open"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class TimeInForce(Enum):
    """Time in force."""

    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"
    POST_ONLY = "post_only"


class Environment(Enum):
    """Environment."""

    PROD = "prod"
    TEST = "test"


class SubaccountType(Enum):
    """
    Type of sub account
    """

    STANDARD = "standard"
    PORTFOLIO = "portfolio"


class CollateralAsset(Enum):
    """Asset types."""

    USDC = "usdc"
    WEETH = "weeth"
    LBTC = "lbtc"


class ActionType(Enum):
    """Action types."""

    DEPOSIT = "deposit"
    TRANSFER = "transfer"


class RfqStatus(Enum):
    """RFQ statuses."""

    OPEN = "open"
