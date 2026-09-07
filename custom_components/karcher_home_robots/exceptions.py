"""ClientError hierarchy for the Kärcher Home Robots integration."""

from __future__ import annotations


class ClientError(Exception):
    """Base class for all integration errors."""


class AuthError(ClientError):
    """Login failed or token rejected."""


class InvalidCredentials(AuthError):
    """Wrong password or user not found."""


class TokenRejected(AuthError):
    """Previously valid token is now rejected by the server."""


class TransientError(ClientError):
    """Retryable error; the coordinator will schedule a retry."""


class NetworkError(TransientError):
    """DNS, TCP, TLS, or socket failure."""


class RateLimited(TransientError):
    """HTTP 429 or explicit vendor throttle."""


class BrokerDisconnect(TransientError):
    """MQTT layer surprise disconnect."""


class PermanentError(ClientError):
    """Not retryable without operator action."""


class MalformedDeviceError(PermanentError):
    """A device payload the pinned library could not parse.

    Not the unrecognised-model case: `adapter._LenientProduct._missing_` mints a
    pseudo-member for any product ID the enum lacks, so an unknown robot sets up
    normally. What is left is `Device.__init__`'s other eager coercions — a
    malformed `versions` payload, or a `status` outside `DeviceStatus`'s 0/1 —
    and the library gives no way to tell which field failed. Permanent because
    the account's discovery call fails for every robot until the payload changes.
    """


class ValidationError(ClientError):
    """Inbound payload fails schema validation."""


class ProtocolError(ClientError):
    """Payload is structurally valid but semantically unsupported."""
