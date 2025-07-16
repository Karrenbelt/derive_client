"""Custom Exception classes."""


class ApiException(Exception):
    """Raised when an API request fails or returns an error response."""


class TxSubmissionError(Exception):
    """Raised when a transaction could not be signed or submitted."""


class BridgeEventParseError(Exception):
    """Raised when an expected cross-chain bridge event could not be parsed."""


class AlreadyFinalizedError(Exception):
    """Raised when attempting to poll a BridgeTxResult who'se status is not TxStatus.PENDING."""
