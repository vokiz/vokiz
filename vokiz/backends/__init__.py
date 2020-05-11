"""Vokiz backends module."""

import importlib


class BackendError(Exception):
    """Exception that is raised by a backend."""


def load(backend):
    """Load a backend from a backend configuration dataclass."""
    try:
        module = importlib.import_module(f"vokiz.backends.{backend.module}")
    except ModuleNotFoundError:
        raise BackendError(f"No such backend module: {backend.module}")
    try:
        instance = getattr(module, "SMS")(**backend.kwargs)
    except TypeError as te:
        raise BackendError(f"Invalid arguments to {backend.module} backend")
    return instance
