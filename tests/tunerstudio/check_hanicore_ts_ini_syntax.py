#!/usr/bin/env python3
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# The live .ini. Until 2026-10 the default was generated/hanicore_tunerstudio_draft.ini,
# the output of an abandoned draft generator - so Tier 1 ran this check on a file
# TunerStudio never loads.
INI = ROOT / "tunerstudio" / "hanicore_me711.ini"
SUPPORTED_TYPES = {"U08": 1, "S08": 1, "U16": 2, "S16": 2, "U32": 4, "S32": 4, "F32": 4}
VALID_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SECTION_RE = re.compile(r"^\[[A-Za-z0-9_]+\]$")


def split_csv(row):
    fields = []
    current = []
    in_quote = False
    for char in row:
        if char == '"':
            in_quote = not in_quote
        if char == "," and not in_quote:
            fields.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    fields.append("".join(current).strip())
    return fields


def validate_scalar(line_no, name, value, och_block_size=None):
    errors = []
    if not VALID_NAME_RE.fullmatch(name):
        return [f"line {line_no}: invalid scalar name"]
    fields = split_csv(value)
    if len(fields) < 6:
        return [f"line {line_no}: scalar row has too few fields"]
    if fields[0] != "scalar":
        return [f"line {line_no}: only scalar rows are supported here"]
    dtype = fields[1]
    if dtype not in SUPPORTED_TYPES:
        return [f"line {line_no}: unsupported type {dtype}"]
    try:
        offset = int(fields[2])
    except ValueError:
        return [f"line {line_no}: invalid offset"]
    if len(fields[3]) < 2 or not (fields[3].startswith('"') and fields[3].endswith('"')):
        errors.append(f"line {line_no}: units must be quoted")
    try:
        float(fields[4])
        float(fields[5])
    except ValueError:
        errors.append(f"line {line_no}: invalid scale/translate")
    if och_block_size is not None and offset + SUPPORTED_TYPES[dtype] > och_block_size:
        errors.append(f"line {line_no}: offset outside ochBlockSize")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("ini", nargs="?", type=Path, default=INI,
                        help="INI to validate (default: tunerstudio/hanicore_me711.ini)")
    parser.add_argument("--debug", action="store_true", help="print parsed section and row line numbers")
    args = parser.parse_args(argv)
    ini_path = args.ini if args.ini.is_absolute() else ROOT / args.ini

    if not ini_path.is_file():
        print(f"missing INI: {ini_path}")
        return 1

    errors = []
    section = None
    och_block_size = None
    channels = {}
    gauge_configs = {}
    front_page_gauges = {}
    megatune_values = {}
    tunerstudio_values = {}
    output_values = {}
    constants_values = {}

    for line_no, raw in enumerate(ini_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("["):
            if not SECTION_RE.fullmatch(line):
                errors.append(f"line {line_no}: malformed section header")
            section = line.strip("[]")
            if args.debug:
                print(f"line {line_no}: section [{section}]")
            continue
        if "=" not in line:
            errors.append(f"line {line_no}: row missing '='")
            continue

        name, value = [part.strip() for part in line.split("=", 1)]
        value = value.split(";", 1)[0].strip()
        if not name:
            errors.append(f"line {line_no}: empty field name")
            continue

        if section == "OutputChannels":
            if args.debug:
                print(f"line {line_no}: OutputChannels row {name}")
            if name == "ochBlockSize":
                try:
                    och_block_size = int(value)
                except ValueError:
                    errors.append(f"line {line_no}: invalid ochBlockSize")
                continue
            if name == "ochGetCommand":
                if not (value.startswith('"') and value.endswith('"')):
                    errors.append(f"line {line_no}: ochGetCommand must be quoted")
                output_values[name] = value
                continue
            if name in channels:
                errors.append(f"line {line_no}: duplicate OutputChannels name {name}")
                continue
            if value.startswith("{") and value.endswith("}"):
                channels[name] = (-1, 0)
                continue
            row_errors = validate_scalar(line_no, name, value)
            if row_errors:
                errors.extend(row_errors)
                continue
            fields = split_csv(value)
            dtype = fields[1]
            offset = int(fields[2])
            channels[name] = (offset, SUPPORTED_TYPES[dtype])
        elif section == "Constants":
            constants_values[name] = value
            if args.debug:
                print(f"line {line_no}: Constants row {name}")
            if "scalar," in value:
                fields = split_csv(value)
                if len(fields) < 9:
                    errors.append(f"line {line_no}: Constants scalar row has too few fields")
                errors.extend(validate_scalar(line_no, name, value))
        elif section == "TunerStudio":
            tunerstudio_values[name] = value
        elif section == "MegaTune":
            megatune_values[name] = value
        elif section == "GaugeConfigurations":
            if args.debug:
                print(f"line {line_no}: GaugeConfigurations row {name}")
            if name == "gaugeCategory":
                continue
            fields = split_csv(value)
            if len(fields) < 11:
                errors.append(f"line {line_no}: gauge row has too few fields")
                continue
            if not VALID_NAME_RE.fullmatch(name):
                errors.append(f"line {line_no}: invalid gauge name")
            if not VALID_NAME_RE.fullmatch(fields[0]):
                errors.append(f"line {line_no}: invalid gauge variable")
            if name in gauge_configs:
                errors.append(f"line {line_no}: duplicate gauge config {name}")
            gauge_configs[name] = fields[0]
        elif section == "FrontPage":
            if args.debug:
                print(f"line {line_no}: FrontPage row {name}")
            if re.fullmatch(r"gauge[1-8]", name):
                if not VALID_NAME_RE.fullmatch(value):
                    errors.append(f"line {line_no}: invalid FrontPage gauge reference")
                front_page_gauges[name] = value

    if och_block_size is None:
        errors.append("missing [OutputChannels] ochBlockSize")
    elif och_block_size <= 0:
        errors.append("ochBlockSize must be positive")

    if och_block_size:
        offsets = set()
        for name, (offset, size) in channels.items():
            if size == 0:
                continue
            if offset < 0 or offset + size > och_block_size:
                errors.append(f"{name}: offset outside ochBlockSize")
            if offset in offsets:
                errors.append(f"{name}: duplicate binary offset")
            offsets.add(offset)

    if "iniSpecVersion" not in tunerstudio_values:
        errors.append("[TunerStudio] missing iniSpecVersion")
    if tunerstudio_values.get("queryCommand") != '"S"':
        errors.append('[TunerStudio] queryCommand must be "S"')
    if tunerstudio_values.get("versionInfo") != '"V"':
        errors.append('[TunerStudio] versionInfo must be "V"')
    if "signature" not in tunerstudio_values:
        errors.append("[TunerStudio] missing signature")
    elif len(tunerstudio_values["signature"].strip('"')) < 7:
        errors.append("[TunerStudio] signature must be at least 7 characters")
    if output_values.get("ochGetCommand") != '"O%2o%2c"':
        errors.append('[OutputChannels] ochGetCommand must be "O%2o%2c"')
    if constants_values.get("messageEnvelopeFormat") != "msEnvelope_1.0":
        errors.append("[Constants] messageEnvelopeFormat must be msEnvelope_1.0")

    for gauge_name, channel_name in gauge_configs.items():
        if channel_name not in channels:
            errors.append(f"GaugeConfigurations {gauge_name}: unknown OutputChannels variable {channel_name}")

    for index in range(1, 9):
        key = f"gauge{index}"
        if key not in front_page_gauges:
            errors.append(f"FrontPage missing {key}")
            continue
        if front_page_gauges[key] not in gauge_configs:
            errors.append(f"FrontPage {key}: unknown gauge config {front_page_gauges[key]}")

    if errors:
        for error in errors:
            print(error)
        return 1

    print(f"HaniCore TunerStudio INI syntax check passed: {len(channels)} channels")
    return 0


if __name__ == "__main__":
    sys.exit(main())
