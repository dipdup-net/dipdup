"""
Compatibility aliases for the `pysignalr` package.
"""

from pysignalr.messages import JSONMessage as WebsocketMessage
from pysignalr.messages import Message as Message
from pysignalr.protocol.json import BaseJSONProtocol as WebsocketProtocol
from pysignalr.transport.websocket import BaseWebsocketTransport as WebsocketTransport

__all__ = ['Message', 'WebsocketMessage', 'WebsocketProtocol', 'WebsocketTransport']
