"""Exceptions for AIOSonos."""

from __future__ import annotations

# ruff: noqa: N818


class SonosException(Exception):
    """Generic Sonos exception."""


class TransportError(SonosException):
    """Exception raised to represent transport errors."""

    def __init__(self, message: str, error: Exception | None = None) -> None:
        """Initialize a transport error."""
        super().__init__(message)
        self.error = error


class ConnectionClosed(TransportError):
    """Exception raised when the connection is closed."""


class CannotConnect(TransportError):
    """Exception raised when failed to connect the client."""

    def __init__(self, error: Exception) -> None:
        """Initialize a cannot connect error."""
        super().__init__(f"{error}", error)


class ConnectionFailed(TransportError):
    """Exception raised when an established connection fails."""

    def __init__(self, error: Exception | None = None) -> None:
        """Initialize a connection failed error."""
        if error is None:
            super().__init__("Connection failed.")
            return
        super().__init__(f"{error}", error)


class NotConnected(SonosException):
    """Exception raised when not connected to the socket."""


class InvalidState(SonosException):
    """Exception raised when data gets in invalid state."""


class InvalidMessage(SonosException):
    """Exception raised when an invalid message is received."""


class FailedCommand(SonosException):
    """When a command has failed."""

    def __init__(self, error_code: str, details: str | None = None) -> None:
        """Initialize a failed command error."""
        super().__init__(f"Command failed: {details or error_code}")
        self.error_code = error_code
        self.details = details
