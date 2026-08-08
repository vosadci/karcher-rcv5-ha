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


class UnsupportedDeviceError(PermanentError):
    """Cloud account reports a robot model the pinned library does not recognise."""


class ValidationError(ClientError):
    """Inbound payload fails schema validation."""


class ProtocolError(ClientError):
    """Payload is structurally valid but semantically unsupported."""
