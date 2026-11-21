#!/usr/bin/env python3
r"""The logger in a window: HaniCore_Logger.exe, double-clicked.

One instruction at a time, Continue / Skip buttons, a green/red checklist. The
logging itself is me711_vehicle_test.py, run unchanged as a child process of
this same exe: this file only reads what it prints and answers its questions, so
every file a session writes (console.log, the CSVs, the ZIP) is what it always
was. With arguments the exe is the plain command-line tool.
"""
from __future__ import annotations

import datetime as dt
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

CHILD_FLAG = "--gui-child"
NO_WINDOW = 0x08000000

_STAMP = re.compile(r"^\[\s*[\d.]+\]\s?")
_VERDICT = re.compile(r"^([A-Z][^:]{2,40}): (PASS|FAIL|SKIP|WARN|INFO)\b(?: - (.*))?$")
_NOT_A_CHECK = {"AUTOCAL", "KLINE", "ETB", "RAM", "STATE", "ENGINE", "EVENTS", "SNAPSHOT"}
_PHASE = re.compile(r"PHASE \d+: ([^=]+?)\s*=*$")
_CABLE = re.compile(r"\[Enter\] = (OBD|DIRECT ECU)\s+d = ")


def plain(prompt: str) -> str:
    """The logger's console wording, for buttons."""
    s = re.sub(r"\s*\(s(?: \+ ENTER)? skips\)|\s*\(s \+ Enter: skip\)", "", prompt)
    s = re.sub(r"\s*\(s \+ ENTER:[^)]*\)", "", s)
    s = re.sub(r"\b[Pp]ress (ENTER|Enter)\b", "click Continue", s)
    s = re.sub(r"\bENTER\b", "Continue", s)
    s = re.sub(r"(\. )click\b", r"\1Click", s)
    return s[0].upper() + s[1:] if s else s


def classify(raw: str):
    """One line of the logger's output -> (kind, data). See the test beside it."""
    line = _STAMP.sub("", raw.rstrip())
    text = line.strip()
    if not text:
        return ("log", "")
    if text.startswith("SESSION ZIP"):
        return ("zip", text.split(":", 1)[-1].strip())
    m = _CABLE.search(text)
    if m:
        return ("cable", m.group(1))
    if text.startswith(">>> Where is the KKL"):
        return ("log", text)
    if text.startswith(">>> SAFETY"):
        return ("warn", text[4:].replace("SAFETY: ", "").strip())
    if text.startswith(">>> "):
        p = text[4:]
        skip = bool(re.search(r"\bs\b( \+ (ENTER|Enter))?(:| skips)", p))
        return ("prompt", (plain(p), skip))
    m = _PHASE.search(text)
    if m and text.lstrip("= ").startswith("PHASE"):
        return ("phase", m.group(1).strip())
    m = re.match(r"BURN \((.*?)\): (.*)$", text)
    if m:
        ok = m.group(2).startswith("OK")
        return ("check", ("Burn: " + m.group(1), "PASS" if ok else "FAIL", m.group(2)))
    m = _VERDICT.match(text)
    if m and m.group(1) not in _NOT_A_CHECK:
        return ("check", (m.group(1), m.group(2), m.group(3) or ""))
    if line.startswith("    ") and text[:1].isupper() and not text.startswith(("RAM:", "ENGINE CONFIG")):
        return ("info", text)
    return ("log", text)


def child_main(argv) -> int:
    """The logger itself, under the window. A stop file ends it the way Ctrl+C
    does, so the session keeps what it recorded and writes its ZIP."""
    stop = Path(argv[argv.index("--stop-file") + 1])
    i = argv.index("--stop-file")
    argv = argv[:i] + argv[i + 2:]

    def watch():
        import _thread
        while not stop.exists():
            time.sleep(0.2)
        _thread.interrupt_main()
    threading.Thread(target=watch, daemon=True).start()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    return cli(argv)


def cli(argv) -> int:
    root = Path(__file__).resolve().parents[2]
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(root / "tools" / "lib"))
    import me711_vehicle_test as VT
    return VT.main(argv)


def kit_dir() -> Path:
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()


def find_ports():
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    usb = [p for p in ports if any(k in (p.description or "") + (p.manufacturer or "")
                                   for k in ("FTDI", "USB Serial", "CH340", "Prolific", "KKL", "CP210", "USB"))]
    return [p.device for p in usb] + [p.device for p in ports if p not in usb]


class App:
    GREEN, RED, GREY, AMBER = "#1a7f37", "#c62828", "#8a8f98", "#b26a00"

    def __init__(self):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.root = tk.Tk()
        self.root.title("HaniCore logger")
        self.root.geometry("980x720")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.q = queue.Queue()
        self.proc = None
        self.stop_file = None
        self.zip = None
        self.rows = {}
        self.cable_choice = "OBD"
        self.auto = os.environ.get("HC_APP_AUTOTEST")
        self.start_screen()
        self.root.after(100, self.poll)

    def clear(self):
        for w in self.root.winfo_children():
            w.destroy()

    def start_screen(self):
        tk, ttk = self.tk, self.ttk
        self.clear()
        f = tk.Frame(self.root, padx=30, pady=24)
        f.pack(fill="both", expand=True)
        tk.Label(f, text="HaniCore logger", font=("Segoe UI", 26, "bold")).pack(anchor="w")
        tk.Label(f, text="Key on, engine off. Close LibreTune first: only one program can use the cable.",
                 font=("Segoe UI", 13)).pack(anchor="w", pady=(4, 20))
        g = tk.Frame(f)
        g.pack(anchor="w", pady=(0, 20))
        tk.Label(g, text="Cable is in:", font=("Segoe UI", 13)).grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.cable = tk.StringVar(value="OBD")
        ttk.Radiobutton(g, text="Car OBD socket", value="OBD", variable=self.cable).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(g, text="ECU K-line pin", value="DIRECT ECU", variable=self.cable).grid(row=0, column=2, sticky="w", padx=12)
        tk.Label(g, text="Port:", font=("Segoe UI", 13)).grid(row=1, column=0, sticky="w", pady=(10, 0))
        ports = find_ports()
        self.port = tk.StringVar(value=os.environ.get("HC_APP_PORT") or (ports[0] if ports else ""))
        ttk.Combobox(g, textvariable=self.port, values=ports, width=12).grid(row=1, column=1, sticky="w", pady=(10, 0))
        self.ini = sorted(kit_dir().glob("*.ini"), key=lambda p: p.stat().st_mtime)
        if not self.ini:
            tk.Label(f, text="No .ini next to this program: keep the kit's files together.",
                     fg=self.RED, font=("Segoe UI", 14, "bold")).pack(anchor="w")
            return
        tk.Button(f, text="Guided car test\nStep by step. Moves the throttle, asks you to start the engine.",
                  font=("Segoe UI", 15), bg=self.GREEN, fg="white", height=3,
                  command=lambda: self.start(True)).pack(fill="x", pady=6)
        tk.Button(f, text="Just record (15 min)\nDrive or idle. Nothing is changed in the ECU.",
                  font=("Segoe UI", 15), height=3, command=lambda: self.start(False)).pack(fill="x", pady=6)
        if self.auto:
            self.root.after(500, lambda: self.start(self.auto in ("guided", "hold")))

    def run_screen(self, title):
        tk = self.tk
        self.clear()
        top = tk.Frame(self.root, padx=24, pady=14)
        top.pack(fill="x")
        self.phase = tk.Label(top, text=title, font=("Segoe UI", 12, "bold"), fg=self.GREY, anchor="w")
        self.phase.pack(fill="x")
        self.text = tk.Label(top, text="Connecting to the ECU...", font=("Segoe UI", 22, "bold"),
                             wraplength=920, justify="left", anchor="w")
        self.text.pack(fill="x", pady=(6, 2))
        self.warn = tk.Label(top, text="", font=("Segoe UI", 13, "bold"), fg=self.AMBER,
                             wraplength=920, justify="left", anchor="w")
        self.warn.pack(fill="x")
        self.sub = tk.Label(top, text="", font=("Segoe UI", 13), wraplength=920, justify="left", anchor="w")
        self.sub.pack(fill="x")
        b = tk.Frame(top)
        b.pack(fill="x", pady=(12, 0))
        self.go = tk.Button(b, text="Continue", font=("Segoe UI", 16, "bold"), width=14, state="disabled",
                            command=lambda: self.answer(""))
        self.go.pack(side="left")
        self.skip = tk.Button(b, text="Skip", font=("Segoe UI", 14), width=8, command=lambda: self.answer("s"))
        self.stopb = tk.Button(b, text="Stop and save", font=("Segoe UI", 12), command=self.stop)
        self.stopb.pack(side="right")
        self.detail_btn = tk.Button(b, text="Details", font=("Segoe UI", 12), command=self.toggle_details)
        self.detail_btn.pack(side="right", padx=8)
        mid = tk.Frame(self.root, padx=24)
        mid.pack(fill="both", expand=True, pady=(8, 12))
        tk.Label(mid, text="Checks", font=("Segoe UI", 12, "bold"), fg=self.GREY, anchor="w").pack(fill="x")
        # a full guided test has more checks than a laptop screen: it scrolls
        # and keeps the newest in view
        box = tk.Frame(mid)
        box.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(box, highlightthickness=0)
        bar = tk.Scrollbar(box, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.list = tk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.list, anchor="nw")
        self.list.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(-e.delta // 120, "units"))
        self.details = tk.Text(mid, height=12, font=("Consolas", 9), wrap="word")
        self.details_on = False
        self.rows = {}

    def toggle_details(self):
        self.details_on = not self.details_on
        if self.details_on:
            self.details.pack(fill="both", expand=True, pady=(8, 0))
        else:
            self.details.pack_forget()

    def start(self, guided: bool):
        day = dt.datetime.now().strftime("%Y%m%d_%H%M")
        self.cable_choice = self.cable.get()
        port = self.port.get().strip() or "auto"
        args = ["--port", port, "--baud", "57600", "--ini", self.ini[-1].name]
        args += ["--guided", "--out", "guided_" + day] if guided else \
                ["--recorder", "--duration", os.environ.get("HC_APP_SECONDS", "900"), "--out", "log_" + day]
        self.stop_file = Path(tempfile.gettempdir()) / ("hc_logger_stop_%d" % os.getpid())
        self.stop_file.unlink(missing_ok=True)
        me = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, __file__]
        self.proc = subprocess.Popen(me + [CHILD_FLAG, "--stop-file", str(self.stop_file)] + args,
                                     cwd=str(kit_dir()), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        self.run_screen("Guided car test" if guided else "Recording")
        threading.Thread(target=self.reader, daemon=True).start()

    def reader(self):
        buf = b""
        while True:
            chunk = self.proc.stdout.read1(4096)
            if not chunk:
                break
            buf += chunk
            parts = re.split(rb"[\r\n]+", buf)
            buf = parts.pop()
            for p in parts:
                self.q.put(p.decode("utf-8", "replace"))
        if buf:
            self.q.put(buf.decode("utf-8", "replace"))
        self.q.put(None)

    def send(self, s: str):
        try:
            self.proc.stdin.write((s + "\n").encode())
            self.proc.stdin.flush()
        except OSError:
            pass

    def answer(self, s: str):
        self.go.config(state="disabled", bg="SystemButtonFace", fg="black")
        self.skip.pack_forget()
        self.warn.config(text="")
        self.send(s)
        self.text.config(text="Working...")
        self.sub.config(text="")

    def check(self, name, status, detail):
        tk = self.tk
        color = {"PASS": self.GREEN, "FAIL": self.RED, "WARN": self.AMBER}.get(status, self.GREY)
        if name not in self.rows:
            r = tk.Frame(self.list)
            r.pack(fill="x", pady=1)
            badge = tk.Label(r, width=6, font=("Segoe UI", 10, "bold"), fg="white")
            badge.pack(side="left", padx=(0, 8))
            tk.Label(r, text=name, font=("Segoe UI", 12), width=28, anchor="w").pack(side="left")
            d = tk.Label(r, font=("Segoe UI", 10), fg="#444", anchor="w", justify="left", wraplength=560)
            d.pack(side="left", fill="x", expand=True)
            self.rows[name] = (badge, d)
        badge, d = self.rows[name]
        badge.config(text=status, bg=color)
        d.config(text=detail[:150])
        self.root.update_idletasks()
        self.canvas.yview_moveto(1.0)

    def handle(self, raw: str):
        self.details.insert("end", raw + "\n")
        self.details.see("end")
        kind, data = classify(raw)
        if kind == "phase":
            self.phase.config(text=data)
            self.sub.config(text="")
        elif kind == "cable":
            self.send("" if data == self.cable_choice else "d")
        elif kind == "warn":
            self.warn.config(text=data)
        elif kind == "info":
            self.sub.config(text=data)
        elif kind == "prompt":
            text, skip = data
            self.text.config(text=text)
            self.go.config(state="normal", bg=self.GREEN, fg="white")
            if skip:
                self.skip.pack(side="left", padx=10)
            if self.auto == "guided":
                self.root.after(1200, lambda: self.answer(""))
        elif kind == "check":
            self.check(*data)
        elif kind == "zip":
            self.zip = data

    def poll(self):
        try:
            for _ in range(200):
                raw = self.q.get_nowait()
                if raw is None:
                    self.finished()
                    break
                self.handle(raw)
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def stop(self):
        if self.stop_file:
            self.stop_file.touch()
        self.stopb.config(state="disabled", text="Saving...")
        self.text.config(text="Stopping and saving...")

    def finished(self):
        tk = self.tk
        code = self.proc.wait()
        if self.stop_file:
            self.stop_file.unlink(missing_ok=True)
        self.go.pack_forget()
        self.skip.pack_forget()
        self.stopb.pack_forget()
        self.warn.config(text="")
        self.phase.config(text="Finished")
        if self.zip:
            self.text.config(text="Done. Bring back this file:", fg=self.GREEN)
            self.sub.config(text=str(kit_dir() / self.zip))
        else:
            self.text.config(text="It stopped before a session was saved (exit %s). See Details." % code, fg=self.RED)
        tk.Button(self.stopb.master, text="Open folder", font=("Segoe UI", 14),
                  command=lambda: os.startfile(str(kit_dir()))).pack(side="left")
        if self.auto:
            self.root.after(1500, self.root.destroy)

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.stop()
            for _ in range(150):
                if self.proc.poll() is not None:
                    break
                time.sleep(0.1)
        self.root.destroy()


def main() -> int:
    if sys.stdout is None:                  # a windowed exe run with arguments
        sys.stdout = open(os.devnull, "w")
        sys.stderr = sys.stdout
    argv = sys.argv[1:]
    if argv[:1] == [CHILD_FLAG]:
        return child_main(argv[1:])
    if argv:
        return cli(argv)
    App().root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
