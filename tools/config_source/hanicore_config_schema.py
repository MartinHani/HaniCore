#!/usr/bin/env python3
"""
hanicore_config_schema.py - the vocabulary the configuration model is written
in. Types only; no data, no offsets, no hardware facts.

WHAT IS NOT HERE ANY MORE. The first version of this file also carried
`ConfigField`, `ConfigCurve`, `ConfigTable` and `PinCapability` dataclasses,
each with an `offset` attribute. Those existed to describe a SECOND 4096-byte
page layout parallel to the firmware's own hcconfig.h. There is one layout, it
belongs to hcconfig.h, and hcconfig_layout.py parses it - so a class whose job
is to hold an offset has no job. See hanicore_config_def.py for the direction
of authority.

APPLY POLICY AND SAFETY_CRITICAL ARE DELIBERATELY DIFFERENT THINGS.
`ApplyPolicy` answers "when may this reach the running engine". Whether a wrong
value is dangerous is an independent boolean carried beside it. An oil-pressure
shutdown threshold is LIVE_APPLY *and* safety critical; a cylinder count is
RESTART_REQUIRED *and* safety critical; a bench simulation speed is LIVE_APPLY
and is not. Folding the two into one enum makes two of those three
inexpressible.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple


class ApplyPolicy(Enum):
    """WHEN a validated change may reach the active runtime configuration."""

    LIVE_APPLY = "LIVE_APPLY"
    """Applied as soon as it validates. Calibration: tables, gains, targets."""

    RPM_ZERO_APPLY = "RPM_ZERO_APPLY"
    """Staged while the engine turns; the whole apply GROUP is swapped
    atomically the first time RPM reaches zero. Anything that changes what an
    output means - routing, geometry, strategy, sensor source."""

    RESTART_REQUIRED = "RESTART_REQUIRED"
    """Stored as desired state and NOT applied to the running system at all.
    It reaches the runtime through persistence and the next boot. Anything the
    runtime sizes or binds once at init."""


class ApplyGroup(Enum):
    """The unit of atomicity. A RPM_ZERO_APPLY group is validated and swapped
    all at once, so the runtime never sees half of a new injector map."""

    GENERAL = 0
    ENGINE_SETUP = 1
    TRIGGER_SETUP = 2
    INJECTOR_ROUTING = 3
    IGNITION_ROUTING = 4
    SENSOR_ROUTING = 5
    DBW_SETUP = 6
    OUTPUT_ROUTING = 7
    RELAY_SETUP = 8
    TABLES = 9
    MOTORSPORT = 10


class EvidenceClass(Enum):
    """How well a HARDWARE claim is supported. Attached per property, not per
    pin: "pin 92 is an analog input" and "pin 92 can be a digital input" are
    different claims with different support."""

    VERIFIED = "VERIFIED"
    """Two independent sources in this repo agree, or it is measured on this
    ECU by a gate that is in the tree."""

    PROBABLE = "PROBABLE"
    """One manufacturer document says so, and nothing contradicts it. Bosch's
    ME7.1 maximum-scope connector sheet is PROBABLE for this Bosch target:
    same ECU family, different harness."""

    UNVERIFIED = "UNVERIFIED"
    """Not established. Carries NO capabilities - an unproven pin that
    advertises a low-side driver is how a validation engine comes to permit an
    injector on an ignition coil's pin."""


@dataclass
class ConfigEnum:
    """A named set of stored values, used for both the C defines and the
    TunerStudio `bits` list so the two cannot drift."""
    name: str
    options: List[Tuple[int, str, str]]   # (stored value, C identifier, label)
    description: str = ""


class PinCap:
    """Electrical capability bits. A pin advertises what its CIRCUIT can do,
    which is not the same as what it is currently configured for."""
    NONE            = 0x0000
    AIN             = 0x0001  # analog input
    DIN             = 0x0002  # digital input
    FREQ_IN         = 0x0004  # capture / frequency input
    VR_IN           = 0x0008  # variable reluctance, needs conditioning
    HALL_IN         = 0x0010  # Hall / open-collector digital sensor
    LOW_SIDE        = 0x0020  # low-side driver output
    PWM_OUT         = 0x0040  # hardware PWM capable output
    INJ_OUT         = 0x0080  # injector power stage
    IGN_OUT         = 0x0100  # ignition coil driver
    DBW_HBRIDGE     = 0x0200  # throttle motor H-bridge channel
    RELAY_OUT       = 0x0400  # relay drive
    MAIN_RELAY_HW   = 0x0800  # a SUPPLY IC's own main-relay stage: it follows
                              # KL15 (and run-on) in HARDWARE. Carries the
                              # MAIN_RELAY function and nothing else - no CPU
                              # port, so no pump, tacho or bench pulse on it.
    SPECIAL_LOCKED  = 0x8000  # dedicated wire: supply, ground, screen, K-line,
                              # supervision. Never freely assignable.
