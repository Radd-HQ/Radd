"""Inbound transports (RADD-953/958). A source authenticates a message and hands
raw bytes to `intake`; it decides nothing else."""

from .webhook import verify_signature

__all__ = ["verify_signature"]
