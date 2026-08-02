"""The upload routing chain (spec 102): ordered rules, first match wins, the
default host catches everything else. Rule types are socket providers
(Socket.STORAGE_ROUTING_RULE) so plugins can contribute new ones."""

from .context import RoutingContext
from .engine import decide

__all__ = ["RoutingContext", "decide"]
