"""User preset library: names, built-in protection, atomic save, delete,
and the apply plan. No ECU: the library and the planner are pure."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402
import me711_user_presets as U  # noqa: E402

PAGE = U.PAGE


@pytest.fixture
def lib(tmp_path):
    return U.Library(tmp_path / "lib")


def page(fill=0x11):
    return bytes([fill]) * PAGE


def test_builtins_come_from_the_firmware_presets():
    b = U.builtin_names()
    assert "vag 1.8t dbw (awt)" in b and "vag_18t_me711" in b


@pytest.mark.parametrize("bad", ["", " lead", "trail ", "a/b", "..\\x",
                                 "x" * 41, "-dash", "tab\tname"])
def test_invalid_names_are_refused(lib, bad):
    with pytest.raises(U.PresetError):
        lib.save(bad, page(), "5AB824FA", "test")


@pytest.mark.parametrize("name", ["VAG 1.8T DBW (AWT)", "vag 1.8t dbw (awt)",
                                  "VAG_18T_ME711", "Custom / user defined"])
def test_builtin_names_cannot_be_taken(lib, name):
    with pytest.raises(U.PresetError):
        lib.save(name, page(), "5AB824FA", "test")


def test_save_list_show_round_trip(lib):
    path = lib.save("My AWT", page(0x22), "5AB824FA", "test", note="n")
    assert path.parent == lib.root and path.name == "my_awt.json"
    assert not list(lib.root.glob("*.tmp"))          # atomic: no leftovers
    d = lib.find("my awt")                           # case-insensitive
    assert d["name"] == "My AWT" and lib.page(d) == page(0x22)


def test_no_silent_overwrite_and_slug_collisions(lib):
    lib.save("My AWT", page(1), "5AB824FA", "test")
    with pytest.raises(U.PresetError):
        lib.save("my awt", page(2), "5AB824FA", "test")
    with pytest.raises(U.PresetError):
        lib.save("My_AWT", page(2), "5AB824FA", "test")   # same file name
    lib.save("My AWT", page(3), "5AB824FA", "test", replace=True)
    assert lib.page(lib.find("My AWT")) == page(3)


def test_delete_only_user_presets(lib):
    lib.save("Keep", page(1), "5AB824FA", "test")
    lib.save("Drop", page(2), "5AB824FA", "test")
    with pytest.raises(U.PresetError):
        lib.delete("VAG 1.8T DBW (AWT)")
    with pytest.raises(U.PresetError):
        lib.delete("missing")
    lib.delete("drop")
    assert [d["name"] for d in lib.user()] == ["Keep"]


def test_damaged_preset_is_detected(lib):
    p = lib.save("X", page(5), "5AB824FA", "test")
    d = json.loads(p.read_text())
    d["page"] = "00" + d["page"][2:]
    p.write_text(json.dumps(d))
    with pytest.raises(U.PresetError):
        lib.page(lib.find("X"))


def test_wrong_page_size_is_refused(lib):
    with pytest.raises(U.PresetError):
        lib.save("Short", b"\0" * 100, "5AB824FA", "test")


def test_plan_writes_only_differences_in_bounded_runs():
    cur = bytearray(page(0))
    want = bytearray(cur)
    want[10:50] = b"\1" * 40                  # 40 bytes -> 3 runs of <= 16
    want[100] = 7
    runs = U.plan_apply(bytes(cur), bytes(want), set())
    assert [(o, len(b)) for o, b in runs] == [(10, 16), (26, 16), (42, 8), (100, 1)]
    for o, b in runs:
        cur[o:o + len(b)] = b
    assert bytes(cur) == bytes(want)


def test_plan_skips_measured_fields():
    cur, want = bytearray(page(0)), bytearray(page(0))
    want[200:204] = bytes([9, 9, 9, 9])
    runs = U.plan_apply(bytes(cur), bytes(want), set(range(200, 204)))
    assert runs == []


def test_plan_refuses_a_page_that_would_overflow_the_transaction():
    with pytest.raises(U.PresetError):
        U.plan_apply(page(0), page(1), set())


def test_measured_offsets_cover_the_endpoint_fields():
    m = U.measured_offsets()
    o, w = U.field_span("CAL_TPS1_MIN")
    assert set(range(o, o + w)) <= m


class FakeLink:
    """A page in RAM behind the 'W' request; refuses the write at `refuse`."""

    def __init__(self, before, refuse=None, refuse_restore=False):
        self.page = bytearray(before)
        self.refuse, self.refuse_restore, self.writes = refuse, refuse_restore, []

    def request(self, payload, _timeout):
        off = int.from_bytes(payload[1:3], "big")
        data = payload[3:]
        restoring = any(o == off for o, _d in self.writes)
        if off == self.refuse and not restoring:
            self.writes.append((off, None))
            return None, "TS_BAD", 0
        if restoring and self.refuse_restore:
            return None, "TS_BAD", 0
        self.writes.append((off, data))
        self.page[off:off + len(data)] = data
        return b"", None, 0


def _two_runs():
    before = page(0)
    want = bytearray(before)
    want[10:12] = b"\1\1"
    want[300:302] = b"\2\2"
    return before, bytes(want), U.plan_apply(before, bytes(want), set())


def test_apply_writes_every_run():
    before, want, runs = _two_runs()
    link = FakeLink(before)
    assert U.write_runs(link, runs, before) is None
    assert bytes(link.page) == want


def test_a_refused_write_puts_back_what_was_written():
    before, want, runs = _two_runs()
    link = FakeLink(before, refuse=300)
    err = U.write_runs(link, runs, before)
    assert err and "put back" in err and "FAILED" not in err
    assert bytes(link.page) == before            # nothing left half-applied


def test_a_failed_put_back_is_reported_not_hidden():
    before, want, runs = _two_runs()
    link = FakeLink(before, refuse=300, refuse_restore=True)
    err = U.write_runs(link, runs, before)
    assert err and "FAILED" in err and "reload" in err


def test_cli_refuses_without_yes_and_for_builtins(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HANICORE_USER_PRESETS", str(tmp_path / "lib"))
    U.Library().save("Mine", page(4), U.layout_id(), "test")
    assert U.main(["delete", "Mine"]) == 2                 # no --yes
    assert U.main(["delete", "VAG 1.8T DBW (AWT)", "--yes"]) == 2
    assert U.main(["apply", "VAG 1.8T DBW (AWT)"]) == 2     # built-in: use TS
    assert U.main(["delete", "Mine", "--yes"]) == 0
    out = capsys.readouterr().out
    assert out.count("REFUSED") == 3 and "deleted user preset 'Mine'" in out
