#!/usr/bin/env python3
r"""
hw_descriptors.py - TARGET-SPECIFIC physical ECU pin descriptors.

    py tools\config_source\hw_descriptors.py          # summarise both
    py tools\config_source\hw_descriptors.py --csv    # write build/generated/

WHY THERE IS MORE THAN ONE OF THESE. The first Project 2A pin table was a
SINGLE hand-typed list of 121 pins carrying two columns, `hal_resource_me75`
and `hal_resource_me711`, that were identical for 118 of the 121 rows. That
is not a portability model, it is one board's pinout asserted about two boards.
The repo's own evidence disagrees with it on pins that matter:

  * connector pin 21 is `ZAS2_S`, "Zylinderabschaltung 2" - Bosch's own
    121-pin sheet and Bosch's own abbreviation list. The table called it
    "MAIN_RELAY_J271", VERIFIED, on both targets.
  * connector pin 121 carries NO signal in Bosch's maximum-scope sheet. The
    table called it "Main Relay Switched Power 2 / Secondary Feed", VERIFIED.
  * the ME7.1.1 V8's injectors 5..8 are EV5..EV8 on connector pins
    112/113/24/23. The table put them on 15/14/13/12, which are the four
    LSU lambda-2 wires, and its ignition 5..8 on 51/52/53/54, which are a
    lambda wire, a lambda wire, the 5 V sensor supply and a road-speed input.

So: ONE descriptor per board, each carrying its own evidence, and a common
logical API above them. A physical pin number means nothing until you say
which ECU it is on.

EVIDENCE IS PER PROPERTY, NOT PER PIN. "Pin 92 is an analog input" and "pin 92
is a general-purpose digital input" are different claims with different
support, so each capability bit carries its own EvidenceClass and its own
source string. A pin has no blanket verified flag.

NOTHING IN THIS FILE IS TYPED FROM MEMORY. Every capability comes from one of:

  ME7.1.1 (OEM ME7.1.1):
    tools/config_source/data/me71_connector_121.csv   <- extract_me71_connector.py, which
        reads the ME7.1.1 schematic set ME7.1.XLS (Bosch, K3/EEV2-Ss,
        rev. 27.01.97) and pin_kuerzel_tC_ME7.xls (Bosch's own abbreviations)
    tools/config_source/data/me711_iomap.csv  <- an OEM-firmware analysis script (not published), which
        reads the ME7.1.1 schematic set the target's OWN column
    the maintainer's design records            the K-line path and the ASIC's
        ownership of the temperature channels

  ME7.5 (4B0906018DC):
    the maintainer's design notes          "This file outranks every earlier
        pin table" - three sources reconciled, disagreements stated

A pin this evidence does not describe gets NO capabilities and evidence
UNVERIFIED. There is deliberately no "Spare I/O, DIN|LOW_SIDE" default: an
unproven pin that advertises a low-side driver is exactly how a validation
engine comes to permit an injector on an ignition coil's pin.
"""
from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

from hanicore_config_schema import EvidenceClass, PinCap  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CONN_CSV = ROOT / "tools/config_source/data/me71_connector_121.csv"
IOMAP_CSV = ROOT / "tools/config_source/data/me711_iomap.csv"
OUT_DIR = ROOT / "build/generated"

PIN_COUNT = 121

# --------------------------------------------------------------------------
# Bosch signal class -> electrical capability.
#
# Keyed by the short name Bosch prints on the connector sheet, with the wire
# role suffix removed. The COMMENT on each row is its justification, taken from
# pin_kuerzel_tC_ME7.xls. A name that is not in this table produces no
# capability at all.
# --------------------------------------------------------------------------
SIGNAL_CLASS: dict[str, tuple[int, str]] = {
    # ---- outputs Bosch drives from a CAPCOM channel -----------------------
    "EV": (PinCap.INJ_OUT | PinCap.LOW_SIDE, "Einspritzventil - injector driver stage"),
    "ZUE": (PinCap.IGN_OUT, "Zuendendstufe extern - external ignition output stage"),
    # ZAS IS RELAY CAPABLE, AND THE OEM NAME IS NOT THE REASON IT WOULD NOT BE.
    #
    # Capability is a property of the DRIVER STAGE, not of what Bosch called
    # the signal. Traced on the Ein-Ausgaenge sheet 2026-09-03: ZAS1 and ZAS2
    # reach S6000 = CJ420, a four-channel smart LOW-SIDE driver with a serial
    # diagnosis interface, and TWO OF ITS OTHER CHANNELS ARE EV7 AND EV8.
    # Cavity 21 (ZAS2) and cavity 22 (ZAS1) are clamped by TPSMB36A TVS
    # diodes to ground - which is exactly the inductive-load protection a
    # relay coil needs. Cavity 24 (EV7) already carried RELAY_OUT here; the
    # channel beside it on the same die did not, purely because of its name.
    #
    # That is the "OEM assignment became an architectural binding" defect
    # the project rules forbid.
    #
    # AND ON THIS PORSCHE BOARD IT NO LONGER REACHES CAVITY 21. This comment
    # used to end "...it would have made cavity 21 unroutable for the
    # MAIN_RELAY the first 1.8T installation needs", which was true of the
    # family workbook and is false of the ECU. _PORSCHE_TRUTH below settles
    # cavity 21 as KL15 - a POWER INPUT - and runs AFTER this table, so 21
    # ends up SPECIAL_LOCKED with no capability at all. The reasoning here is
    # still right about the CJ420 die; it simply does not apply to a cavity
    # the family sheet mislabelled. Cavity 4 and cavity 5 are where these bits
    # actually land.
    #
    # Still NOT claimed: the CJ420's current rating is not printed on the
    # sheet, and CJ420 pin 15 RES is ED_RST - the monitoring net that also
    # gates the throttle bridge - so an EGAS shutdown drops this output too.
    # Both are recorded in the maintainer's design notes and
    # neither is a reason to withhold the capability.
    "ZAS": (PinCap.LOW_SIDE | PinCap.RELAY_OUT,
            "Zylinderabschaltung - CJ420 smart low side, TVS clamped, "
            "relay capable"),
    "STST": (PinCap.LOW_SIDE, "Startersteuerung - starter control output"),
    # ---- solenoid / relay outputs ----------------------------------------
    "EKPR": (PinCap.LOW_SIDE | PinCap.RELAY_OUT, "Relais fuer elektrische Kraftstoffpumpe"),
    "TEV": (PinCap.LOW_SIDE | PinCap.PWM_OUT, "Tankentlueftungs-Ventil"),
    "AAV": (PinCap.LOW_SIDE | PinCap.PWM_OUT, "Aktivkohlefilterabschaltventil"),
    "SLV": (PinCap.LOW_SIDE | PinCap.PWM_OUT, "Sekundaerluft-Ventil"),
    "SLP": (PinCap.LOW_SIDE | PinCap.RELAY_OUT, "Sekundaerluft-Pumpe"),
    "LDR": (PinCap.LOW_SIDE | PinCap.PWM_OUT, "Ladedruckregelungs-Ventil - boost control"),
    "SRU": (PinCap.LOW_SIDE | PinCap.PWM_OUT, "Saugrohrumschaltung - intake flap"),
    "LUV": (PinCap.LOW_SIDE | PinCap.PWM_OUT, "Luftumfassungs-Ventil"),
    "ULVT": (PinCap.LOW_SIDE | PinCap.PWM_OUT, "Umluftventil Turbo"),
    "AGR": (PinCap.LOW_SIDE | PinCap.PWM_OUT, "Ausgang Abgasrueckfuehrung - EGR"),
    "NWS": (PinCap.LOW_SIDE | PinCap.PWM_OUT, "Nockenwellen-Steuerung - cam timing valve"),
    "ETH": (PinCap.LOW_SIDE | PinCap.PWM_OUT, "Elektrische Thermostatregelung"),
    "LUES": (PinCap.LOW_SIDE | PinCap.RELAY_OUT, "Lueftersteuerung - fan control"),
    "MIL": (PinCap.LOW_SIDE, "Malfunction Indicator Light"),
    "EFLA": (PinCap.LOW_SIDE, "Fehlerlampe - fault lamp"),
    "TN": (PinCap.LOW_SIDE | PinCap.PWM_OUT, "tN-Signal - engine speed OUTPUT to the cluster"),
    "MMS": (PinCap.PWM_OUT, "Motor-Soll-Moment-PWM - torque request output"),
    "KVA": (PinCap.PWM_OUT, "Kraftstoffverbrauchsanzeige - consumption output"),
    "LSH": (PinCap.LOW_SIDE | PinCap.PWM_OUT, "Lambdasonden-Heizung"),
    # ---- analog inputs ----------------------------------------------------
    "IP1": (PinCap.AIN, "Istwertpoti 1 (EGAS) - throttle position track 1"),
    "IP2": (PinCap.AIN, "Istwertpoti 2 (EGAS) - throttle position track 2"),
    "SP1": (PinCap.AIN, "Sollwertpoti 1 - accelerator pedal track 1"),
    "SP2": (PinCap.AIN, "Sollwertpoti 2 - accelerator pedal track 2"),
    "TMOT1": (PinCap.AIN, "Motortemperatur - coolant temperature"),
    "TMOT2": (PinCap.AIN, "Temperatur Kuehlerausgang - radiator outlet temperature"),
    "TAN": (PinCap.AIN, "Ansauglufttemperatur - intake air temperature"),
    "TAGR": (PinCap.AIN, "Temperatur AGR"),
    "TAB1": (PinCap.AIN, "Abgastemperatur 1"),
    "TAB2": (PinCap.AIN, "Abgastemperatur 2"),
    "TVKAT1": (PinCap.AIN, "Temperatursensor Vorkat. 1"),
    "TVKAT2": (PinCap.AIN, "Temperatursensor Vorkat. 2"),
    "PMOEL": (PinCap.AIN, "oil pressure sender"),
    "TMOEL": (PinCap.AIN, "Motoroeltemperatur"),
    "SRD": (PinCap.AIN, "Saugrohrdruck - manifold pressure"),
    "HFM": (PinCap.AIN | PinCap.FREQ_IN, "Heissfilmluftmassenmesser - air mass"),
    "FST": (PinCap.AIN, "Fuellstand Tank"),
    "AGRPOT": (PinCap.AIN, "EGR valve position potentiometer"),
    "UBE": (PinCap.AIN, "battery voltage sense"),
    "DSBKV": (PinCap.AIN, "Drucksensor Bremskraftverstaerker"),
    "DF": (PinCap.AIN, "Erregerstrom Generator DF"),
    # ---- knock: analog, but through a dedicated conditioning IC -----------
    "KS1": (PinCap.AIN | PinCap.SPECIAL_LOCKED, "Klopfsensor 1 - via the knock IC"),
    "KS2": (PinCap.AIN | PinCap.SPECIAL_LOCKED, "Klopfsensor 2 - via the knock IC"),
    "KS3": (PinCap.AIN | PinCap.SPECIAL_LOCKED, "Klopfsensor 3 - via the knock IC"),
    "KS4": (PinCap.AIN | PinCap.SPECIAL_LOCKED, "Klopfsensor 4 - via the knock IC"),
    # ---- position sensors -------------------------------------------------
    "DZG+": (PinCap.VR_IN | PinCap.FREQ_IN | PinCap.SPECIAL_LOCKED,
             "Drehzahlgeber + - crank sensor, differential, conditioned by the CJ910"),
    "DZG-": (PinCap.VR_IN | PinCap.SPECIAL_LOCKED, "Drehzahlgeber - - crank sensor return"),
    "PHA1": (PinCap.HALL_IN | PinCap.FREQ_IN, "Phasensignal 1 - camshaft position bank 1"),
    "PHA2": (PinCap.HALL_IN | PinCap.FREQ_IN, "Phasensignal 2 - camshaft position bank 2"),
    "PHA3": (PinCap.HALL_IN | PinCap.FREQ_IN, "Phasensignal 3 - camshaft position"),
    "PHA4": (PinCap.HALL_IN | PinCap.FREQ_IN, "Phasensignal 4 - camshaft position"),
    # ---- digital switch inputs -------------------------------------------
    "AC": (PinCap.DIN, "Schalter Klimabereitschaft"),
    "ACD": (PinCap.DIN, "Schalter Druck Klimaanlage"),
    "BLS": (PinCap.DIN, "Bremslichtschalter - brake light switch"),
    "BTS": (PinCap.DIN, "Bremstestschalter - brake test switch"),
    "KU": (PinCap.DIN, "Kupplung - clutch switch"),
    "GRAEIN": (PinCap.DIN, "GRA Ein - cruise on"),
    "GRAAUS": (PinCap.DIN, "GRA Aus - cruise off"),
    "GRAWA": (PinCap.DIN, "GRA Wiederaufnahme - cruise resume"),
    "GRASV": (PinCap.DIN, "GRA Setzen/Verzoegern - cruise set"),
    "LDP": (PinCap.DIN, "Schalter Leak Detection Pump"),
    "SLDP": (PinCap.DIN, "Leak Detection Pump signal"),
    "CRSH": (PinCap.DIN | PinCap.FREQ_IN, "Crash-PWM-Signal vom Air-Bag"),
    "VFZG": (PinCap.DIN | PinCap.FREQ_IN, "Geschwindigkeitssignal - road speed"),
    "KKOBI": (PinCap.DIN, "body / air-conditioning signal"),
    "TAUS": (PinCap.DIN, "switch input"),
    "TD": (PinCap.DIN, "switch input"),
    # ---- wires that are not assignable at all ----------------------------
    "EL_MA": (PinCap.SPECIAL_LOCKED, "Endstufen-Masse - power ground"),
    "KL15": (PinCap.SPECIAL_LOCKED, "Versorgungsspannung Kl.15 - switched supply"),
    "KL 30": (PinCap.SPECIAL_LOCKED, "Dauerversorgung Kl.30 - permanent supply"),
    "KL 50": (PinCap.DIN | PinCap.SPECIAL_LOCKED, "Kl.50 - starter signal"),
    "5V1": (PinCap.SPECIAL_LOCKED, "5 V sensor supply 1"),
    "5V2": (PinCap.SPECIAL_LOCKED, "5 V sensor supply 2"),
    "SEN_MA": (PinCap.SPECIAL_LOCKED, "sensor ground"),
    "SEN_SCH": (PinCap.SPECIAL_LOCKED, "sensor screen"),
    "SCH_SEN": (PinCap.SPECIAL_LOCKED, "sensor screen"),
    "KS_MA": (PinCap.SPECIAL_LOCKED, "Sensormasse Klopfsensoren"),
    "HFM_MA": (PinCap.SPECIAL_LOCKED, "air mass sensor ground"),
    "SRDS_MA": (PinCap.SPECIAL_LOCKED, "manifold pressure sensor ground"),
    "SP1_MA": (PinCap.SPECIAL_LOCKED, "pedal track 1 ground"),
    "SP2_MA": (PinCap.SPECIAL_LOCKED, "pedal track 2 ground"),
    "IP_MA": (PinCap.SPECIAL_LOCKED, "throttle position sensor ground"),
    "DZG_MA": (PinCap.SPECIAL_LOCKED, "crank sensor ground"),
    "DIAK": (PinCap.SPECIAL_LOCKED, "K-Leitung - ISO 9141 diagnostics, inside the CJ910"),
    "CAN_H": (PinCap.SPECIAL_LOCKED, "CAN High"),
    "CAN_L": (PinCap.SPECIAL_LOCKED, "CAN Low"),
    "CAN_SCH": (PinCap.SPECIAL_LOCKED, "CAN screen / reference"),
    "ESBM+": (PinCap.DBW_HBRIDGE | PinCap.SPECIAL_LOCKED, "DV-E5 throttle motor + (H-bridge)"),
    "ESBM-": (PinCap.DBW_HBRIDGE | PinCap.SPECIAL_LOCKED, "DV-E5 throttle motor - (H-bridge)"),
    # lambda sensor wiring: signal, ground, heater, pump current, reference
    "LS1VK": (PinCap.AIN | PinCap.SPECIAL_LOCKED, "Lambdasonde vor Kat. 1"),
    "LS2VK": (PinCap.AIN | PinCap.SPECIAL_LOCKED, "Lambdasonde vor Kat. 2"),
    "LS1HK": (PinCap.AIN | PinCap.SPECIAL_LOCKED, "Lambdasonde hinter Kat. 1"),
    "LS2HK": (PinCap.AIN | PinCap.SPECIAL_LOCKED, "Lambdasonde hinter Kat. 2"),
}

# Suffixes Bosch uses for the wire's ROLE, not its identity.
_ROLE_SUFFIX = re.compile(r"_(S|MA|H|SCH|SEN|UV|M|IP|IA)$")


def classify(signal: str) -> tuple[int, str]:
    """Bosch short name -> (capability bits, why). Unknown -> (0, '')."""
    if signal in SIGNAL_CLASS:
        return SIGNAL_CLASS[signal]
    base = _ROLE_SUFFIX.sub("", signal)
    if base in SIGNAL_CLASS:
        return SIGNAL_CLASS[base]
    fam = re.sub(r"\d+$", "", base)
    if fam in SIGNAL_CLASS:
        return SIGNAL_CLASS[fam]
    return 0, ""


@dataclass(frozen=True)
class PinProperty:
    """One electrical capability, with the evidence for THAT capability."""
    cap: int
    evidence: EvidenceClass
    source: str


@dataclass
class PhysicalPin:
    number: int
    oem_name: str = ""
    meaning: str = ""
    properties: tuple[PinProperty, ...] = ()
    hal_resource: str = ""
    hal_evidence: EvidenceClass = EvidenceClass.UNVERIFIED
    hal_source: str = ""

    @property
    def capabilities(self) -> int:
        m = 0
        for p in self.properties:
            m |= p.cap
        return m

    def caps_at_least(self, level: EvidenceClass) -> int:
        """Capability bits supported at `level` or better. VERIFIED > PROBABLE."""
        order = {EvidenceClass.VERIFIED: 2, EvidenceClass.PROBABLE: 1,
                 EvidenceClass.UNVERIFIED: 0}
        want = order[level]
        m = 0
        for p in self.properties:
            if order[p.evidence] >= want:
                m |= p.cap
        return m


@dataclass
class HwDescriptor:
    target_id: str
    name: str
    connector: str
    pins: list[PhysicalPin] = field(default_factory=list)

    def pin(self, n: int) -> PhysicalPin:
        return self.pins[n - 1]


# --------------------------------------------------------------------------
# ME7.1.1 OEM ME7.1.1 - derived, not typed.
# --------------------------------------------------------------------------
# Connector short name -> the name Bosch's PORT map uses for the same net.
# Each entry states why the two names are the same signal.
_PORT_ALIAS: dict[str, tuple[str, EvidenceClass, str]] = {
    "DZG+": ("KWDG", EvidenceClass.VERIFIED,
             "me7_port.xls MAIN P2.15 CC15IO = KWDG (Kurbelwellen-Drehzahlgeber); "
             "hctarget.h and the hardware-proven capture path use CC15"),
    "PHA1": ("NWDG", EvidenceClass.VERIFIED,
             "me7_port.xls MAIN P2.8 CC8IO = NWDG (Nockenwellen-Drehzahlgeber)"),
    "PHA2": ("NWDG2", EvidenceClass.VERIFIED,
             "me7_port.xls MAIN P2.9 CC9IO = NWDG2"),
    "SP1": ("SPS1/DKG", EvidenceClass.PROBABLE,
            "me7_port.xls MAIN P5.8 AN8 = SPS1/DKG; connector SP1_S = Sollwertpoti 1"),
    "SP2": ("SPS2", EvidenceClass.PROBABLE,
            "me7_port.xls MAIN P5.9 AN9 = SPS2"),
    "TMOT1": ("", EvidenceClass.VERIFIED,
              "NOT on the main CPU: ME7.1.1 schematic - TMOT is ASIC AN0 "
              "and reaches the CPU only inside the SSC frame"),
    "TAN": ("", EvidenceClass.VERIFIED,
            "NOT on the main CPU: TANS is ASIC AN1, same SSC path as TMOT"),
    "DIAK": ("TXD/RXD", EvidenceClass.VERIFIED,
             "ME7.1.1 schematic - connector 43 -> CJ910 pin 30 RT; the "
             "transceiver is inside the CJ910 and no CPU pin gates it"),
    "UBE": ("UBAT", EvidenceClass.VERIFIED,
            "me7_port.xls MAIN P5.5 AN5 = UBAT. The battery path is one of the "
            "three things V26 proved on hardware, so leaving this cavity "
            "unrouted would have hidden the only analog channel this ECU has "
            "actually demonstrated."),
    "IP1": ("IP1S", EvidenceClass.VERIFIED,
            "me7_port.xls MAIN P5.1 AN1 = IP1S; pin_kuerzel_tC_ME7.xls: "
            "IP1S = 'Istwertpoti 1 (EGAS)'"),
    "IP2": ("IP2S", EvidenceClass.VERIFIED,
            "me7_port.xls MAIN P5.3 AN3 = IP2S"),
    "ESBM+": ("DVE1", EvidenceClass.VERIFIED,
              "me7_port.xls MAIN P7.2 POUT2 = DVE1; pin_kuerzel: ESBM+ = "
              "'Electronic-System-Baukasten DV-E5 Motor +'"),
    "ESBM-": ("DVE2", EvidenceClass.VERIFIED,
              "me7_port.xls MAIN P7.7 CC31IO = DVE2"),
    "EKPR": ("EKP", EvidenceClass.VERIFIED,
             "me7_port.xls MAIN P2.12 CC12IO = EKP (elektrische Kraftstoffpumpe)"),
    # Outputs the ME7.1.1 gives to the PERIPHERAL ASIC, not the main CPU. On
    # this ECU the boost valve, the purge valve and the EGR valve are the
    # ASIC's PWM unit - the maintainer's design records, "what the ASIC owns".
    # Naming them NOT_ON_MAIN_CPU is the point: the first Project 2A table put
    # the boost valve on MAIN P7.1, which on this board is NWS2.
    "LDR": ("", EvidenceClass.VERIFIED,
            "NOT on the main CPU: me7_port.xls ASIC-mC P7.2 POUT2 = LDR"),
    "TEV": ("", EvidenceClass.VERIFIED,
            "NOT on the main CPU: me7_port.xls ASIC-mC P7.3 POUT3 = TEV"),
    "AGR": ("", EvidenceClass.VERIFIED,
            "NOT on the main CPU: me7_port.xls ASIC-mC P7.1 POUT1 = AGR"),
    "SLP": ("", EvidenceClass.VERIFIED,
            "NOT on the main CPU: me7_port.xls ASIC-mC P1L.0 = SLP"),
    "SLV": ("", EvidenceClass.VERIFIED,
            "NOT on the main CPU: me7_port.xls ASIC-mC P7.0 POUT0 / P7.7 = SLV"),
    "AAV": ("", EvidenceClass.VERIFIED,
            "NOT on the main CPU: me7_port.xls ASIC-mC P1L.1 = AAV"),
    "MIL": ("", EvidenceClass.VERIFIED,
            "NOT on the main CPU: the MIL lamp is an ASIC output on this family"),
    "LUV": ("", EvidenceClass.VERIFIED,
            "NOT on the main CPU: me7_port.xls ASIC-mC P2.0 CC0IO = LUV"),
    "CRSH": ("", EvidenceClass.VERIFIED,
             "NOT on the main CPU: me7_port.xls ASIC-mC P1H.1 = CRSH"),
}

# ZUEn (connector) and ZDGn (port map) are the same eight ignition stages.
# Corroborated independently for 1..4 by the maintainer's design notes, whose
# ME7.5 coil table is ZUE1=102/P2.0, ZUE2=103/P2.1, ZUE3=94/P2.2, ZUE4=95/P2.3
# - identical pins and identical ordinals to this join.
for _n in range(1, 9):
    _PORT_ALIAS["ZUE%d" % _n] = (
        "ZDG%d" % _n,
        EvidenceClass.VERIFIED if _n <= 4 else EvidenceClass.PROBABLE,
        "me7_port.xls MAIN P2.%d CC%dIO = ZDG%d; connector ZUE%d = "
        "'Zuendendstufe %d extern'%s" % (
            _n - 1, _n - 1, _n, _n, _n,
            "; ordinals corroborated by docs/HANICORE_ENGINE_IO_MAP.md"
            if _n <= 4 else
            "; ordinal correspondence only - no second source for 5..8"),
    )


def _read_conn() -> list[dict[str, str]]:
    if not CONN_CSV.exists():
        raise SystemExit(
            "%s missing - run tools/config_source/extract_me71_connector.py" % CONN_CSV)
    return list(csv.DictReader(CONN_CSV.open(encoding="utf-8")))


def _read_portmap() -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for r in csv.DictReader(IOMAP_CSV.open(encoding="utf-8")):
        if r["processor"] != "MAIN CPU":
            continue
        sig = r["me711_signal"].strip()
        if sig and sig not in out:
            out[sig] = (r["port"], r["peripheral_fn"])
    return out


CONN_SRC = ("tools/config_source/data/me71_connector_121.csv <- Bosch "
            "'Steckerb. ME7.1.XLS' + 'pin_kuerzel_tC_ME7.xls'")


# V97: WHAT A TUNER READS IN A PIN DROPDOWN - the
# cavity number and the OEM FUNCTION of that cavity on this ECU, in words.
# The Bosch mnemonic (TMOT, TANS, IP1_S ...) and the CPU/ASIC resource stay
# in the descriptor (oem_name / meaning / hal_resource) for evidence and
# advanced views; they are never the dropdown's main label. "Pedal", never
# "APP". generate_config refuses to offer a cavity that has no entry here.
# Every name follows the descriptor meaning of the same cavity.
FRIENDLY_CAVITY_NAMES = {
    # V98: the OEM switch inputs, read through the S5500 (SWITCH_INPUTS)
    38: "Cruise main switch", 39: "Clutch switch", 40: "A/C request",
    55: "Brake test switch", 56: "Brake light switch", 57: "Cruise set",
    75: "Cruise resume", 76: "Cruise off",
    6: "Rear O2 sensor 2 heater",
    7: "Ignition output 8",
    8: "Ignition output 7",
    10: "Rear O2 sensor 2 ground",
    11: "Rear O2 sensor 2 signal",
    19: "Injector output 8",
    23: "Main relay",
    24: "Injector output 7",
    26: "Intake air temperature",
    29: "MAF sensor",
    34: "Pedal sensor 2",
    35: "Pedal sensor 1",
    37: "Tacho output",
    47: "Check engine lamp",
    63: "Rear O2 sensor 1 heater",
    65: "Fuel pump relay",
    68: "Rear O2 sensor 1 ground",
    69: "Rear O2 sensor 1 signal",
    81: "Fuel consumption output",
    82: "Crankshaft position",
    84: "Throttle position 2",
    86: "Camshaft position 1",
    87: "Camshaft position 2",
    88: "Injector output 3",
    89: "Injector output 4",
    92: "Throttle position 1",
    93: "Coolant temperature",
    94: "Ignition output 3",
    95: "Ignition output 4",
    96: "Injector output 1",
    97: "Injector output 2",
    101: "MAP / pressure",
    102: "Ignition output 1",
    103: "Ignition output 2",
    104: "Boost control valve",
    110: "Ignition output 5",
    111: "Ignition output 6",
    112: "Injector output 5",
    113: "Injector output 6",
    115: "Cam timing valve 1",
    117: "Throttle motor +",
    118: "Throttle motor -",
    120: "Cam timing valve 2",
}


def build_me711() -> HwDescriptor:
    conn = _read_conn()
    ports = _read_portmap()
    # The connector workbook is a VW/Audi ME7.1 maximum-scope drawing. Every
    # row it alone supports is PROBABLE for this Bosch target OEM ME7.1.1, exactly as
    # the maintainer's design records already says about connector pin 43.
    d = HwDescriptor(
        "BOSCH_ME711",
        "Bosch ME7.1.1 / V8 target",
        "121-pin SKE, Bosch 'Steckerbelegung ME7.1 mit 121 pol. SKE-Stecker'",
    )
    for row in conn:
        n = int(row["pin"])
        sigs = [s for s in row["signals"].split("|") if s]
        props: list[PinProperty] = []
        why: list[str] = []
        for s in sigs:
            cap, reason = classify(s)
            if cap:
                props.append(PinProperty(cap, EvidenceClass.PROBABLE,
                                         "%s: %s = %s" % (CONN_SRC, s, reason)))
                why.append("%s = %s" % (s, reason))
        # A cavity can carry more than one signal because Bosch built several
        # variants on one connector - pin 26 is "TAN_S | UBE_S". Collect every
        # resolution and PREFER a concrete main-CPU resource over
        # NOT_ON_MAIN_CPU: if this target's own port map puts one of the
        # variants on this CPU, that is the variant this ECU is built as.
        cands = []
        hal, hal_ev, hal_src = "", EvidenceClass.UNVERIFIED, ""
        for s in sigs:
            base = _ROLE_SUFFIX.sub("", s)
            key = base if base in _PORT_ALIAS else s
            if key in _PORT_ALIAS:
                pname, ev, src = _PORT_ALIAS[key]
                if pname == "":
                    cands.append(("NOT_ON_MAIN_CPU", ev, src))
                elif pname in ports:
                    port, fn = ports[pname]
                    cands.append(("%s/%s" % (port, fn), ev, src))
                else:
                    cands.append((pname, ev, src))
                continue
            if base in ports:
                port, fn = ports[base]
                cands.append(("%s/%s" % (port, fn), EvidenceClass.VERIFIED,
                              "tools/config_source/data/me711_iomap.csv <- Bosch "
                              "me7_port.xls, the OEM ME7.1.1's own column: "
                              "MAIN %s %s = %s" % (port, fn, base)))
        for c in cands:
            if c[0] != "NOT_ON_MAIN_CPU":
                hal, hal_ev, hal_src = c
                break
        else:
            if cands:
                hal, hal_ev, hal_src = cands[0]
        d.pins.append(PhysicalPin(n, "|".join(sigs), " | ".join(why),
                                  tuple(props), hal, hal_ev, hal_src))
    _apply_porsche_truth(d)
    _apply_me711_sheet(d)
    _apply_asic_frame_outputs(d)
    _apply_switch_inputs(d)
    assert len(d.pins) == PIN_COUNT
    _refuse_reserved_resources(d)
    return d


# ==========================================================================
# CPU PINS AN ON-BOARD FUNCTION OWNS - NO CONNECTOR ROUTE MAY NAME ONE
# ==========================================================================
#
# V95 (found 2026-09-28 in the V93 Tier 2 review): the sheet layer offered
# cavities 18 and 22 as RELAY_OUT | LOW_SIDE on P8.2 / P8.1, and on THIS board
# those two pins are the CJ120 chip selects. A relay or tacho routed there
# VALIDATED (the HAL had no drive case, so nothing moved - a silent dead
# route) and was one HAL case away from toggling a wideband chip select on
# the SSC the S5500 shares. The fix is not two edits: it is this list,
# checked on every build of the descriptor, so the next cavity whose
# family-sheet resource collides with a board function fails here.
#
# Each entry: CPU pin -> (owner, evidence). A pin a cavity legitimately IS
# (P2.15 = the crank capture on cavity 82, P7.2/P7.7 = the throttle bridge on
# 117/118) is not listed: a dedicated function on its own cavity is not a
# collision. Only pins with NO connector route of their own are here.
RESERVED_CPU_PINS = {
    "P8.1": ("CJ120 chip select, wideband bank 1 (device 0)",
             "EXACT TARGET BINARY: BCLR P8.1 0x8C075A / "
             "BSET P8.1 0x8C07A0 around the CJ120 SSC transfer [0x8C0734], "
             "P8.1 latched HIGH + output at 0x8BFF60..66 (init). PHYSICAL "
             "EXACT: HaniCore's CJ120 driver (hcio711.c IO_CJ_CS1) selects "
             "the chip on this pin and INIT/IDENT/DIAG answer on the bench"),
    "P8.2": ("CJ120 chip select, wideband bank 2 (device 1)",
             "EXACT TARGET BINARY: BCLR P8.2 0x8C0756 / BSET P8.2 0x8C079C, "
             "init 0x8BFF6A..70. PHYSICAL EXACT: IO_CJ_CS2, bench CJ120 "
             "INIT/IDENT/DIAG. Port map C-Muster column: CS_CJ120"),
    "P6.0": ("external flash chip select", "hcasic.c: P6.0/P6.1 are the "
             "flash and RAM chip selects (bus configuration)"),
    "P6.1": ("external RAM chip select", "hcasic.c"),
    "P6.3": ("CS_EEPR, the serial EEPROM chip select", "hcmain_me711.c P6 init"),
    "P6.4": ("CS_ASIC, the S5500 chip select", "hcasic.c TGT_ASIC_CS_PORT_BIT"),
    "P3.8": ("SSC MRST (S5500 + CJ120 bus)", "hcasic.c ASIC_MRST_DIR"),
    "P3.9": ("SSC MTSR (S5500 + CJ120 bus)", "hcasic.c ASIC_MTSR_DIR"),
    "P3.13": ("SSC SCLK (S5500 + CJ120 bus)", "hcasic.c ASIC_SCLK_DIR"),
    "P3.10": ("ASC0 TXD, the K-line (cavity 43 through the CJ910)",
              "hcmain_me711.c TXD0; hctarget.h K-line path"),
    "P3.11": ("ASC0 RXD, the K-line and the 5-baud decoder",
              "hcmain_me711.c RXD0"),
    "P3.12": ("NLEN_FR, the CJ910 run-on veto", "hcio711.c IO_NLEN_FR; "
              "PHYSICAL: run-on measured V80"),
    "P3.15": ("the CJ220 throttle bridge status flag SF", "hchal_me711.c "
              "DBW_SF_PIN (TGT_DBW_SF_PORT_BIT)"),
    "P2.11": ("EGENFR, the CJ220 throttle bridge enable (active LOW)",
              "hctarget.h, the project rules"),
    "P6.2": ("KL15 status input", "the project rules: KL15 readable on P6.2"),
}
# Anything that would let a logical function USE the cavity. A cavity that
# carries only SPECIAL_LOCKED is a dedicated wire nothing can be routed to.
_ROUTE_CAPS = (PinCap.LOW_SIDE | PinCap.PWM_OUT | PinCap.INJ_OUT
               | PinCap.IGN_OUT | PinCap.RELAY_OUT | PinCap.DBW_HBRIDGE
               | PinCap.AIN | PinCap.DIN | PinCap.FREQ_IN | PinCap.HALL_IN
               | PinCap.VR_IN | PinCap.MAIN_RELAY_HW)


def cpu_pin(resource: str) -> str:
    """'P8.2/CC18IO' -> 'P8.2'; anything that is not a main-CPU port -> ''."""
    m = re.match(r"(P\d+\.\d+)(?:/|$)", resource or "")
    return m.group(1) if m else ""


def reserved_collisions(d: "HwDescriptor") -> list:
    """[(cavity, pin, owner)] for every routable cavity naming a reserved pin."""
    out = []
    for p in d.pins:
        pin = cpu_pin(p.hal_resource)
        if pin in RESERVED_CPU_PINS and (p.capabilities & _ROUTE_CAPS):
            out.append((p.number, pin, RESERVED_CPU_PINS[pin][0]))
    return out


def _refuse_reserved_resources(d: "HwDescriptor") -> None:
    """A descriptor that offers a reserved CPU pin must not reach a generated
    table, a validator or a dropdown."""
    bad = reserved_collisions(d)
    if bad:
        raise SystemExit("RESERVED CPU PIN offered on a connector route: "
                         + "; ".join("cavity %d names %s = %s" % b for b in bad))


# V79: OUTPUTS THE MAIN CPU REACHES THROUGH THE S5500 FRAME'S PORT IMAGE.
# The family workbook marks them NOT_ON_MAIN_CPU, which is true of the PIN
# and false of the REACH: [BIN 0x8BE2B6] sends the ASIC's P7/P8 image in
# runtime word 58 and the OEM's actuator test switches LDR by FDE8.2
# (hcio711.c). Routable, with that resource named, and PROBABLE: the cavity
# rests on the family workbook and the stage has never been measured.
_ASIC_FRAME_OUTPUTS = {
    104: ("LDR - boost valve (AWT N75), ASIC P7.2",
          PinCap.LOW_SIDE | PinCap.PWM_OUT, "ASIC P7.2 LDR via frame word 58",
          "family workbook 104 = SRU1_S|LDR_S; port map ASIC P7.2 = LDR "
          "(B-Muster); OEM actuator test [BIN 0x88F766] toggles FDE8.2"),
    # V97: the check-engine lamp stage - ASIC P7.0 through a CJ920 low side
    47: ("MIL - check-engine lamp, ASIC P7.0",
         PinCap.LOW_SIDE, "ASIC P7.0 via frame word 58",
         "me711.pdf W12 sheet LUES2_PX70 -> S6500 -> 47 A_S_LUES2/"
         "A_S_SPOEKUE/A_S_MIL; family workbook 47 = MIL_S; OEM actuator "
         "test [BIN 0x08F8C6/CA] toggles FDE8.0"),
}


# ==========================================================================
# THE DIGITAL SWITCH INPUTS (V98) - ONE TABLE, THE ONLY SOURCE OF TRUTH
# ==========================================================================
#
# cavity -> how firmware reads it -> how a switch is wired -> evidence.
# hchal_me711.c hc_hal_din() implements exactly these (word/bit for the ASIC
# ones), generate_config offers exactly these in every switch dropdown, and
# me711_switch_input_proof holds the three together.
#
# TWO READ PATHS:
#   CPU   86/87: the phase inputs, main CPU P2.8/P2.9 (VERIFIED me7_port.xls),
#         open-collector front end with a 2.61 kOhm PULL-UP - a switch to
#         GROUND reads LOW.
#   ASIC  the OEM switch inputs. The S5500 reads them on ITS ports and sends a
#         port snapshot in every runtime reply (RX words 53..59 = ASIC P0, P1,
#         P2, P3, P5, P6:P4, P8:P7). Evidence chain:
#         the maintainer's design notes.
#           S5500 IROM (bins/ASIC-IROM-7x00005d, sibling, same ASIC): 0x47A2
#             /0x4858 snapshot the ports, 0x48AE copies the 7 words to reply
#             byte +0x6A = word 53 (reply header 0x781E written there too);
#           A1104F + its A2L (T44HEH0, a matching pair): 0x8B470A builds
#             S_bls/S_kupp/S_fgr*/S_brs/S_ac/S_tal (FD88) from the mailbox
#             copies of words 55/56/59 at FDF4/FDF6/FDFC;
#           THIS ECU's OEM firmware 0x88F62C: the same bits with the
#             same inversions from FDEE/FDF0/FDF6 = words 55/56/59 (its RX
#             table, build/generated/me711_asic_runtime_frame.csv);
#           the ME7.1.1 schematic (same-generation ME7.1.1): cavity -> E_S_* -> 68.1 kOhm
#             -> ASIC pin (BL_PX31, GRA_PX32, KUP_PX34, SV_PX35, WA_PX36,
#             AUS_PX37, BT_PX22, AC_PX85), a 2.61 kOhm PULL-DOWN to GND where
#             fitted - a switch to +12 V reads HIGH. BL goes through an LM2904
#             comparator against ~78 % of UB_IN.
#         Class: EXACT TARGET BINARY for the word/bit, SAME-GENERATION
#         SCHEMATIC for cavity and front end. PROBABLE until one physical
#         toggle (the maintainer's design records lists the test per cavity).
#   NOT offered: KL50 (P3.3/P2.1, the starter - a special function), the
#   tank-level / crash / coding inputs (not switches a tuner wires).
#
#   cavity: (read path, wiring, tuner name, evidence)
SWITCH_INPUTS = {
    86: ("CPU P2.8", "switch to ground", "Cam input 1",
         "me7_port.xls MAIN P2.8 PHA1; me711.pdf 2.61 kOhm pull-up"),
    87: ("CPU P2.9", "switch to ground", "Cam input 2",
         "me7_port.xls MAIN P2.9 PHA2; me711.pdf 2.61 kOhm pull-up"),
    38: ("ASIC P3.2 (reply word 56 bit 2)", "switch to +12 V",
         "Cruise main switch input", "E_S_GRA -> GRA_PX32; 0x88F62C FDF0.2"),
    39: ("ASIC P3.4 (reply word 56 bit 4)", "switch to +12 V",
         "Clutch switch input", "E_S_KUP -> KUP_PX34; 0x88F62C FDF0.4"),
    40: ("ASIC P8.5 (reply word 59 bit 13)", "switch to +12 V",
         "A/C request input", "E_S_AC -> AC_PX85; 0x88F62C FDF6.13"),
    55: ("ASIC P2.2 (reply word 55 bit 2)", "switch to +12 V",
         "Brake test switch input", "E_S_BT -> BT_PX22; 0x88F62C FDEE.2"),
    # BL is INVERTED at the pin: an LM2904 compares the input with ~78 % of
    # UB_IN and its output is HIGH while the input is low - bench 2026-10-01,
    # input open: word 56 bit 1 = 1. A switch to +12 V reads LOW.
    56: ("ASIC P3.1 (reply word 56 bit 1)", "switch to +12 V, reads inverted",
         "Brake light switch input", "E_S_BL -> LM2904 -> BL_PX31; "
         "0x88F62C FDF0.1; bench: open = 1"),
    57: ("ASIC P3.5 (reply word 56 bit 5)", "switch to +12 V",
         "Cruise set input", "E_S_SV -> SV_PX35; 0x88F62C FDF0.5"),
    75: ("ASIC P3.6 (reply word 56 bit 6)", "switch to +12 V",
         "Cruise resume input", "E_S_WA -> WA_PX36; 0x88F62C FDF0.6"),
    76: ("ASIC P3.7 (reply word 56 bit 7)", "switch to +12 V",
         "Cruise off input", "E_S_AUS -> AUS_PX37; 0x88F62C FDF0.7"),
}
# the ASIC ones as firmware reads them: cavity -> (reply word, bit), parsed
# from the read path above (V98r2: was a second hand-typed table) and
# emitted into hc_config_generated.h (HC_SWITCH_ASIC_*) for hc_hal_din().
SWITCH_INPUT_ASIC_BITS = {
    n: tuple(int(x) for x in re.search(r"reply word (\d+) bit (\d+)",
                                       p[0]).groups())
    for n, p in SWITCH_INPUTS.items() if p[0].startswith("ASIC")}
SWITCH_INPUT_CAVITIES = set(SWITCH_INPUTS)


def _apply_switch_inputs(d: "HwDescriptor") -> None:
    for n, (path, wiring, _name, why) in SWITCH_INPUTS.items():
        old = d.pin(n)
        # The CPU port is the target's own column of the port map (VERIFIED);
        # the cavity -> pin path is a schematic reading (PROBABLE), like
        # every connector-side claim not measured on this ECU.
        hal_ev = (EvidenceClass.VERIFIED if path.startswith("CPU")
                  else EvidenceClass.PROBABLE)
        d.pins[n - 1] = PhysicalPin(
            n, old.oem_name, old.meaning,
            old.properties + (PinProperty(
                PinCap.DIN, EvidenceClass.PROBABLE,
                "SWITCH INPUT: %s, %s; %s" % (path, wiring, why)),),
            old.hal_resource or path, old.hal_evidence if old.hal_resource
            else hal_ev, old.hal_source or ("SWITCH INPUT: " + why))


def _apply_asic_frame_outputs(d: "HwDescriptor") -> None:
    for n, (meaning, cap, hal, why) in _ASIC_FRAME_OUTPUTS.items():
        old = d.pin(n)
        d.pins[n - 1] = PhysicalPin(
            n, old.oem_name, meaning,
            (PinProperty(cap, EvidenceClass.PROBABLE, "ASIC FRAME LAYER: " + why),),
            hal, EvidenceClass.PROBABLE, "ASIC FRAME LAYER: " + why)


# ==========================================================================
# THE PORSCHE OVERRIDE LAYER, AND IT IS A SAFETY FIX, NOT A FILING FIX
# ==========================================================================
#
# Everything above is derived from `Steckerb. ME7.1.XLS`, a VW/Audi ME7.1 C4
# maximum-scope connector workbook. Against the ME7.1.1 sheet and against
# Porsche's own service documentation it is WRONG FOR A WHOLE BLOCK - 21 is
# KL15 and not ZAS2, 23 is the main relay and not EV8, 19 is EV8, 18 is ZAS2,
# 22 is ZAS1; only 24 = EV7 agrees.
#
# The consequence is not cosmetic. The unmodified descriptor OFFERS CAVITY 23
# AS AN INJECTOR OUTPUT when cavity 23 is the main relay drive, and CAVITY 21
# AS A RELAY OUTPUT when cavity 21 is a power input feeding the CJ910's enable.
# Routing either would command a driver into a wire that is not one.
#
# the project rules settle seven cavities from THREE AGREEING SOURCES:
# Porsche connector/service documentation, this ECU on the bench, and the
# ME7.1.1 schematic rendered at 600 dpi. Those seven are hard facts and they
# win over the family workbook. The rest of the disputed block is NOT settled,
# so it is LOCKED rather than relabelled: a friendly wrong label is worse than
# a raw integer, because a tuner has no reason to distrust it.
#
# WHAT THIS IS NOT. It is not the full regeneration the project rules ask
# for - that needs an ME7.1.1 connector sheet this repository does not have.
# It is the part that can be done from evidence that exists, and it removes the
# specific hazard the descriptor was flagged for.

# (cavity, what it really is, the capability it may advertise, why)
#
# SPECIAL_LOCKED alone means "dedicated wire, never freely assignable" - the
# validator will not route a logical function to it at all.
_PORSCHE_TRUTH = {
    1:  ("Terminal 31, electronics ground", PinCap.SPECIAL_LOCKED,
         "Porsche connector documentation + PHYSICAL EXACT: GND on the bench"),
    2:  ("Terminal 31, electronics ground", PinCap.SPECIAL_LOCKED,
         "Porsche connector documentation + PHYSICAL EXACT: GND on the bench"),
    3:  ("Relay-switched DME main power", PinCap.SPECIAL_LOCKED,
         "Porsche connector documentation + PHYSICAL EXACT: +12 V on the bench"),
    21: ("KL15, ignition lock - A POWER INPUT", PinCap.SPECIAL_LOCKED,
         "SETTLED by three agreeing sources. ME7.1.1 sheet: cav 21 = U_U_KL15 "
         "-> R4000 1.47k -> CJ910 pin 21 EIN. PHYSICAL EXACT: removing +12 V "
         "from cavity 21 while 3 and 62 stay powered takes the ECU OFFLINE. "
         "The family workbook calls this ZAS2 and it is not",
         "CJ910 EIN via R4000 (KL15 state readable on P6.2)"),
    23: ("DME main relay, terminal 85 low-side drive - the CJ910's own MR "
         "stage, which follows KL15 in hardware",
         PinCap.MAIN_RELAY_HW,
         "SETTLED: Porsche service documentation and the ME7.1.1 sheet agree "
         "- cav 23 = A_S_HR <- SP_S4000_16 <- CJ910 (S4000) pin 16 HR; net "
         "HR_PXA514 is the peripheral ASIC's SENSE of it (P5.14/AN14, 'Port "
         "nur Input'). CJ911_Product_Info.pdf (the CJ910's pin-for-pin "
         "sibling, SIBLING COMPONENT DATASHEET): pin 16 MR 'Main relay stage "
         "output', a low-side switch whose only controls are EN1 = KL15 "
         "('control for all switchable outputs') and /EN2 = keep-alive, "
         "active low (NL <- NLEN_FR P3.12 and NLEN_AS). No CPU port commands "
         "it. So it is offered to MAIN_RELAY alone, as a hardware function, "
         "never as a CPU output. The family workbook calls this EV8 and it "
         "is not", "CJ910 MR (EN1/KL15, /EN2 run-on)"),
    43: ("K-line", PinCap.SPECIAL_LOCKED,
         "Porsche connector documentation + PHYSICAL EXACT: this is the wire "
         "TunerStudio talks over"),
    62: ("Terminal 30, permanent B+", PinCap.SPECIAL_LOCKED,
         "Porsche connector documentation + PHYSICAL EXACT: +12 V on the "
         "bench"),
}

# The Porsche ME7.1.1 connector names of the settled cavities (the project rules
# section 7 power table: Porsche documentation + the ME7.1.1 sheet).
_PORSCHE_NAME = {3: "U_U_UBR", 21: "U_U_KL15", 23: "A_S_HR", 62: "U_U_UBD"}

# Meaning (not capability) corrections from the ME7.1.1 sheet. The capability
# bits of these cavities are compiled into the image's pin table, so they are
# left as they are; only the description the documentation shows is fixed.
_MEANING_FIX = {
    85: ("E_A_DSBKV", "E_A_DSBKV - brake-booster pressure: 68.1 kOhm into ASIC AN6 "
         "with a 681 kOhm pull-up. It CANNOT read an NTC; the family workbook's "
         "TAN_S (intake air temperature) label is wrong for this board - the AWT "
         "IAT wire moves to cavity 26"),
}

# The rest of the block the family workbook gets wrong. NOT settled, so not
# relabelled - locked, with the reason attached, until an ME7.1.1 connector
# sheet says what they are.
_DISPUTED_BLOCK = tuple(n for n in range(18, 25) if n not in _PORSCHE_TRUTH)


def _apply_porsche_truth(d: "HwDescriptor") -> None:
    """Replace the family workbook's answer where Porsche evidence exists, and
    LOCK what is merely known to be wrong."""
    for n, entry in _PORSCHE_TRUTH.items():
        meaning, cap, why = entry[:3]
        old = d.pin(n)
        # A fourth element REPLACES the port map's HAL resource. Cavity 23
        # needs it: the family workbook put EV8 there, so its inherited
        # resource was P8.3 - an injector port - on a cavity that is now
        # routable. Everywhere else the port map's CPU column stands.
        d.pins[n - 1] = PhysicalPin(
            # The Porsche ME7.1.1 net name where the project has settled it;
            # the family workbook's label (KL15 on 3, ZAS2 on 21, EV8 on 23)
            # was wrong for this board and only ever reached comments.
            n, _PORSCHE_NAME.get(n, old.oem_name), meaning,
            # ONE PROVENANCE TAG ON EVERY OVERRIDE. Each `why` names its own
            # sources, but a reader - and the test that requires every
            # capability to cite where it came from - needs one string it can
            # look for. This is the layer, and the project rules are where
            # the three agreeing sources are written down.
            (PinProperty(cap, EvidenceClass.VERIFIED,
                         "the project rules, Porsche override: " + why),),
            # The HAL resource stays whatever the port map said, because that
            # column is about the CPU and is not what was wrong.
            entry[3] if len(entry) > 3 else old.hal_resource,
            old.hal_evidence, old.hal_source)

    for n, (name, text) in _MEANING_FIX.items():
        old = d.pin(n)
        d.pins[n - 1] = PhysicalPin(n, name, text, old.properties, old.hal_resource,
                                    old.hal_evidence, old.hal_source)

    for n in _DISPUTED_BLOCK:
        old = d.pin(n)
        d.pins[n - 1] = PhysicalPin(
            n, old.oem_name,
            "LOCKED - the family connector workbook is demonstrably wrong for "
            "cavities 18..24 on this board and no ME7.1.1 sheet is in this "
            "repository. Was: %s" % (old.meaning or old.oem_name),
            (PinProperty(PinCap.SPECIAL_LOCKED, EvidenceClass.VERIFIED,
                         "the project rules: against the ME7.1.1 sheet the "
                         "ME7.1 C4 workbook is wrong for this whole block - "
                         "21 is KL15 not ZAS2, 23 is the main relay not EV8, "
                         "19 is EV8, 18 is ZAS2, 22 is ZAS1; only 24 = EV7 "
                         "agrees. A wrong capability here routes a driver "
                         "into a wire that is not one"),),
            old.hal_resource, old.hal_evidence, old.hal_source)


# ==========================================================================
# THE ME7.1.1 SHEET LAYER - read by eye at 330 dpi, 2026-09-16
# ==========================================================================
#
# `the ME7.1.1 schematic`, sheet 1 of 2, *ME 7.1.1 - C4, Rechnerkern
# und Rechnerperipherie*, Bosch `0 261 C0 776`. It is a VECTOR pdf whose text is
# converted to curves: pdfplumber extracts ZERO characters and it renders
# perfectly at any DPI, which is why it can be read at all and why no tool can
# do it for you.
#
# THIS IS THE EVIDENCE the project ASKED FOR AND DID NOT HAVE.
# That section locked cavities 18..24 with: "No cavity in 18..24 may be routed
# or bench-commanded until the descriptor is regenerated against ME7.1.1
# evidence." The sheet names all of them, and the port map independently gives
# their CPU resources with BOTH ME7.1.1 columns agreeing for the two that
# matter. The block is unlocked here on exactly that pairing.
#
# STILL SAME-GENERATION, NOT THIS BOARD. `the ME7.1.1 schematic set` is an Audi
# W12/D3 ME7.1.1 C4 variant. It settles what signal is on which cavity for the
# ME7.1.1 GENERATION. It does NOT settle whether a given driver is POPULATED on
# the Porsche board - the sheet draws variant options in red, and the S8621
# ignition driver feeding cavities 7 and 8 is one of them. Population is a
# resistance measurement, not a reading.
#
# (cavity, what it is, capabilities, HAL resource, why)
_ME711_SHEET = {
    # ---- V85: THE WIDEBAND LAMBDA BLOCK, from the LOWER HALF of the ME7.1.1 schematic
    # page 1. The PDF's crop box is 842 x 595 of an 842 x 1191 page, so every
    # earlier render stopped half way down the I/O sheet; set_cropbox(mediabox)
    # shows two CJ120s (S1071 bank 1, S1051 bank 2; the CJ110s beside them are
    # drawn in the variant colour), their pump shunts R1070/R1050 61.9 ohm and
    # the heater stages. The ME7.5 C2-2 sheet uses the SAME cavities for its
    # own LSU bank 1 (70/51/71/52 + heater 5), and the ME7.1 family workbook
    # agrees for both banks. Dedicated sensor wires of a fixed hardware
    # function: locked, never freely assignable.
    70: ("LSU bank 1 UN (Nernst cell) -> CJ120 S1071",
         PinCap.SPECIAL_LOCKED, "CJ120 bank 1 UN",
         "me711.pdf p1 lower half: E_A_LSUUN1 at cavity 70 -> CJ120 S1071 UN; "
         "ME7.5 C2-2 E_AN_LSUUN1 = 70; family workbook LS1VK_S = 70"),
    51: ("LSU bank 1 VM (virtual ground) -> CJ120 S1071",
         PinCap.SPECIAL_LOCKED, "CJ120 bank 1 VM",
         "me711.pdf: M_R_LSUVM1 at 51; ME7.5 C2-2 = 51; workbook LS1VK_MA = 51"),
    71: ("LSU bank 1 IA (trim) -> CJ120 S1071",
         PinCap.SPECIAL_LOCKED, "CJ120 bank 1 IA",
         "me711.pdf: E_A_LSUIA1 at 71; ME7.5 C2-2 = 71; workbook LS1VK_IA = 71"),
    52: ("LSU bank 1 IP (pump current, R1070 61.9 ohm) -> CJ120 S1071",
         PinCap.SPECIAL_LOCKED, "CJ120 bank 1 IP",
         "me711.pdf: E_A_LSUIP1 at 52; ME7.5 C2-2 = 52; workbook LS1VK_IP = 52"),
    13: ("LSU bank 2 UN (Nernst cell) -> CJ120 S1051",
         PinCap.SPECIAL_LOCKED, "CJ120 bank 2 UN",
         "me711.pdf: E_A_LSUUN2 at 13; family workbook LS2VK_S = 13"),
    12: ("LSU bank 2 VM (virtual ground) -> CJ120 S1051",
         PinCap.SPECIAL_LOCKED, "CJ120 bank 2 VM",
         "me711.pdf: M_R_LSUVM2 at 12; family workbook LS2VK_MA = 12"),
    14: ("LSU bank 2 IA (trim) -> CJ120 S1051",
         PinCap.SPECIAL_LOCKED, "CJ120 bank 2 IA",
         "me711.pdf: E_A_LSUIA2 at 14; family workbook LS2VK_IA = 14"),
    15: ("LSU bank 2 IP (pump current, R1050 61.9 ohm) -> CJ120 S1051",
         PinCap.SPECIAL_LOCKED, "CJ120 bank 2 IP",
         "me711.pdf: E_A_LSUIP2 at 15; family workbook LS2VK_IP = 15"),
    5:  ("LSU heater bank 1 pre-cat, low side (BUK138-50 T7000, gate ASIC "
         "P8.7) - driven by the lambda function, not a free output",
         PinCap.SPECIAL_LOCKED, "ASIC P8.7 LSH1VK via frame word 58",
         "me711.pdf: A_S_LSH1VK at 5, gate LSH1VK_PX87, CJ120 DIAHD/DIAHG "
         "watch it; ME7.5 C2-2 A_S_LSHVK = 5. NOT P5.6/AN6: that is the "
         "CJ120 UA line LS1VK_PA56, internal, no cavity"),
    4:  ("LSU heater bank 2 pre-cat, low side (BUK138-50 T7030, gate ASIC "
         "P7.4) - driven by the lambda function, not a free output",
         PinCap.SPECIAL_LOCKED, "ASIC P7.4 LSH2VK via frame word 58",
         "me711.pdf: A_S_LSH2VK at 4, gate LSH2VK_PX74. NOT P5.4/AN4: that "
         "is the CJ120 UA line LS2VK_PA54, internal, no cavity"),
    # V95: 18 AND 22 ARE LOCKED. The sheet draws A_S_ZAS2 / A_S_ZAS1 (CJ420
    # stages) on them, and on the W12 drawing the stages' inputs are P8.2 /
    # P8.1. On THIS board those two CPU pins are the CJ120 chip selects
    # (RESERVED_CPU_PINS: the OEM binary toggles them around every CJ120
    # transfer, HaniCore's own CJ120 driver selects the chips with them on the
    # bench) and the exact-target A2L says SY_ZAS = 0 and SY_CJ120 = 2 - the
    # Porsche is the variant WITHOUT cylinder shut-off and WITH two wideband
    # ICs, which is what the port map's "C-Muster CS_CJ120/ZAS1" column says.
    # No CPU pin drives whatever stage sits behind these cavities (population
    # unmeasured), so they are offered to nothing. Until V95 they were
    # RELAY_OUT | LOW_SIDE: a relay or tacho routed here validated and drove
    # nothing - one HAL case away from a wideband chip select.
    18: ("ZAS2 on the W12 sheet - NOT DRIVABLE on this board: its CPU pin "
         "P8.2 is the CJ120 bank-2 chip select",
         PinCap.SPECIAL_LOCKED, "",
         "me711.pdf: A_S_ZAS2 at cavity 18, input P8.2 on the W12 drawing; "
         "on the Porsche P8.2 is the CJ120 chip select (EXACT TARGET BINARY "
         "0x8C0756/0x8C079C; PHYSICAL EXACT: CJ120 INIT/IDENT/DIAG through "
         "it, V85); A2L SY_ZAS = 0. Locked, no resource"),
    19: ("EV8 - Einspritzventil 8", PinCap.INJ_OUT | PinCap.LOW_SIDE,
         "P8.3/CC19IO",
         "me711.pdf: A_T_EV8 at cavity 19 - NOT cavity 23, which the ME7.1 C4 "
         "family workbook claimed and which is the main relay. Port map row "
         "75: MAIN P8.3/CC19IO = EV8, BOTH ME7.1.1 columns agree"),
    22: ("ZAS1 on the W12 sheet - NOT DRIVABLE on this board: its CPU pin "
         "P8.1 is the CJ120 bank-1 chip select",
         PinCap.SPECIAL_LOCKED, "",
         "me711.pdf: A_S_ZAS1 at cavity 22, input P8.1 on the W12 drawing; "
         "port map C-Muster column CS_CJ120/ZAS1; on the Porsche P8.1 is the "
         "CJ120 chip select (EXACT TARGET BINARY 0x8C075A/0x8C07A0; PHYSICAL "
         "EXACT: CJ120 INIT/IDENT/DIAG through it, V85); A2L SY_ZAS = 0. "
         "Locked, no resource"),
    24: ("EV7 - Einspritzventil 7", PinCap.INJ_OUT | PinCap.LOW_SIDE,
         "P8.4/CC20IO",
         "me711.pdf: A_T_EV7 at cavity 24 - the one cavity in this block the "
         "family workbook got right. Port map row 76: MAIN P8.4/CC20IO = EV7, "
         "BOTH ME7.1.1 columns agree"),

    # ---- and two analog cavities the family workbook resolved WRONGLY ------
    # V86: "ASIC Pn.m/ANk" IS A RESOURCE. The generator encodes it as
    # HC_ADC_ASIC(k) (0xE0 + k), hc_route binds it, and the ME7.1.1 HAL reads
    # that ASIC channel out of the S5500 window - only when the ADC's own
    # channel tag matches. Before V86 these two cavities had resource "" and
    # were UNROUTABLE, so the validator refused pinClt = 93 / pinIat = 26
    # while the HAL read exactly those cavities anyway.
    26: ("TANS - Ansauglufttemperatur, on the PERIPHERAL ASIC",
         PinCap.AIN, "ASIC P5.1/AN1",
         "me711.pdf: cavity 26 is E_A_TANS and its net is TANS_PXA51 - the "
         "ASIC. The main CPU's own analog block on the same sheet reads "
         "UBAT_PA55 on AN5, an INTERNAL RAIL WITH NO CONNECTOR CAVITY. The "
         "family workbook lists cavity 26 as TAN_S|UBE_S and the generator's "
         "'prefer a concrete main-CPU resource' rule resolved UBE -> UBAT -> "
         "AN5, which is the wrong variant for this board. Port map rows 177/178 "
         "agree: TMOT and TANS are ASIC P5.0/AN0 and P5.1/AN1, 'Port nur "
         "Input'. Battery sense therefore has NO cavity and belongs to the "
         "HAL's own TGT_ADC_BATT_CH"),
    93: ("TMOT - Motortemperatur, on the PERIPHERAL ASIC", PinCap.AIN,
         "ASIC P5.0/AN0",
         "me711.pdf: cavity 93 is E_A_TMOT into N1100 and its net is "
         "TMOT_PXA50 - the ASIC's AN0 (bench measurement"
         "p1_cav93_26.png). Port map rows 177/178: TMOT = ASIC P5.0/AN0. "
         "Read by the HAL from S5500 window w00, tag-checked, since V78"),
    29: ("HFM - Heissfilmluftmassenmesser", PinCap.AIN | PinCap.FREQ_IN,
         "P5.0/AN0",
         "me711.pdf: cavity 29 is E_A_HFM, and the main CPU analog block reads "
         "HFM_PA50 on AN0. Port map: MAIN P5.0/AN0 = HFM/P (B) / HFM (C) - the "
         "variants differ only in a suffix. The air-mass input IS on this CPU "
         "on this board; the descriptor previously had it unroutable"),
    101: ("PLADE / DSS - charge or manifold PRESSURE", PinCap.AIN,
          "P5.14/AN14",
          "me711.pdf: cavity 101 is drawn E_A_PLADE with E_A_DSS(PSR) beneath "
          "it, and the main CPU analog block reads DSS_PA514 on AN14. The port "
          "map's two ME7.1.1 columns disagree (TAGR vs DSS) and the sheet "
          "settles it as DSS, a PRESSURE input. WHICH pressure - manifold or "
          "post-intercooler - is NOT settled, and the exact-target A2L says "
          "SY_TURBO = 1, so the distinction matters to a speed-density model"),
    # V97: the cam solenoid stages the V82 bench test already drives - the
    # MAIN CPU's own PWM pins through CJ920 low sides with freewheel diodes.
    115: ("KNWS1 - cam timing valve 1 (AWT N205 lands here)",
          PinCap.LOW_SIDE | PinCap.PWM_OUT, "P7.0/POUT0",
          "me711.pdf p1: MAIN P7.0/POUT0 net KNWS1_P70 -> S6600 (CJ920, 2.2 A) "
          "OUT 6/7 -> cavity 115, freewheel BYG22D D6600; OEM key-on PWM init "
          "[BIN 0x8C0D78] 250 Hz; port map MAIN P7.0 POUT0 = NWS1 / KNWS1"),
    120: ("KNWS2 - cam timing valve 2", PinCap.LOW_SIDE | PinCap.PWM_OUT,
          "P7.1/POUT1",
          "me711.pdf p1: MAIN P7.1/POUT1 net KNWS2_P71 -> CJ920 OUT 50/51 -> "
          "cavity 120; the family workbook leaves 120 blank (a known error "
          "row)"),
}


def _apply_me711_sheet(d: "HwDescriptor") -> None:
    """Override the family workbook where the ME7.1.1 sheet itself was read.

    Runs AFTER _apply_porsche_truth, so it also lifts the 18..24 lock for the
    four cavities the sheet names. Cavity 20 is NOT named there and stays
    locked; cavities 21 and 23 keep their _PORSCHE_TRUTH entries, which carry a
    PHYSICAL measurement this sheet cannot beat."""
    for n, (meaning, cap, hal, why) in _ME711_SHEET.items():
        old = d.pin(n)
        d.pins[n - 1] = PhysicalPin(
            n, old.oem_name, meaning,
            (PinProperty(cap, EvidenceClass.PROBABLE,
                         "ME7.1.1 SHEET LAYER, me711.pdf at 330 dpi: " + why),),
            hal,
            # PROBABLE EITHER WAY. The first version rated a cavity with NO CPU
            # resource as VERIFIED - "verified to be on nothing" - which reads
            # as a stronger claim than the sheet supports and tripped
            # test_no_me711_connector_claim_is_rated_verified. This is a
            # same-generation W12 drawing, not this board; nothing it says is
            # VERIFIED for the Porsche.
            EvidenceClass.PROBABLE,
            "ME7.1.1 SHEET LAYER: " + why)


# --------------------------------------------------------------------------
# ME7.5 4B0906018DC - typed, but ONLY from the maintainer's design notes,
# which states plainly that it outranks every earlier pin table on this board
# and names the three sources it reconciles. Every row below quotes it.
#
# Pins that document does not name are left with NO capabilities. This board's
# connector is physically the same 121-pin SKE shell, but a pin's function on
# THIS loom is a different claim from its function on the ME7.1 drawing, and
# the two are not interchangeable - which is the whole reason this file has two
# descriptors.
# --------------------------------------------------------------------------
_ME75_SRC = "ME7.5-archive/HANICORE_ENGINE_IO_MAP.md"
V = EvidenceClass.VERIFIED
P = EvidenceClass.PROBABLE

_ME75_ROWS: list[tuple[int, str, int, EvidenceClass, str, str]] = [
    # (pin, oem name, caps, evidence, hal resource, note)
    (82, "G28+ crank", PinCap.VR_IN | PinCap.FREQ_IN | PinCap.SPECIAL_LOCKED, V,
     "P2.15/CC15", "differential inductive via the CJ910; NBM is the clean tooth signal"),
    (90, "G28- crank", PinCap.VR_IN | PinCap.SPECIAL_LOCKED, V, "CJ910", "crank return"),
    (86, "G40 cam", PinCap.HALL_IN | PinCap.FREQ_IN, V, "P2.8/CC8",
     "sensor takes +5 V from D141, not from the ECU pin"),
    (29, "G70 air mass", PinCap.AIN | PinCap.FREQ_IN, P, "DISPUTED",
     "AN0 per the schematic vs CC17 frequency per Pinout.xlsx - unresolved, and "
     "the IO map says so explicitly"),
    (101, "G31 charge air pressure", PinCap.AIN, V, "P5.14/AN14", "Bosch generic name TAGR"),
    (93, "G62 coolant", PinCap.AIN, V, "P5.10/AN10", "TMOT_P510"),
    (85, "G42 intake air", PinCap.AIN | PinCap.SPECIAL_LOCKED, V, "ASIC PXAN1",
     "the one engine sensor NOT on the C167 ADC"),
    (17, "TMOT2 spare temperature", PinCap.AIN, V, "P5.13/AN13",
     "a spare temperature input this car does not use; iatChannel=13 moves IAT here"),
    (26, "battery", PinCap.AIN | PinCap.SPECIAL_LOCKED, V, "P5.5/AN5", ""),
    (106, "G66 knock 2", PinCap.AIN | PinCap.SPECIAL_LOCKED, V, "P5.15/AN15", "via the knock IC"),
    (107, "G61 knock 1", PinCap.AIN | PinCap.SPECIAL_LOCKED, V, "P5.15/AN15", "via the knock IC"),
    (92, "J338 p1 throttle 1", PinCap.AIN, V, "P5.1/AN1", "generic name IP1S"),
    (84, "J338 p4 throttle 2", PinCap.AIN, V, "P5.3/AN3", "generic name IP2S; opposing slope"),
    (35, "G79 pedal 1", PinCap.AIN, V, "P5.8/AN8", "generic name SP1S; also ASIC PXAN7"),
    (34, "G185 pedal 2", PinCap.AIN, V, "P5.9/AN9", "generic name SP2S"),
    (117, "throttle motor +", PinCap.DBW_HBRIDGE | PinCap.SPECIAL_LOCKED, V, "P7.2/DVE1",
     "into the CJ220 H-bridge; the bridge does nothing without EGENFR on P2.11"),
    (118, "throttle motor -", PinCap.DBW_HBRIDGE | PinCap.SPECIAL_LOCKED, V, "P7.7/DVE2", ""),
    (98, "5 V sensor supply", PinCap.SPECIAL_LOCKED, V, "", "feeds pedal, cam, MAF, charge-air"),
    (53, "5 V sensor supply", PinCap.SPECIAL_LOCKED, V, "", "MAF supply per the MAF row"),
    (27, "MAF ground", PinCap.SPECIAL_LOCKED, V, "", ""),
    (102, "N70 coil, firing index 1", PinCap.IGN_OUT, V, "P2.0/CC0", "CK110 E1->Z1"),
    (103, "N291 coil, firing index 2", PinCap.IGN_OUT, V, "P2.1/CC1", "CK110 E2->Z2"),
    (94, "N292 coil, firing index 3", PinCap.IGN_OUT, V, "P2.2/CC2", "CK110 E3->Z3"),
    (95, "N127 coil, firing index 4", PinCap.IGN_OUT, V, "P2.3/CC3", "CK110 E4->Z4"),
    (96, "N30 injector, firing index 1", PinCap.INJ_OUT | PinCap.LOW_SIDE, V,
     "P7.6/CC30", "CJ920 E1->A1"),
    (97, "N32 injector, firing index 2", PinCap.INJ_OUT | PinCap.LOW_SIDE, V,
     "P7.5/CC29", "CJ920 E2->A2"),
    (88, "N33 injector, firing index 3", PinCap.INJ_OUT | PinCap.LOW_SIDE, V,
     "P7.4/CC28", "CJ920 E3->A3"),
    (89, "N31 injector, firing index 4", PinCap.INJ_OUT | PinCap.LOW_SIDE, V,
     "P8.7/CC23", "CJ920 E4->A4"),
    (21, "J271 main relay", PinCap.RELAY_OUT | PinCap.SPECIAL_LOCKED, V, "CJ910 HR",
     "'via the ASIC/KL15 path' - not a CPU port pin, so it is not freely assignable"),
    (65, "fuel pump relay", PinCap.LOW_SIDE | PinCap.RELAY_OUT, V, "P3.7/EKPR", ""),
    (64, "TEV tank vent", PinCap.LOW_SIDE | PinCap.PWM_OUT, V, "P7.3", ""),
    (104, "LDR/SU boost valve", PinCap.LOW_SIDE | PinCap.PWM_OUT, V, "P7.1/POUT1",
     "drive polarity NOT known - calibratable as pwmInvert"),
    (116, "ETR secondary air", PinCap.LOW_SIDE | PinCap.PWM_OUT, V, "P2.7", ""),
    (5, "LSHVK O2 heater pre-cat", PinCap.LOW_SIDE | PinCap.PWM_OUT, V, "P2.12", ""),
    (63, "LSHHK O2 heater post-cat", PinCap.LOW_SIDE | PinCap.PWM_OUT, V, "P2.4", ""),
    (115, "N205 cam adjust valve", PinCap.LOW_SIDE | PinCap.PWM_OUT, P, "",
     "the IO map names the connector pin but no CPU resource"),
    (47, "MIL lamp", PinCap.LOW_SIDE, V, "ASIC PXO3", ""),
]


def build_me75() -> HwDescriptor:
    d = HwDescriptor(
        "ME75_4B0906018DC",
        "VAG ME7.5 4B0906018DC (1.8T AWT bench board)",
        "121-pin SKE; pin functions per docs/HANICORE_ENGINE_IO_MAP.md",
    )
    rows = {r[0]: r for r in _ME75_ROWS}
    for n in range(1, PIN_COUNT + 1):
        r = rows.get(n)
        if r is None:
            d.pins.append(PhysicalPin(n))
            continue
        _, oem, caps, ev, hal, note = r
        src = "%s: %s%s" % (_ME75_SRC, oem, (" - " + note) if note else "")
        d.pins.append(PhysicalPin(n, oem, note, (PinProperty(caps, ev, src),),
                                  hal, ev, _ME75_SRC if hal else ""))
    assert len(d.pins) == PIN_COUNT
    return d


DESCRIPTORS = {"BOSCH_ME711": build_me711, "ME75_4B0906018DC": build_me75}

_CAP_NAMES = [
    (PinCap.AIN, "AIN"), (PinCap.DIN, "DIN"), (PinCap.FREQ_IN, "FREQ_IN"),
    (PinCap.VR_IN, "VR_IN"), (PinCap.HALL_IN, "HALL_IN"),
    (PinCap.LOW_SIDE, "LOW_SIDE"), (PinCap.PWM_OUT, "PWM_OUT"),
    (PinCap.INJ_OUT, "INJ_OUT"), (PinCap.IGN_OUT, "IGN_OUT"),
    (PinCap.DBW_HBRIDGE, "DBW_HBRIDGE"), (PinCap.RELAY_OUT, "RELAY_OUT"),
    (PinCap.SPECIAL_LOCKED, "SPECIAL_LOCKED"),
]


def cap_names(mask: int) -> str:
    return "|".join(n for b, n in _CAP_NAMES if mask & b) or "-"


def write_csv(d: HwDescriptor) -> Path:
    out = OUT_DIR / ("hc_hw_descriptor_%s.csv" % d.target_id.lower())
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["pin", "oem_name", "capabilities", "evidence_per_cap",
                     "hal_resource", "hal_evidence", "source"])
        for p in d.pins:
            wr.writerow([
                p.number, p.oem_name, cap_names(p.capabilities),
                ";".join("%s=%s" % (cap_names(pr.cap), pr.evidence.value)
                         for pr in p.properties),
                p.hal_resource, p.hal_evidence.value if p.hal_resource else "",
                " ;; ".join(pr.source for pr in p.properties) or p.hal_source,
            ])
    return out


def main() -> int:
    want_csv = "--csv" in sys.argv
    for key, fn in DESCRIPTORS.items():
        d = fn()
        assigned = sum(1 for p in d.pins if p.capabilities)
        verified = sum(1 for p in d.pins if p.caps_at_least(EvidenceClass.VERIFIED))
        print("%s: %s" % (key, d.name))
        print("    pins with any capability : %d/%d" % (assigned, PIN_COUNT))
        print("    pins with VERIFIED caps  : %d/%d" % (verified, PIN_COUNT))
        print("    pins with a HAL resource : %d"
              % sum(1 for p in d.pins if p.hal_resource))
        if want_csv:
            print("    wrote %s" % write_csv(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
