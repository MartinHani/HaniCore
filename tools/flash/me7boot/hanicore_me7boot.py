#!/usr/bin/env python3
"""
HaniCore ME7 Bootmode CLI wrapper for EcuProg7/C167BootTool.

Windows-oriented, non-interactive wrapper around ME7BootTool.py.
It selects an explicit COM port, supports ME7 external flash read/write,
supports sector-aware diffWrite, and can optionally perform a full readback SHA-256 verification.

The upstream C167BootTool project remains unmodified and must be present
next to this file (or supplied with --tool).
"""

from __future__ import annotations

import argparse
import builtins
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import traceback

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_SETUP = 10
EXIT_TOOL_FAILED = 20
EXIT_VERIFY_MISMATCH = 21

DEFAULT_BAUD = 57600
DEFAULT_READ_SIZE = 0x100000  # HaniCore/Porsche ME7.1.1 = AM29F800, 1 MiB
VALID_FULL_FLASH_SIZES = {0x80000, 0x100000}  # 29F400 / 29F800


class NonInteractivePrompt(RuntimeError):
    pass


def parse_int(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid integer '{value}' (use decimal or e.g. 0x100000)"
        ) from exc


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_default_tool(wrapper_dir: Path) -> Path:
    candidates = [
        wrapper_dir / "ME7BootTool.py",
        wrapper_dir / "C167BootTool" / "ME7BootTool.py",
        wrapper_dir.parent / "C167BootTool" / "ME7BootTool.py",
    ]
    for p in candidates:
        if p.is_file():
            return p.resolve()
    return candidates[0].resolve()


def check_upstream_layout(tool: Path, needs_flash_driver: bool) -> list[str]:
    base = tool.parent
    required = [
        base / "Minimon" / "LOADK.bin",
        base / "Minimon" / "MINIMONK.bin",
    ]
    if needs_flash_driver:
        required.append(base / "Drivers" / "FX00Bx_Driver.bin")
    return [str(p) for p in required if not p.is_file()]


def import_pyserial():
    try:
        import serial  # type: ignore
        import serial.tools.list_ports  # type: ignore
        return serial
    except ImportError as exc:
        print("ERROR: pyserial is not installed.", file=sys.stderr)
        print("Install it with:  py -m pip install pyserial", file=sys.stderr)
        raise SystemExit(EXIT_SETUP) from exc


def normalize_com_port(port: str) -> str:
    p = port.strip()
    if not p:
        raise ValueError("empty COM port")
    # pyserial accepts COM3 directly. For COM10+ it also handles the name,
    # so keep the user-facing form unchanged.
    return p.upper() if p.lower().startswith("com") else p


def upstream_args_for_read(baud: int, size: int, output: Path) -> list[str]:
    return [str(baud), "-readextflash", hex(size), str(output)]


def upstream_args_for_write(baud: int, image: Path) -> list[str]:
    return [str(baud), "-writeextflash", str(image), "me7"]


def run_upstream(tool: Path, port: str, upstream_args: list[str], extra_env: dict[str, str] | None = None) -> int:
    """Run upstream ME7BootTool.py with its USB-port discovery forced to one COM port."""
    serial = import_pyserial()
    list_ports = serial.tools.list_ports

    old_argv = sys.argv[:]
    old_grep = list_ports.grep
    old_input = builtins.input
    old_env: dict[str, str | None] = {}

    class ForcedPort:
        def __init__(self, device: str):
            self.device = device

        def __str__(self) -> str:
            return self.device

    fake_port = ForcedPort(port)

    def forced_grep(_pattern):
        return iter([fake_port])

    def no_input(prompt: str = ""):
        raise NonInteractivePrompt(
            f"Upstream tool requested interactive input: {prompt.strip()}"
        )

    list_ports.grep = forced_grep
    builtins.input = no_input
    sys.argv = [str(tool)] + upstream_args
    if extra_env:
        for key, value in extra_env.items():
            old_env[key] = os.environ.get(key)
            os.environ[key] = value

    try:
        result = runpy.run_path(str(tool), run_name="__main__")
        exitt = result.get("exitt", 0)
        try:
            return int(exitt)
        except Exception:
            return EXIT_TOOL_FAILED
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return EXIT_TOOL_FAILED
    except BaseException:
        traceback.print_exc()
        return EXIT_TOOL_FAILED
    finally:
        sys.argv = old_argv
        list_ports.grep = old_grep
        builtins.input = old_input
        for key, old_value in old_env.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def ensure_output_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def emit_result(args, status: str, **extra) -> None:
    data = {"status": status, **extra}
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
    else:
        fields = " ".join(f"{k}={v}" for k, v in extra.items())
        print(f"HC_ME7BOOT_RESULT={status}" + (f" {fields}" if fields else ""))


def cmd_ports(args) -> int:
    serial = import_pyserial()
    ports = list(serial.tools.list_ports.comports())
    if args.json:
        print(json.dumps([
            {
                "device": p.device,
                "description": getattr(p, "description", ""),
                "hwid": getattr(p, "hwid", ""),
            }
            for p in ports
        ], indent=2))
    else:
        if not ports:
            print("No serial ports found.")
        for p in ports:
            print(f"{p.device:8}  {getattr(p, 'description', '')}  {getattr(p, 'hwid', '')}")
    return EXIT_OK


def cmd_read(args, tool: Path, port: str) -> int:
    output = Path(args.output).expanduser().resolve()
    ensure_output_parent(output)
    missing = check_upstream_layout(tool, needs_flash_driver=False)
    if missing:
        print("ERROR: upstream C167BootTool files are missing:", file=sys.stderr)
        for p in missing:
            print(f"  {p}", file=sys.stderr)
        return EXIT_SETUP

    print(f"READ  port={port} baud={args.baud} size=0x{args.size:X} -> {output}")
    rc = run_upstream(tool, port, upstream_args_for_read(args.baud, args.size, output))
    # Upstream uses exitt=1 for normal completion (not a process-style success code).
    # For reads, the reliable success criterion is a complete output file.
    if not output.is_file() or output.stat().st_size != args.size:
        actual = output.stat().st_size if output.is_file() else -1
        print(f"ERROR: read size mismatch: expected {args.size}, got {actual}", file=sys.stderr)
        emit_result(args, "FAIL", operation="read", code="SIZE_MISMATCH", upstream_state=rc)
        return EXIT_TOOL_FAILED

    digest = sha256_file(output)
    emit_result(args, "PASS", operation="read", bytes=args.size, sha256=digest, file=str(output))
    return EXIT_OK


def validate_image_size(image: Path, allow_partial: bool) -> tuple[bool, int]:
    size = image.stat().st_size
    if allow_partial:
        return True, size
    return size in VALID_FULL_FLASH_SIZES, size


DIFF_BLOCK_SIZE = 0x200  # upstream flash-program block size


def changed_block_indices(current: Path, image: Path, block_size: int = DIFF_BLOCK_SIZE) -> list[int]:
    changed: list[int] = []
    with current.open("rb") as a, image.open("rb") as b:
        index = 0
        while True:
            ca = a.read(block_size)
            cb = b.read(block_size)
            if not ca and not cb:
                break
            if ca != cb:
                changed.append(index)
            index += 1
    return changed


def make_diff_patched_tool(tool: Path) -> Path:
    """Create a temporary upstream copy that erases/programs only sectors containing changed blocks."""
    source = tool.read_text(encoding="utf-8", errors="strict")

    erase_init = """        sector = 0;\n        sectorSize = 0;\n        while (offset < size):\n"""
    erase_init_repl = """        sector = 0;\n        sectorSize = 0;\n        _hc_diff_blocks_raw = os.environ.get(\"HANICORE_DIFF_BLOCKS\", \"\")\n        _hc_changed_blocks = {int(x) for x in _hc_diff_blocks_raw.split(\",\") if x}\n        _hc_changed_ranges = []\n        while (offset < size):\n"""
    if erase_init not in source:
        raise RuntimeError("upstream patch failed: erase-loop marker not found")
    source = source.replace(erase_init, erase_init_repl, 1)

    erase_call_marker = "            writeAddressHigh = ((writeAddressBase + offset) >>16) & 0xFFFF;\n"
    erase_guard = """            _hc_first_block = offset // BlockLength\n            _hc_last_block = (offset + sectorSize - 1) // BlockLength\n            _hc_sector_changed = any(b in _hc_changed_blocks for b in range(_hc_first_block, _hc_last_block + 1))\n            if not _hc_sector_changed:\n                sys.stdout.write(\"\\rDIFF skip unchanged sector \" + str(sector) + \" offset \" + hex(offset))\n                offset += sectorSize;\n                sector += 1;\n                continue\n            _hc_changed_ranges.append((offset, offset + sectorSize))\n\n""" + erase_call_marker
    pos = source.find(erase_call_marker, source.find(erase_init_repl))
    if pos < 0:
        raise RuntimeError("upstream patch failed: erase-call marker not found")
    source = source[:pos] + erase_guard + source[pos + len(erase_call_marker):]

    write_selector = """            write = False;\n            for e in blockData:\n                if(e != 0xff):\n                    write = True;\n"""
    write_selector_repl = """            write = False;\n            _hc_in_changed_sector = any(start <= offset < end for start, end in _hc_changed_ranges)\n            if _hc_in_changed_sector:\n                for e in blockData:\n                    if(e != 0xff):\n                        write = True;\n"""
    if write_selector not in source:
        raise RuntimeError("upstream patch failed: write-loop marker not found")
    source = source.replace(write_selector, write_selector_repl, 1)

    fd, name = tempfile.mkstemp(prefix="_hanicore_diff_", suffix=".py", dir=str(tool.parent))
    os.close(fd)
    patched = Path(name)
    patched.write_text(source, encoding="utf-8")
    return patched


def verify_image(args, tool: Path, port: str, image: Path, keep_path: Path | None = None) -> int:
    image_size = image.stat().st_size

    if keep_path is not None:
        verify_path = keep_path.resolve()
        ensure_output_parent(verify_path)
        cleanup = False
    else:
        fd, name = tempfile.mkstemp(prefix="hanicore_me7_verify_", suffix=".bin")
        os.close(fd)
        verify_path = Path(name)
        cleanup = True

    try:
        print(f"VERIFY readback: {image_size} bytes -> {verify_path}")
        rc = run_upstream(tool, port, upstream_args_for_read(args.baud, image_size, verify_path))
        # Upstream returns 1 both after a completed read and on some read-error paths,
        # so verify completeness by exact byte count instead of treating it as an exit code.
        if not verify_path.is_file() or verify_path.stat().st_size != image_size:
            got = verify_path.stat().st_size if verify_path.is_file() else -1
            print(f"ERROR: verify readback size mismatch: expected {image_size}, got {got}", file=sys.stderr)
            emit_result(args, "FAIL", operation="verify", code="SIZE_MISMATCH", upstream_state=rc)
            return EXIT_TOOL_FAILED

        expected_hash = sha256_file(image)
        actual_hash = sha256_file(verify_path)
        if expected_hash != actual_hash:
            print("ERROR: VERIFY MISMATCH", file=sys.stderr)
            print(f"  image   SHA256: {expected_hash}", file=sys.stderr)
            print(f"  readback SHA256: {actual_hash}", file=sys.stderr)
            emit_result(
                args,
                "FAIL",
                operation="verify",
                code="HASH_MISMATCH",
                expected_sha256=expected_hash,
                readback_sha256=actual_hash,
            )
            return EXIT_VERIFY_MISMATCH

        emit_result(
            args,
            "PASS",
            operation="verify",
            bytes=image_size,
            sha256=expected_hash,
        )
        return EXIT_OK
    finally:
        if cleanup:
            try:
                verify_path.unlink(missing_ok=True)
            except Exception:
                pass


def cmd_write(args, tool: Path, port: str) -> int:
    image = Path(args.image).expanduser().resolve()
    if not image.is_file():
        print(f"ERROR: image not found: {image}", file=sys.stderr)
        return EXIT_USAGE

    ok, size = validate_image_size(image, args.allow_partial)
    if not ok:
        print(
            f"ERROR: refusing ME7 write of {size} bytes. Expected a full 29F400 (0x80000) "
            f"or 29F800 (0x100000) image. Use --allow-partial only if intentional.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    missing = check_upstream_layout(tool, needs_flash_driver=True)
    if missing:
        print("ERROR: upstream C167BootTool files are missing:", file=sys.stderr)
        for p in missing:
            print(f"  {p}", file=sys.stderr)
        return EXIT_SETUP

    image_hash = sha256_file(image)
    print(f"WRITE port={port} baud={args.baud} bytes={size} image={image}")
    print(f"IMAGE SHA256: {image_hash}")
    rc = run_upstream(tool, port, upstream_args_for_write(args.baud, image))
    # For external-flash write, upstream returns 1 after the success message and
    # normally -1 on programming/erase/communication failures.
    if rc != 1:
        emit_result(args, "FAIL", operation="write", code=rc)
        return EXIT_TOOL_FAILED

    do_verify = bool(args.verify or args.verify_dump)
    if not do_verify:
        emit_result(args, "PASS", operation="write", bytes=size, sha256=image_hash, verified=False)
        return EXIT_OK

    keep = Path(args.verify_dump).expanduser() if args.verify_dump else None
    return verify_image(args, tool, port, image, keep)


def cmd_diff_write(args, tool: Path, port: str) -> int:
    image = Path(args.image).expanduser().resolve()
    if not image.is_file():
        print(f"ERROR: image not found: {image}", file=sys.stderr)
        return EXIT_USAGE

    ok, size = validate_image_size(image, False)
    if not ok:
        print(
            f"ERROR: diffWrite requires a full 29F400 (0x80000) or 29F800 (0x100000) image; got {size} bytes.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    missing = check_upstream_layout(tool, needs_flash_driver=True)
    if missing:
        print("ERROR: upstream C167BootTool files are missing:", file=sys.stderr)
        for p in missing:
            print(f"  {p}", file=sys.stderr)
        return EXIT_SETUP

    fd, current_name = tempfile.mkstemp(prefix="hanicore_me7_current_", suffix=".bin")
    os.close(fd)
    current = Path(current_name)
    patched_tool: Path | None = None

    try:
        print(f"DIFF READ port={port} baud={args.baud} bytes={size}")
        rc = run_upstream(tool, port, upstream_args_for_read(args.baud, size, current))
        if not current.is_file() or current.stat().st_size != size:
            got = current.stat().st_size if current.is_file() else -1
            print(f"ERROR: diff pre-read size mismatch: expected {size}, got {got}", file=sys.stderr)
            emit_result(args, "FAIL", operation="diffWrite", code="READ_SIZE_MISMATCH", upstream_state=rc)
            return EXIT_TOOL_FAILED

        changed = changed_block_indices(current, image)
        if not changed:
            digest = sha256_file(image)
            print("DIFF: ECU flash already matches image; nothing to write.")
            emit_result(args, "PASS", operation="diffWrite", changed_blocks=0, bytes_written=0, sha256=digest, verified=True)
            return EXIT_OK

        changed_bytes = len(changed) * DIFF_BLOCK_SIZE
        print(f"DIFF: {len(changed)} changed 0x{DIFF_BLOCK_SIZE:X}-byte blocks ({changed_bytes} bytes before sector expansion)")

        patched_tool = make_diff_patched_tool(tool)
        env = {"HANICORE_DIFF_BLOCKS": ",".join(str(i) for i in changed)}
        image_hash = sha256_file(image)
        print(f"diffWrite port={port} baud={args.baud} image={image}")
        rc = run_upstream(patched_tool, port, upstream_args_for_write(args.baud, image), extra_env=env)
        if rc != 1:
            emit_result(args, "FAIL", operation="diffWrite", code=rc, changed_blocks=len(changed))
            return EXIT_TOOL_FAILED

        do_verify = bool(args.verify or args.verify_dump)
        if not do_verify:
            emit_result(
                args, "PASS", operation="diffWrite", changed_blocks=len(changed),
                changed_block_bytes=changed_bytes, sha256=image_hash, verified=False
            )
            return EXIT_OK

        keep = Path(args.verify_dump).expanduser() if args.verify_dump else None
        return verify_image(args, tool, port, image, keep)
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        emit_result(args, "FAIL", operation="diffWrite", code="PATCH_ERROR")
        return EXIT_SETUP
    finally:
        try:
            current.unlink(missing_ok=True)
        except Exception:
            pass
        if patched_tool is not None:
            try:
                patched_tool.unlink(missing_ok=True)
            except Exception:
                pass


def cmd_verify(args, tool: Path, port: str) -> int:
    image = Path(args.image).expanduser().resolve()
    if not image.is_file():
        print(f"ERROR: image not found: {image}", file=sys.stderr)
        return EXIT_USAGE

    missing = check_upstream_layout(tool, needs_flash_driver=False)
    if missing:
        print("ERROR: upstream C167BootTool files are missing:", file=sys.stderr)
        for p in missing:
            print(f"  {p}", file=sys.stderr)
        return EXIT_SETUP

    keep = Path(args.verify_dump).expanduser() if args.verify_dump else None
    return verify_image(args, tool, port, image, keep)


def build_parser() -> argparse.ArgumentParser:
    wrapper_dir = Path(__file__).resolve().parent
    default_tool = find_default_tool(wrapper_dir)

    p = argparse.ArgumentParser(
        prog="hanicore_me7boot",
        description="Non-interactive Windows CLI for ME7 C167 bootmode external flash R/W.",
    )
    p.add_argument("--port", help="Windows serial port, e.g. COM3")
    p.add_argument("--baud", type=int, default=DEFAULT_BAUD, help=f"baud rate (default {DEFAULT_BAUD})")
    p.add_argument("--tool", default=str(default_tool), help="path to upstream ME7BootTool.py")
    p.add_argument("--json", action="store_true", help="emit machine-readable final result")

    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("ports", help="list Windows serial ports")

    sr = sub.add_parser("read", help="read external ME7 flash")
    sr.add_argument("output", help="output BIN filename")
    sr.add_argument("--size", type=parse_int, default=DEFAULT_READ_SIZE, help="read size (default 0x100000)")

    sw = sub.add_parser("write", help="write external ME7 flash; no verify by default")
    sw.add_argument("image", help="input BIN filename")
    sw.add_argument("--verify", action="store_true", help="perform full readback SHA-256 verification after write")
    sw.add_argument("--verify-dump", help="keep readback in this file instead of deleting it")
    sw.add_argument("--allow-partial", action="store_true", help="allow image sizes other than 0x80000/0x100000")

    sd = sub.add_parser("diffWrite", help="read/compare and erase+program only changed flash sectors; no verify by default")
    sd.add_argument("image", help="full input BIN filename (29F400/29F800)")
    sd.add_argument("--verify", action="store_true", help="perform full readback SHA-256 verification after diffWrite")
    sd.add_argument("--verify-dump", help="keep verification readback in this file (also enables verify)")

    sv = sub.add_parser("verify", help="full flash readback and SHA-256 compare against image")
    sv.add_argument("image", help="reference BIN filename")
    sv.add_argument("--verify-dump", help="keep readback in this file instead of deleting it")

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "ports":
        return cmd_ports(args)

    if not args.port:
        parser.error("--port is required for read/write/diffWrite/verify (example: --port COM3)")

    try:
        port = normalize_com_port(args.port)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE

    tool = Path(args.tool).expanduser().resolve()
    if not tool.is_file():
        print(f"ERROR: upstream ME7BootTool.py not found: {tool}", file=sys.stderr)
        print("Run install.ps1 or pass --tool C:\\path\\to\\C167BootTool\\ME7BootTool.py", file=sys.stderr)
        return EXIT_SETUP

    if args.command == "read":
        return cmd_read(args, tool, port)
    if args.command == "write":
        return cmd_write(args, tool, port)
    if args.command == "diffWrite":
        return cmd_diff_write(args, tool, port)
    if args.command == "verify":
        return cmd_verify(args, tool, port)

    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
