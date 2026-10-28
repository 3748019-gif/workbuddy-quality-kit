"""Capture real command failures and bound retries. Python 3.9+, standard library.

This is a task-local runner, not a sandbox or a business-result validator.
It preserves the inherited runtime and never disables hooks or permissions.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
import task_guard

SCHEMA = 'workbuddy-quality-run/2'
HARD_STOP = {'managed_runtime', 'permission'}


def classify(returncode, stdout, stderr, timed_out=False, start_error=None):
    try:
        value = json.loads(stdout)
    except (ValueError, TypeError):
        value = None
    reported = isinstance(value, dict) and (value.get('ok') is False or value.get('passed') is False)
    text = (stderr + '\n' + (stdout if returncode != 0 or reported else '')).lower()
    # A traceback from the managed interpreter needs review, not a startup bypass.
    if ('sitecustomize' in text and ('error' in text or 'exception' in text)) or (
            'no usable temporary directory' in text):
        return 'managed_runtime'
    if start_error == 'PermissionError' or any(x in text for x in (
            'permission denied', 'operation not permitted', 'access is denied',
            'access denied', 'read-only file system')):
        return 'permission'
    if timed_out:
        return 'timeout'
    if start_error == 'FileNotFoundError' or any(x in text for x in (
            'modulenotfounderror', 'command not found', 'no module named')):
        return 'dependency'
    if returncode != 0:
        return 'process'
    if reported:
        return 'reported_failure'
    return None


def _excerpt(path, limit=65536):
    with path.open('rb') as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - limit))
        data = f.read(limit)
    return data.decode('utf-8', errors='replace'), size > limit


def _save(path, value, *, root, protected):
    """Write one new log record exclusively; never rename or overwrite a log."""
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    path=Path(path)
    task_guard.check_separation([p for p in protected if Path(p).exists()],[path],root=root)
    if path.is_symlink():raise ValueError('Refuse a symlink log record')
    fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as f:
        f.write(payload);f.flush();os.fsync(f.fileno())
    if json.loads(path.read_text(encoding='utf-8'))!=value:
        raise ValueError('Saved command record differs; preserve and review')


def run_checked(root, argv, *, cwd='.', state='work/run-state.json',
                evidence=(), timeout=60, attempt_limit=2, expected=()):
    root = Path(root).resolve(strict=True)
    if not root.is_dir() or not isinstance(argv, (list, tuple)) or not argv:
        raise ValueError('Use an existing task root and a nonempty argument list')
    if not all(isinstance(x, str) and x and '\x00' not in x for x in argv):
        raise ValueError('Command arguments must be nonempty strings')
    if not 0 < timeout <= 3600 or not 1 <= attempt_limit <= 3:
        raise ValueError('timeout must be <=3600 seconds; attempt_limit must be 1..3')
    cwd = task_guard.within(root, root / cwd)[0]
    if not cwd.is_dir():
        raise ValueError('Working directory must already exist inside the task root')
    state = task_guard.within(root, root / state)[0]
    if state.is_symlink() or not state.parent.is_dir():
        raise ValueError('State parent must already exist; do not use a state symlink')
    protected = [task_guard.within(root, root / n)[0] for n in evidence]
    targets = [task_guard.within(root, root / n)[0] for n in expected]
    task_guard.check_separation(protected, [state] + targets, root=root)
    logdir = state.parent / (state.stem + '-runs')
    ledger={'runs':[]}
    if state.exists():
        header=json.loads(state.read_text(encoding='utf-8'))
        if header.get('schema')!=SCHEMA or header.get('logs')!=str(logdir.relative_to(root)) or not isinstance(header.get('owner'),str):
            raise ValueError('Existing state is not this runner state; preserve it')
        if not logdir.is_dir() or logdir.is_symlink():raise ValueError('Runner log directory changed; preserve and review')
        for rd in sorted(logdir.iterdir()):
            if not rd.is_dir() or rd.is_symlink():raise ValueError('Unknown file in runner logs; preserve it')
            launch=rd/'launch.json';result=rd/'result.json'
            if not launch.is_file() or launch.is_symlink():raise ValueError('Incomplete runner launch record; preserve and review')
            row=json.loads(launch.read_text(encoding='utf-8'))
            if row.get('owner')!=header['owner']:raise ValueError('Runner log ownership mismatch')
            if result.exists():
                if result.is_symlink():raise ValueError('Runner result link refused')
                row=json.loads(result.read_text(encoding='utf-8'))
                if row.get('owner')!=header['owner']:raise ValueError('Runner result ownership mismatch')
            ledger['runs'].append(row)
    else:header={'schema':SCHEMA,'owner':uuid.uuid4().hex,'logs':str(logdir.relative_to(root))}
    baseline = task_guard.snapshot(root, list(evidence)) if evidence else {'files': {}}
    version = hashlib.sha256(json.dumps(baseline, sort_keys=True).encode()).hexdigest()
    key = hashlib.sha256(json.dumps([str(cwd), list(argv)], ensure_ascii=False).encode()).hexdigest()
    relevant = [x for x in ledger['runs'] if x.get('evidence_version') == version]
    pending = [x for x in relevant if x.get('status') == 'running']
    hard = [x for x in relevant if x.get('category') in HARD_STOP]
    repeated = [x for x in relevant if x.get('command_key') == key and x.get('ok') is False]
    reason = 'previous_command_interrupted_review_logs' if pending else (
        'same_environment_fault_review_before_retry' if hard else (
            'retry_budget_exhausted' if len(repeated) >= attempt_limit else None))
    if reason:
        return {'schema': SCHEMA, 'ok': False, 'blocked': True, 'executed': False,
                'reason': reason, 'state': str(state.relative_to(root)),
                'previous_log': (pending or hard or repeated)[-1].get('log'),
                'next': 'Read the saved error and preserve results. Retry after a verified cause or input change; do not disable runtime protection.'}
    task_guard.check_separation(protected, [state] + targets + [logdir], root=root)
    if any(p == logdir or p.is_relative_to(logdir) or logdir.is_relative_to(p)
           for p in [state] + targets):
        raise ValueError('State and expected files must be separate from the log directory')
    if logdir.is_symlink() or (logdir.exists() and not logdir.is_dir()):
        raise ValueError('Log path is occupied; preserve it and choose another state name')
    if not state.exists() and logdir.exists() and any(logdir.iterdir()):
        raise ValueError('Unowned existing logs; choose another state name')
    if not logdir.exists():
        logdir.mkdir()
    if not state.exists():_save(state,header,root=root,protected=protected+targets)
    runid = uuid.uuid4().hex
    rd = logdir / runid
    task_guard.check_separation(protected, [state] + targets + [rd], root=root)
    rd.mkdir()
    outpath, errpath = rd / 'stdout.txt', rd / 'stderr.txt'
    reportpath = rd / 'result.json'
    rec = {'command_key': key, 'evidence_version': version, 'argv': list(argv),
           'cwd': str(cwd.relative_to(root)), 'status': 'running',
           'log': str(reportpath.relative_to(root)), 'started': time.time(), 'owner':header['owner']}
    _save(rd/'launch.json',rec,root=root,protected=protected+targets+[state])
    timed_out, start_error, returncode = False, None, None
    with outpath.open('xb') as out, errpath.open('xb') as err:
        try:
            proc = subprocess.Popen(argv, cwd=str(cwd), stdout=out, stderr=err,
                                    start_new_session=(os.name == 'posix'))
            try:
                returncode = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                if os.name == 'posix':
                    os.killpg(proc.pid, signal.SIGTERM)
                else:
                    proc.terminate()
                try:
                    returncode = proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    if os.name == 'posix':
                        os.killpg(proc.pid, signal.SIGKILL)
                    else:
                        proc.kill()
                    returncode = proc.wait(timeout=3)
                if os.name == 'posix':
                    # The leader may have exited while a descendant ignored TERM.
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        except OSError as error:
            start_error = type(error).__name__
            err.write((start_error + ': ' + str(error)).encode('utf-8', errors='replace'))
    stdout, out_cut = _excerpt(outpath)
    stderr, err_cut = _excerpt(errpath)
    category = classify(returncode, stdout, stderr, timed_out, start_error)
    if not category and out_cut:
        category = 'large_output_requires_review'
    missing = [str(p.relative_to(root)) for p in targets if not p.is_file()]
    if not category and missing:
        category = 'missing_output'
    try:
        input_check = task_guard.verify(root, baseline, []) if evidence else {'passed': True}
    except (ValueError, OSError) as error:
        input_check = {'passed': False, 'error': str(error)}
    if not input_check['passed']:
        category = 'input_changed'
    ok = category is None
    result = dict(rec, schema=SCHEMA, status='finished', ok=ok, executed=True,
                  blocked=False, returncode=returncode, category=category,
                  timed_out=timed_out, start_error=start_error,
                  elapsed_seconds=round(time.time() - rec['started'], 3),
                  stdout=str(outpath.relative_to(root)), stderr=str(errpath.relative_to(root)),
                  stdout_tail=stdout, stderr_tail=stderr,
                  excerpts_truncated=out_cut or err_cut, missing_outputs=missing,
                  inputs_unchanged=input_check['passed'],
                  retry_requires_review=bool(category),
                  check_scope='exit status, top-level JSON failure flag, expected-file presence, input versions; not business correctness or visual layout')
    # Keep raw streams even if updating the state is refused by the runtime.
    try:
        _save(reportpath, result, root=root, protected=protected + targets + [state])
    except (OSError,ValueError) as error:
        result.update(ok=False,category='result_record_blocked',record_error=str(error),
                      status='record_incomplete',executed=True)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True)
    p.add_argument('--cwd', default='.')
    p.add_argument('--state', default='work/run-state.json')
    p.add_argument('--evidence', nargs='*', default=[])
    p.add_argument('--expect', nargs='*', default=[])
    p.add_argument('--timeout', type=float, default=60)
    p.add_argument('--attempt-limit', type=int, default=2)
    p.add_argument('argv', nargs=argparse.REMAINDER)
    args = p.parse_args()
    argv = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
    try:
        result = run_checked(args.root, argv, cwd=args.cwd, state=args.state,
                             evidence=args.evidence, timeout=args.timeout,
                             attempt_limit=args.attempt_limit, expected=args.expect)
    except Exception as error:
        print(json.dumps({'ok': False, 'executed': False, 'error': str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result['ok']:
        return 0
    if result.get('blocked'):
        return 75
    if result.get('timed_out'):
        return 124
    rc = result.get('returncode')
    return (min(rc, 125) if rc > 0 else min(128 - rc, 255)) if rc else 65


if __name__ == '__main__':
    raise SystemExit(main())
