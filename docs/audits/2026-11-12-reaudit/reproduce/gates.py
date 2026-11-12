"""Run inspected offline workflow diagnostics against the scratch archive only."""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time

RUN = Path(__file__).resolve().parent
SNAP = RUN / 'snapshot'
OUT = RUN.parents[2] / 'docs/audits/2026-11-12-reaudit'
LOGS = RUN / 'gates'
COMMANDS = [
    ['scripts/check_spec_sync.py'], ['scripts/migrate_mfr_schema.py', '--check'],
    ['scripts/check_golden_resolution.py'],
    ['-m', 'scraper.specs.golden.check_golden', '--baseline', 'data/catalog.json'],
    ['scripts/check_tms_detail.py'], ['scripts/check_spec_merge.py'],
    ['scripts/check_categories.py'], ['scripts/check_identity_merge.py'],
    ['scripts/check_brands.py', '--self-test'], ['scripts/check_brands.py'],
    ['scripts/check_snapshot_rows.py', '--self-test'], ['scripts/check_snapshot_rows.py'],
    ['scripts/check_text_hygiene.py', '--self-test'], ['scripts/check_text_hygiene.py'],
    ['scripts/check_ksp_tags.py'], ['scripts/check_xref_fixtures.py'],
    ['scripts/check_extract.py'], ['scripts/check_ledgers.py', '--self-test'],
    ['scripts/check_ledgers.py'], ['scripts/backtest_rules.py', '--check'],
    ['scripts/check_spec_coverage.py', '--self-test'], ['scripts/check_spec_coverage.py'],
    ['scripts/check_spec_invariants.py', '--self-test'], ['scripts/check_spec_invariants.py'],
    ['scripts/check_image_pick.py'], ['scripts/check_image_files.py'],
    ['scripts/check_site_images.py'], ['scraper/check_site_size.py'],
    ['scripts/check_publish_set.py', '--self-test'], ['scripts/check_publish_set.py'],
]

def main():
    LOGS.mkdir(exist_ok=True)
    env = os.environ.copy()
    # Do not pass production credentials to diagnostic subprocesses or log env values.
    for key in list(env):
        if any(word in key.upper() for word in ['TOKEN', 'SECRET', 'PASSWORD', 'COOKIE', 'GOOGLE_KEY', 'GROQ_KEY', 'INTERN_KEY', 'API_KEY']):
            env.pop(key)
    env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', PYTHONHASHSEED='0',
               TEMP=str(LOGS), TMP=str(LOGS))
    results = []
    for i, args in enumerate(COMMANDS, 1):
        command = [sys.executable, '-B', '-X', 'utf8', *args]
        start = time.monotonic()
        try:
            proc = subprocess.run(command, cwd=SNAP, env=env, capture_output=True, timeout=180)
            text = proc.stdout.decode('utf-8', errors='replace') + proc.stderr.decode('utf-8', errors='replace')
            code = proc.returncode
        except subprocess.TimeoutExpired as exc:
            text = (exc.stdout or b'').decode('utf-8', errors='replace') + (exc.stderr or b'').decode('utf-8', errors='replace')
            code = 'timeout'
        name = f'{i:02d}-' + ('golden' if args[0] == '-m' else Path(args[0]).stem) + ('-self-test' if '--self-test' in args else '') + '.log'
        (LOGS / name).write_text(text, encoding='utf-8')
        result = {'command': 'python -B -X utf8 ' + ' '.join(args), 'cwd': str(SNAP),
            'effective_date': '2026-11-12', 'inputs': 'pinned archive; no rebuild',
            'exit_code': code, 'runtime_seconds': round(time.monotonic()-start, 3),
            'artifact': f'reproduce/gates/{name}',
            'warnings': [line for line in text.splitlines() if any(x in line.lower() for x in ['warn', 'fail', 'missing', 'regression', 'pinned'])],
            'side_effect_review': 'Offline entrypoints. Fixture writes isolated by TEMP/TMP; no refresh/download/normalize/publish invoked. Extract client calls are mocked; no API traffic. Golden baseline is same pinned catalog, not prior build.'}
        results.append(result)
        (RUN / 'gate-results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(f'{i:02d} exit={code} {result["runtime_seconds"]}s {args}', flush=True)
    manifest = json.loads((OUT / 'manifest.json').read_text(encoding='utf-8'))
    manifest['commands'] = results
    manifest['workflow_steps_not_executed'] = ['dependency install', 'pcpartdb refresh (network+write)', 'image backfills (network+write)', 'normalize entrypoint (write)', 'bundle/upload/publish/commit/push']
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')

if __name__ == '__main__':
    main()
