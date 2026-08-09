"""Provider-neutral building blocks for a future SkyETA global model.

This package deliberately contains no downloaded provider data and no trained
global artifact.  It defines the contracts that a licensed, representative
historical source must satisfy before a global model can be trained honestly.
"""

from .schema import GlobalFlightRecord, SchemaError

__all__ = ["GlobalFlightRecord", "SchemaError"]
