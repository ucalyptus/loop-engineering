"""K8s-style reconciliation loops for coding agents."""

from .controller import Controller, observe
from .manifest import Manifest, load

__all__ = ["Controller", "Manifest", "load", "observe"]
