import json
from pydantic import BaseModel
from derive_client._clients.models import (
    RPCErrorFormatSchema,
)


class DeriveJSONRPCError(Exception):
    """Raised when a Derive JSON-RPC error payload is returned."""

    def __init__(self, message_id: str | int, rpc_error: RPCErrorFormatSchema):
        super().__init__(f"{rpc_error.code}: {rpc_error.message} (message_id={message_id})")
        self.message_id = message_id
        self.rpc_error = rpc_error

    def __str__(self):
        base = f"Derive RPC {self.rpc_error.code}: {self.rpc_error.message}"
        return f"{base}  [data={self.rpc_error.data!r}]" if self.rpc_error.data is not None else base


def try_cast_response(message, result_schema: type[BaseModel]):
    if "error" in message:
        # http resonse.json() may load data as dict, which doesn't match datamodel-codegen model
        if isinstance(message.get("data"), dict):
            message["data"] = json.dumps(message["data"])
        rpc_error = RPCErrorFormatSchema(**message["error"])
        raise DeriveJSONRPCError(message_id=message["id"], rpc_error=rpc_error)
    if "result" in message:
        return result_schema(**message["result"])
    raise ValueError("RPC envelope missing both 'result' and 'error'")
