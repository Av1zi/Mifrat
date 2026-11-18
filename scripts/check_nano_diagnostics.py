"""Offline regression: unreadable units must not abort Nano diagnostics."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import diagnose_nano_scrapes as diagnostic


def main():
    output = io.StringIO()

    def read_bytes(path):
        if path == Path("/etc/systemd/system/pc-parts-il-onepc.service"):
            raise PermissionError("fixture: unit not readable")
        return b"fixture unit"

    def command(*args):
        if "-c" in args:
            return "{}"
        return ""

    try:
        with patch.object(Path, "is_file", return_value=True), \
             patch.object(Path, "read_bytes", read_bytes), \
             patch.object(Path, "read_text", return_value=""), \
             patch.object(diagnostic, "read_command", side_effect=command), \
             patch.object(sys, "argv", ["diagnose", "--since", "2026-11-16"]), \
             redirect_stdout(output):
            code = diagnostic.main()
    except Exception as exc:
        print("[nano-diagnostics] FAIL", type(exc).__name__, "aborted collector")
        return 1
    text = output.getvalue()
    if code != 0 or '"unit_read_error": "PermissionError"' not in text or "ksp_runtime" not in text:
        print("[nano-diagnostics] FAIL: unit error not reported or runtime diagnostics not reached")
        return 1
    print("[nano-diagnostics] pass - unreadable unit reported; remaining units/runtime inspected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
