"""Outbound transports (RADD-955/958). `smtp` is the only one so far; a Gmail
adapter registers here and changes nothing above it."""

from .smtp_sender import SmtpSender

__all__ = ["SmtpSender"]
