"""Vokiz channel processing module."""

import collections.abc
import inspect
import readline
import roax.context
import roax.schema as s
import shlex
import vokiz.resource
import vokiz.schema as vs
import wrapt

from dataclasses import dataclass, field


class Error(Exception):
    """Raised when error should be returned to the sender."""


class Unauthorized(Exception):
    """Raised if user is not authorized to execute a command."""


class Exit(Exception):
    """Raised to exit the REPL."""


class cmd:
    """Decorate method to be exposed as a command."""

    _str = s.str()

    def __init__(self, auth=None):
        self.auth = auth or (lambda: True)

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
                    try:
                        key, value = arg.split("=", 1)
                    except ValueError:
                        raise Error(f"Invalid key-value: {arg}")
                    _kwargs[key] = value
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


def listing(strings):
    """Return a string listing of strings for display in command output."""
    return " ".join(sorted(strings, key=str.lower)) if strings else "[none]"


class auth:
    """Command authorization functions."""

    @staticmethod
    def repl():
        """Authorize command if requested through REPL."""
        return roax.context.last(context="repl") is not None

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
    def __init__(self, channel):
        self.channel = channel
        self.commands = self._commands()
        self.users = DataclassMapping(self.channel.users, "nick", insensitive=True)
        self.phones = DataclassMapping(self.channel.phones, "number")
        self.backend = None  # FIXME

    def _commands(self):
        """Return name-to-method mapping of commands."""
        inspect.getmembers(self)
        result = {}
        for member in inspect.getmembers(self, inspect.ismethod):
            name, method = member[0], member[1]
            cmd = getattr(method.__func__, "_command", None)
            if cmd:
                result[name] = method
        return result

    def process(self, line):
        if not line:
            return
        elif line.startswith("/"):
            line = line[1:]
            args = shlex.split(line)
            if args:
                command = args.pop(0)
                return self.execute(command, *args)
        elif not line.startswith("@"):
            pass
        else:
            pass

    def repl(self, nick):
        prompt = f"{nick}@{self.channel.id}: "
        user = vokiz.resource.User(nick, True, True)
        with roax.context.push(context="repl"):
            with roax.context.push(context="user", user=user):
                while True:
                    try:
                        result = self.process(input(prompt))
                        if result:
                            print(result)
                    except (EOFError, KeyboardInterrupt):
                        print()
                        break
                    except Exit:
                        break

    def execute(self, name, *args):
        """Execute command with arguments and return response."""
        try:
            method = self.commands.get(name)
            if not method:
                raise Unauthorized
            return method(*args)
        except Error as e:
            return f"Error: {e}"
        except Unauthorized:
            return f"Unknown command: {name}."
        except TypeError:
            return self.usage(method)

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

    def send(self, nick, message):
        user = ctx("user")
        header = self.channel.head.format_map({"from": user.nick, "to": nick})
        body = f"{header}{message}"
        print(body)
        # TODO: send!

    def notify(self, sendto, event):
        body = f"{ctx('user').nick} {event}."
        print(body)
        # TODO: send!

    # ---- user commands -----

    @cmd(auth.phone)
    def mute(self):
        """Disable receiving messages."""
        phone = ctx("phone")
        if phone.mute:
            raise Error(f"Channel is already muted.")
        phone.mute = True
        self.notify("_ops", f"muted channel on {phone.number}")
        return f"Channel muted on {phone.number}. Use /unmute to renable."

    @cmd(auth.phone)
    def unmute(self):
        """Enable receiving messages."""
        phone = ctx("phone")
        if not phone.mute:
            raise Error(f"Channel is not muted.")
        phone.mute = False
        self.notify("_ops", f"unmuted channel on {phone.number}")
        return f"Channel unmuted on {phone.number}."

    @cmd()
    def who(self, nick=None):
        """List users or get user information."""
        if not nick or not auth.op():
            return f"Users: {listing(self.users)}."
        try:
            user = self.users[nick]
        except KeyError:
            raise Error(f"No such user: {nick}.")
        result = [f"User: {user.nick}{' [op]' if user.op else ''}"]
        if auth.op():
            result.append(
                listing([p.number for p in self.phones.values() if p.nick == user.nick])
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
            return f"Commands: {listing(valid)}."
        elif command in valid:
            method = self.commands[command]
            return f"{self.usage(method)} {method.__doc__}"
        else:
            return f"Unknown command: {command}."

    # ----- operator commands -----

    @cmd(auth.op)
    def add(self, number: vs.e164(), nick: vs.nick()):
        """Add member to channel."""
        if nick.startswith("_"):
            raise Error(f"Invalid nick: {nick}.")
        if number in self.phones:
            raise Error(f"Number already registered: {number}.")
        try:
            user = self.users[nick]
        except KeyError:
            user = vokiz.resource.User(nick)
            self.users.add(user)
        self.phones.add(vokiz.resource.Phone(number, user.nick))
        self.notify("_ops", f"added {number} as {user.nick}")

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
        self.notify("_ops", f"removed {number}{nick_msg} from channel")

    @cmd(auth.op)
    def op(self, nick: vs.nick() = None):
        """List operators or promote user to channel operator."""
        if nick is None:
            result = []
            for nick in self.users:
                if self.users[nick].op:
                    result.append(nick)
            return f"Operators: {listing(result)}."
        try:
            user = self.users[nick]
        except KeyError:
            raise Error(f"No such user: {nick}.")
        if user.op:
            raise Error(f"User {user.nick} is already channel operator.")
        user.op = True
        self.notify("_ops", f"promoted {user.nick} to channel operator")

    @cmd(auth.op)
    def deop(self, nick: vs.nick()):
        """Demote channel operator to user."""
        try:
            user = self.users[nick]
        except KeyError:
            raise Error(f"No such user: {nick}.")
        if not user.op:
            raise Error(f"User {user.nick} is not channel operator.")
        self.notify("_ops", f"demoted {user.nick} to channel user")
        user.op = False

    @cmd(auth.op)
    def alias(self, **kwargs):
        """Get or set alias."""
        return "Aliases: all=QST ops=OPS."

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
        self.notify("_ops", f'set message header to: "{value}"')

    @cmd(auth.op)
    def cast(self, nick: vs.nick() = None):
        """Get or set route for unaddressed messages."""
        return f"Unaddressed messages go to: QST."

    # ----- REPL commands -----

    @cmd(auth.repl)
    def exit(self):
        """Exit the channel."""
        raise Exit

    @cmd(auth.repl)
    def backend(self, module=None, **kwargs):
        """Get or set backend config."""
        return f"Backend: voipms did=6045551212 user=a pass=b."
