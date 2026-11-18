"""KSP timed recovery: no early attempt, one shot, no unblock after failure."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scraper.ksp_schedule import ready, resume_after, snapshot_times
from scraper.spiders.ksp_stream import load_category_routes


def main():
    due = resume_after()
    assert due.tzinfo is not None
    assert due.hour < 4 or due.hour >= 21
    assert not ready(due - timedelta(seconds=1))
    assert ready(due)
    assert due >= datetime(2026, 11, 18, 17, 43, tzinfo=timezone.utc) + timedelta(days=3)
    timer = (ROOT / "nano/pc-parts-il-ksp-resume.timer").read_text()
    assert due.strftime("%Y-%m-%d %H:%M:%S UTC") in timer
    assert "Persistent=true" not in timer
    routes = load_category_routes(str(ROOT / "scraper/ksp_category_routes.json"))
    assert len(routes) == 13
    assert snapshot_times([{'vendor_id':'ksp','scraped_at':'2026-11-16T01:00:00Z'},
                           {'vendor_id':'ksp','scraped_at':'2026-11-22T01:00:00Z'}])['ksp'] == '2026-11-22T01:00:00Z'
    # Stub only privileged/network steps. Run the actual resume wrapper.
    with TemporaryDirectory() as tmp:
        temp = Path(tmp)
        repo = temp / "repo"
        (repo / "nano").mkdir(parents=True)
        (repo / "scraper").mkdir()
        state = temp / "state/pc-parts-il"
        state.mkdir(parents=True)
        (state / "ksp.paused").touch()
        calls = temp / "calls"
        (repo / "nano/run_state.sh").write_text('nano_lock() { export MIFRAT_CHECKOUT_LOCK=1; }\n')
        (repo / "nano/run_ksp.sh").write_text('echo crawl >> "$CALLS"\nexit "${CRAWL_STATUS:-0}"\n')
        bin = temp / "bin"
        bin.mkdir()
        for name, text in {
            "python": '#!/usr/bin/env bash\nexit "${EARLY:-0}"\n',
            "date": '#!/usr/bin/env bash\necho "${HOUR:-01}"\n',
            "flock": '#!/usr/bin/env bash\nexit 0\n',
        }.items():
            p = bin / name
            p.write_text(text)
            p.chmod(0o755)
        source = (ROOT / "nano/run_ksp_resume.sh").read_text().replace('/home/avizi/pc-parts-il', repo.as_posix()).replace('/home/avizi/miniforge3/envs/pc-parts-il/bin/python', (bin / 'python').as_posix())
        wrapper = temp / "resume.sh"
        wrapper.write_text(source)
        import os
        env = {**os.environ, "PATH": str(bin) + os.pathsep + os.environ["PATH"], "XDG_STATE_HOME": str(temp / "state"), "CALLS": str(calls), "MSYS2_ENV_CONV_EXCL": "XDG_STATE_HOME", "HOUR": "01", "EARLY": "0"}
        def run(**extra):
            bin_path = bin.as_posix()
            if os.name == 'nt':
                bin_path = '/' + bin_path[0].lower() + bin_path[2:]
            result = subprocess.run(['bash', '-c', f'export PATH="{bin_path}:$PATH"; bash "$1"', 'fixture', wrapper.as_posix()],
                                    env={**env, **extra}, capture_output=True)
            if result.returncode not in (0, 1, 3):
                print(result.stderr.decode(errors='replace'))
            return result.returncode
        assert run(EARLY="1") != 0 and (state / "ksp.paused").exists() and not calls.exists()
        assert run(HOUR="12") != 0 and (state / "ksp.paused").exists() and not calls.exists()
        assert run(HOUR="08") != 0 and (state / "ksp.paused").exists() and not calls.exists()
        assert run(CRAWL_STATUS="3") == 3
        assert (state / "ksp.paused").exists(), "failed recovery removed the safety pause"
        assert calls.read_text().strip() == 'crawl'
        (state / 'ksp-resume.attempted').unlink()
        assert run(CRAWL_STATUS='0') == 0, 'successful recovery returned failure'
        assert not (state / 'ksp.paused').exists()
        assert run() != 0, "second invocation must not claim successful recovery"
        assert calls.read_text().splitlines() == ['crawl', 'crawl']
    # Actual runner rejects an early start before constructing CrawlerProcess.
    from scraper import run_spider
    with patch('scraper.ksp_schedule.ready', return_value=False), \
         patch.object(run_spider, 'CrawlerProcess') as process, \
         patch.object(sys, 'argv', ['run_spider.py', 'ksp']):
        try:
            run_spider.main()
            raise AssertionError('early runner accepted')
        except SystemExit as error:
            assert error.code != 0
        assert not process.called, 'early date still constructed a live crawler'
    service = (ROOT / 'nano/pc-parts-il-ksp-resume.service').read_text()
    assert 'ExecStartPost=+/bin/systemctl enable --now pc-parts-il-ksp.timer' in service
    assert 'ksp-detail.timer' not in service
    print("[ksp-schedule] pass - 72h/night slot, 13 captured routes, no early/daytime/duplicate recovery")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
