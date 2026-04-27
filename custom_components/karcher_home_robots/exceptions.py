"""ClientError hierarchy for the Kärcher Home Robots integration.

All errors raised by the adapter and coordinator are subclasses of
ClientError. See adr/0003-error-taxonomy.md for the full taxonomy and
the coordinator's translation table.
"""

from __future__ import annotations


class ClientError(Exception):
    """Base class for all integration errors."""


class AuthError(ClientError):
    """Login failed or token rejected."""


class InvalidCredentials(AuthError):
    """Wrong password or user not found."""


class TokenRejected(AuthError):
    """Previously valid token is now rejected by the server."""


class AccessDenied(AuthError):
    """API declined the request for reasons other than credentials."""


class TransientError(ClientError):
    """Retryable error; the coordinator will schedule a retry."""


class NetworkError(TransientError):
    """DNS, TCP, TLS, or socket failure."""


class TimeoutError(TransientError):
    """Request, publish, or reply timed out."""


class RateLimited(TransientError):
    """HTTP 429 or explicit vendor throttle."""


class BrokerDisconnect(TransientError):
    """MQTT layer surprise disconnect."""


class PermanentError(ClientError):
    """Not retryable without operator action."""


class DeviceNotFound(PermanentError):
    """device_id is absent from the authenticated account."""


class InvalidRegion(PermanentError):
    """Region or tenant mismatch."""


class ValidationError(ClientError):
    """Inbound payload fails schema validation."""


class ProtocolError(ClientError):
    """Payload is structurally valid but semantically unsupported."""
