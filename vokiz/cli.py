"""Vokiz command line module."""

import click
import roax.resource
import vokiz.processor
import wrapt

from vokiz.resource import resources, Channel


@wrapt.decorator
def handle_NotFound(wrapped, instance, args, kwargs):
    try:
        return wrapped(*args, **kwargs)
    except roax.resource.NotFound:
        raise click.ClickException(f"No such channel: {kwargs['channel']}.")


@click.group()
@click.version_option()
@click.option("--config", help="Specify config file location.")
def cli(config):
    """Vokiz: SMS group messaging."""
    vokiz.config.init(config)


@cli.command()
@click.argument("channel")
def create(channel):
    """Create a channel."""
    body = Channel(channel)
    try:
        resources.channels.create(channel, body)
    except roax.resource.Conflict:
        raise click.ClickException(f"Channel already exists: {channel}.")
    print(f"Created channel: {channel}.")


@cli.command()
@click.argument("channel")
@click.confirmation_option(
    "--yes", prompt="Confirm channel delete?", help="Confirm channel delete."
)
@handle_NotFound
def delete(channel):
    """Delete a channel."""
    resources.channels.delete(channel)
    print(f"Deleted channel: {channel}.")


@cli.command("list")
def list_():
    """List all channels."""
    listing = resources.channels.list()
    result = ", ".join(listing) if listing else "[none]"
    print(f"Channels: {result}.")


@cli.command()
@click.argument("channel")
@click.option(
    "--nick", help="Nick to use in channel.", default="Admin", show_default=True
)
@handle_NotFound
def enter(channel, nick):
    """Enter channel via command line."""
    ch = resources.channels.read(channel)
    print(f"Entering channel: {ch.id}.")
    vokiz.processor.Processor(ch).repl(nick)
    print("Writing channel configuration...")
    resources.channels.update(ch.id, ch)


@cli.command()
@click.argument("channel", required=False)
@handle_NotFound
def process(channel):
    """Perform channel processing."""
    print(f"channel={channel}")


def main():
    cli(auto_envvar_prefix="VOKIZ")
