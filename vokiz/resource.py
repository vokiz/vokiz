"""Module to manage Vokiz resources."""

import click
import os.path
import re
import roax.file
import roax.schema as s
import vokiz.config
import vokiz.schema as vs

from dataclasses import dataclass, field


@dataclass
class Backend:
    """A backend to send/receive channel messages."""

    module: s.str() = "none"
    kwargs: s.dict({}, additional=s.str()) = field(default_factory=dict)


@dataclass
class Phone:
    """A phone number associated with a channel."""

    number: vs.e164()
    nick: vs.nick()
    mute: s.bool() = False


@dataclass
class User:
    """A user associated with a channel."""

    nick: vs.nick()
    voice: s.bool() = True
    op: s.bool() = False


@dataclass
class Aliases:
    """Aliases for group distributions."""

    ops: vs.nick() = "ops"
    all: vs.nick() = "all"


@dataclass
class Channel:
    """A channel of communications."""

    id: s.str()
    backend: s.dataclass(Backend) = field(default_factory=Backend)
    head: s.str() = "From {from}: "
    users: s.list(s.dataclass(User)) = field(default_factory=list)
    phones: s.list(s.dataclass(Phone)) = field(default_factory=list)
    aliases: s.dataclass(Aliases) = field(default_factory=Aliases)
    rcpt: vs.nick() = "ops"


_schema = s.dataclass(Channel)


class Channels(roax.file.FileResource):
    """Vokiz channels resource."""

    schema = _schema
    extension = ".json"

    def __init__(self):
        self.dir = vokiz.config.config.channel_dir
        super().__init__()

    def read(self, id):
        """Read a channel resource item."""
        result = super().read(id)
        result.id = id
        return result


resources = roax.resource.Resources({"channels": "vokiz.resource:Channels"})
