"""Vokiz channel processing module."""

import collections.abc
import inspect
import readline
import roax.context
import roax.schema as s
import shlex
import vokiz.backends
import vokiz.backends.none
import vokiz.resource
import vokiz.schema as vs
import wrapt

from dataclasses import dataclass, field
from vokiz.backends import BackendError


class Error(Exception):
    """Raised when error should be returned to the sender."""


class Unauthorized(Exception):
    """Raised if user is not authorized to execute a command."""


class Exit(Exception):
    """Raised to exit the REPL."""


class cmd:
    """Decorate method to be exposed as a command."""

    _str = s.str()

    def __init__(self, auth=None, name=None):
        self.auth = auth or (lambda: True)
        self.name = name

    def __call__(self, function):
        function._command = self

        def wrapper(wrapped, instance, args, kwargs):
            if not self.auth():
                raise Unauthorized
            args = list(args)  # mutable
            _args = []
            _kwargs = {}
            for name, param in inspect.signature(wrapped).parameters.items():
                if not args:
                    break  # missing argument(s) will be caught in call to method
                elif param.kind == param.POSITIONAL_OR_KEYWORD:
                    arg = args.pop(0)
                    try:
                        _args.append(
                            wrapped.__annotations__.get(name, cmd._str).str_decode(arg)
                        )
                    except s.SchemaError:
                        raise Error(f"Invalid {name}: {arg}.")
                elif param.kind == param.VAR_KEYWORD:
                    for arg in args:
                        try:
                            key, value = arg.split("=", 1)
                        except ValueError:
                            raise Error(f"Invalid key-value: {arg}")
                        _kwargs[key] = value
                    args.clear()
                else:
                    raise TypeError("unsupported command parameter type")
            if args:
                raise TypeError(f"{wrapped.__name__}: too many arguments")
            return wrapped(*_args, **_kwargs)

        return wrapt.decorator(wrapper)(function)


def ctx(type):
    """Return a context object of the specified type."""
    c = roax.context.last(context=type)
    if c:
        return c.get(type)


def _str_list(l):
    """Return a string representing list of strings."""
    return " ".join(sorted(l, key=str.lower)) if l else "[none]"


def _str_dict(d):
    """Return a string representing dict of strings to strings."""
    return " ".join([f"{k}={v}" for k, v in d.items()]) if d else "[none]"


def _str_dataclass(o):
    """Return a string representing attributes in a dataclass."""
    return _str_dict({attr: getattr(o, attr) for attr in o.__annotations__})


class auth:
    """Command authorization functions."""

    @staticmethod
    def shell():
        """Authorize command if requested through the shell."""
        return roax.context.last(context="shell") is not None

    @staticmethod
    def op():
        """Return if requesting user is channel operator."""
        user = ctx("user")
        return user.op if user else False

    @staticmethod
    def phone():
        """Authorize command if request by phone."""
        return ctx("phone") is not None


class DataclassMapping(collections.abc.Mapping):
    """TODO: Description."""

    def __init__(self, sequence, key, insensitive=False):
        self.sequence = sequence
        self.key = key
        self.insensitive = insensitive

    def __getitem__(self, key):
        if self.insensitive:
            key = key.lower()
        for item in self.sequence:
            item_key = getattr(item, self.key)
            if self.insensitive:
                item_key = item_key.lower()
            if item_key == key:
                return item
        raise KeyError(key)

    def __iter__(self):
        for key in [getattr(item, self.key) for item in self.sequence]:
            yield key

    def __len__(self):
        return len(self.sequence)

    def __delitem__(self, key):
        self.sequence.remove(self[key])

    def add(self, item):
        """TODO: Description."""
        item_key = getattr(item, self.key)
        if item_key in self:
            raise ValueError(f"duplicate key: {item_key}")
        self.sequence.append(item)


class Processor:
    """TODO: Description."""

    def __init__(self, channel):
        self.channel = channel
        self.commands = self._commands()
        self.users = DataclassMapping(self.channel.users, "nick", insensitive=True)
        self.phones = DataclassMapping(self.channel.phones, "number")
        try:
            self.backend = vokiz.backends.load(channel.backend)
        except BackendError as be:
            print(f"Backend error: {be}.")
            self.backend = vokiz.backends.none.SMS()  # use dummy backend

    def _commands(self):
        """Return name-to-method mapping of commands."""
        inspect.getmembers(self)
        result = {}
        for member in inspect.getmembers(self, inspect.ismethod):
            name, method = member[0], member[1]
            cmd = getattr(method.__func__, "_command", None)
            if cmd:
                name = cmd.name or name
                result[name] = method
        return result

    def eval(self, line):
        if not line:
            return
        try:
            if line.startswith("/"):
                line = line[1:]
                args = shlex.split(line)
                if not args:
                    raise Error(f"Missing command.")
                try:
                    command = args.pop(0)
                    method = self.commands.get(command)
                    if not method:
                        raise Unauthorized
                    return method(*args)
                except Unauthorized:
                    return f"Unknown commnd: {command}."
                except TypeError:
                    return self.usage(method)
            if not line.startswith("@"):
                if auth.shell():
                    raise Error(
                        f"Cowardly refusing to send message without explicit @nick."
                    )
                line = f"@{self.channel.rcpt} {line}"
            nick, message = f"{line} ".split(" ", 1)
            self.send(nick[1:], message)
        except Error as e:
            return f"Error: {e}"

    def send(self, nick, message):
        try:
            nick = self.users[nick].nick
        except KeyError:
            for alias in [
                getattr(self.channel.aliases, attr)
                for attr in self.channel.aliases.__annotations__
            ]:
                if alias.lower() == nick.lower():
                    nick = alias
                    break
        message = message.strip()
        if not message:
            raise Error(f"Refusing to send empty message to {nick}.")
        header = self.channel.head.format_map({"from": ctx("user").nick, "to": nick})
        phones = self._resolve(nick)
        if not phones:
            raise Error(f"No such nick: {nick}.")
        for phone in phones:
            self._send(phone, f"{header}{message}")

    def _resolve(self, nick):
        """Return list of phones associated with a nick, including aliases."""
        return [
            phone
            for phone in self.phones.values()
            if nick == self.channel.aliases.all
            or phone.nick == nick
            or (nick == self.channel.aliases.ops and self.users[phone.nick].op)
        ]

    def _send(self, phone, message):
        """Send a message to a phone."""
        if phone.mute:
            return
        print(f"[S] {phone.number}: {message}")
        try:
            self.backend.send(phone.number, message)
        except BackendError as error:
            print(f"[E] Error sending to {phone.number}: {error}.")  # FIXME: log

    def shell(self, nick):
        prompt = f"{nick}@{self.channel.id}: "
        user = vokiz.resource.User(nick, True, True)
        with roax.context.push(context="shell"):
            with roax.context.push(context="user", user=user):
                while True:
                    try:
                        result = self.eval(input(prompt))
                        if result:
                            print(result)
                    except (EOFError, KeyboardInterrupt):
                        print()
                        break
                    except Exit:
                        break

    def usage(self, method):
        """Return usage for method."""
        sig = inspect.signature(method)
        elements = [f"/{method.__name__}"]
        for name, param in sig.parameters.items():
            if param.default != param.empty:
                name = f"[{name}]"
            elif param.kind == param.VAR_KEYWORD:
                name = "[key=value]..."
            elements.append(name)
        return f"Usage: {' '.join(elements)}."

    def notify(self, event):
        message = f"{ctx('user').nick} {event}."
        phones = self._resolve(self.channel.aliases.ops)
        for phone in phones:
            self._send(phone, message)
        else:
            print(f"[I] {message}")

    def process(self):
        """Process incoming messages."""
        with roax.context.push(context="process"):
            for number, message in self.backend.receive():
                print(f"[R] {number}: {message}")
                phone = self.phones.get(number)
                if not phone:  # ignore messages from unregistered numbers
                    continue
                try:
                    user = self.users[phone.nick]
                except KeyError:
                    continue
                with roax.context.push(context="phone", phone=phone):
                    with roax.context.push(context="user", user=user):
                        response = self.eval(message)
                        if response:
                            self._send(phone, response)

    # ---- user commands -----

    @cmd(auth.phone)
    def mute(self):
        """Disable receiving messages."""
        phone = ctx("phone")
        if phone.mute:
            raise Error(f"Channel is already muted. Use /unmute to unmute.")
        phone.mute = True
        self.notify(f"muted channel on {phone.number}")
        return f"Channel muted on {phone.number}. Use /unmute to unmute."

    @cmd(auth.phone)
    def unmute(self):
        """Enable receiving messages."""
        phone = ctx("phone")
        if not phone.mute:
            raise Error(f"Channel is not muted.")
        phone.mute = False
        self.notify(f"unmuted channel on {phone.number}")
        return f"Channel unmuted on {phone.number}."

    @cmd()
    def who(self, nick=None):
        """List users or get user information."""
        if not nick or not auth.op():
            return f"Users: {_str_list(self.users)}."
        try:
            user = self.users[nick]
        except KeyError:
            raise Error(f"No such user: {nick}.")
        result = [f"User: {user.nick}{' [op]' if user.op else ''}"]
        if auth.op():
            result.append(
                _str_list(
                    [p.number for p in self.phones.values() if p.nick == user.nick]
                )
            )
        return " ".join(result) + "."

    @cmd()
    def ping(self):
        """Ping the service to confirm access."""
        phone = ctx("phone")
        source = phone.number if phone else "REPL"
        return f"Ping received from {ctx('user').nick} via {source}."

    @cmd()
    def help(self, command=None):
        """List commands or display help for command."""
        valid = []
        for name, method in self.commands.items():
            if method.__func__._command.auth():
                valid.append(name)
        if not command:
            return f"Commands: {_str_list(valid)}."
        elif command in valid:
            method = self.commands[command]
            return f"{self.usage(method)} {method.__doc__}"
        else:
            return f"Unknown command: {command}."

    # ----- operator commands -----

    @cmd(auth.op)
    def add(self, number: vs.e164(), nick: vs.nick()):
        """Add member to channel."""
        if number in self.phones:
            raise Error(
                f"{number} is already registered to {self.phones[number].nick}."
            )
        if nick.lower() in (
            self.channel.aliases.all.lower(),
            self.channel.aliases.ops.lower(),
        ):
            raise Error(f"Nick unavailable: {nick}.")
        try:
            user = self.users[nick]
        except KeyError:
            user = vokiz.resource.User(nick)
            self.users.add(user)
        self.phones.add(vokiz.resource.Phone(number, user.nick))
        self.notify(f"added {number} as {user.nick}")

    @cmd(auth.op)
    def remove(self, number: vs.e164()):
        """Remove member from channel."""
        try:
            phone = self.phones[number]
        except KeyError:
            raise Error(f"Number not in channel: {number}.")
        del self.phones[number]
        user = self.users.get(phone.nick)
        if user and not [p for p in self.phones.values() if p.nick == phone.nick]:
            del self.users[user.nick]  # delete orphan user
        nick_msg = f" ({user.nick})" if user else ""
        self.notify(f"removed {number}{nick_msg} from channel")

    @cmd(auth.op)
    def op(self, nick: vs.nick() = None):
        """List operators or promote user to channel operator."""
        if nick is None:
            result = []
            for nick in self.users:
                if self.users[nick].op:
                    result.append(nick)
            return f"Operators: {_str_list(result)}."
        try:
            user = self.users[nick]
        except KeyError:
            raise Error(f"No such user: {nick}.")
        if user.op:
            raise Error(f"User {user.nick} is already channel operator.")
        user.op = True
        self.notify(f"promoted {user.nick} to channel operator")

    @cmd(auth.op)
    def deop(self, nick: vs.nick()):
        """Demote channel operator to user."""
        try:
            user = self.users[nick]
        except KeyError:
            raise Error(f"No such user: {nick}.")
        if not user.op:
            raise Error(f"User {user.nick} is not channel operator.")
        self.notify(f"demoted {user.nick} to channel user")
        user.op = False

    @cmd(auth.op)
    def alias(self, **kwargs):
        """Get or set alias."""
        if not kwargs:
            return f"Aliases: {_str_dataclass(self.channel.aliases)}."
        for key, value in kwargs.items():
            if key.lower() not in self.channel.aliases.__annotations__:
                raise Error(f"Unsupported alias: {key}.")
            setattr(self.channel.aliases, key, value)
        self.notify(f"set aliase: {_str_dict(kwargs)}")

    @cmd(auth.op)
    def head(self, value=None):
        """Get or set message header."""
        if not value:
            return f'Header: "{self.channel.head}".'
        try:
            value.format_map({"from": "f", "to": "t"})
        except KeyError:
            raise Error("Only {from} and {to} fields can be expressed in header.")
        self.channel.head = value
        self.notify(f'set message header to: "{value}"')

    @cmd(auth.op)
    def rcpt(self, nick: vs.nick() = None):
        """Get or set recipient of unaddressed messages."""
        return f"Unaddressed messages go to: QST."

    # ----- REPL commands -----

    @cmd(auth.shell)
    def exit(self):
        """Exit the channel."""
        raise Exit

    @cmd(auth.shell)
    def backend(self, module=None, **kwargs):
        """Get or set backend config."""
        if not module:
            data = self.channel.backend
            kwargs = _str_dict(data.kwargs)
            return f"Backend: {data.module}{' ' if kwargs else ''}{kwargs}."
        else:
            data = vokiz.resource.Backend(module, kwargs)
            try:
                self.backend = vokiz.backends.load(data)
            except BackendError as be:
                raise Error(f"{be}.")
            self.channel.backend = data
            return "Backend successfully set."
