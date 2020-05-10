"""Vokiz configuration module."""

import click
import roax.schema as s
import toml

from dataclasses import dataclass


app_dir = click.get_app_dir("vokiz")


@dataclass
class Config:
    channel_dir: s.str() = f"{app_dir}/channels"


def init(path=None):
    global config
    file = path if path else f"{app_dir}/config.toml"
    try:
        with open(file, "r") as f:
            config = s.dataclass(Config).json_decode(toml.load(f))
    except FileNotFoundError:
        if path:  # explict path missing raises exception
            raise FileNotFoundError(f"config file {path} not found")
        config = Config()


config = None
