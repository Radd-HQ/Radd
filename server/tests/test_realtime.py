"""Realtime delivery predicate (specs 27/86).

Pure tests of `should_deliver` — the one rule that decides who sees which push.
Spec 86 stage 1: authenticated connections receive every entity frame (frames
are payload-free pings; the refetched endpoints are RBAC'd); notification
frames stay private to their recipient. The socket lifecycle itself is
exercised by connecting a browser (or wscat) to a running server.
"""

import uuid

from radd.modules.realtime.hub import ClientInfo, should_deliver

USER = uuid.uuid4()
OTHER = uuid.uuid4()


class StubEvent:
    """Duck-types events.models.Event for the predicate."""

    def __init__(self, entity_type: str, payload=None):
        self.entity_type = entity_type
        self.payload = payload or {}


def test_entity_frames_reach_every_authenticated_connection():
    # Every entity frame reaches every authenticated connection (spec 86).
    assert should_deliver(ClientInfo(user_id=USER), StubEvent("item")) is True
    assert should_deliver(ClientInfo(user_id=USER), StubEvent("user")) is True


def test_notifications_are_private_to_their_recipient():
    event = StubEvent("notification", {"user_id": str(USER)})
    assert should_deliver(ClientInfo(user_id=USER), event) is True
    # A different authenticated user never gets someone else's notification signal.
    assert should_deliver(ClientInfo(user_id=OTHER), event) is False
