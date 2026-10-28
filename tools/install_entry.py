"""Add two local quality hooks while preserving existing WorkBuddy settings.

Python 3.9+. No network, credentials, permissions or memory changes. Receipts and
the exact before-file stay in the caller's private configuration workspace.
File verification is not proof that the product has executed the hook.
"""
from pathlib import Path
import argparse, hashlib, json, os, shlex, stat, sys, tempfile, uuid

EVENT = 'SessionStart'
GATE_EVENT = 'PreToolUse'
SCHEMA = 'workbuddy-quality-entry/1'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2); f.write('\n')
        f.flush(); os.fsync(f.fileno())


def read_settings(path):
    p = Path(path).expanduser().absolute()
    if p.is_symlink() or not p.parent.is_dir():
        raise ValueError('Settings must have an existing parent and cannot be a symlink')
    p = p.parent.resolve() / p.name
    if p.exists() and (not p.is_file() or p.stat().st_nlink != 1):
        raise ValueError('Settings must be one regular, unaliased file')
    raw = p.read_bytes() if p.exists() else None
    data = json.loads(raw.decode('utf-8-sig')) if raw is not None else {}
    if not isinstance(data, dict): raise ValueError('Preserve non-object settings; manual review required')
    hooks = data.get('hooks', {})
    if not isinstance(hooks, dict) or any(not isinstance(hooks.get(e, []), list) for e in (EVENT,GATE_EVENT)):
        raise ValueError('Unknown hook structure; preserve existing settings')
    return p, raw, data


def entry_for(skill, python, filename='entry_hook.py'):
    skill = Path(skill).expanduser()
    if skill.is_symlink() or not skill.is_dir(): raise ValueError('Use a verified real skill directory')
    skill = skill.resolve()
    script = skill / 'scripts' / filename
    if script.is_symlink() or not script.is_file() or not script.resolve().is_relative_to(skill) or not (skill/'SKILL.md').is_file():
        raise ValueError('Verified skill entry files are required')
    py = Path(python).expanduser().absolute()
    if not py.is_file(): raise ValueError('Use an existing normal Python interpreter')
    args = [str(py), str(script)]
    if os.name == 'nt':
        if any(any(c in a for c in '\n\r\x00\"%!^') for a in args):
            raise ValueError('Shell-special Windows path: preserve settings and use explicit skill entry')
        command = ' '.join('"' + a + '"' for a in args)
    else:
        command = ' '.join(shlex.quote(a) for a in args)
    return {'hooks': [{'type': 'command', 'command': command, 'timeout': 5}]}, script


def plan(settings, skill, python):
    p, raw, data = read_settings(settings)
    entry, script = entry_for(skill, python)
    gate, gate_script = entry_for(skill, python, 'entry_gate.py')
    gate['matcher']='Write|Edit|MultiEdit|Bash'
    desired={EVENT:entry,GATE_EVENT:gate}
    if data.get('disableAllHooks') is True:
        return {'status': 'disabled_preserved', 'settings': str(p), 'existing_settings_changed': False}
    overrides=data.get('skillOverrides',{})
    if isinstance(overrides,dict):
        for name,value in overrides.items():
            if name=='workbuddy-quality-kit' or str(name).replace('\\','/').rstrip('/').endswith('/workbuddy-quality-kit'):
                if value is False or (isinstance(value,dict) and value.get('enabled') is False):
                    return {'status':'disabled_preserved','settings':str(p),'reason':'quality skill disabled by its owner','existing_settings_changed':False}
    additions={};conflicts=[]
    for event,item in desired.items():
        entries=data.get('hooks',{}).get(event,[])
        path=str(script if event==EVENT else gate_script)
        exact=[x for x in entries if x==item]
        related=[x for x in entries if path in json.dumps(x,ensure_ascii=False)]
        if len(exact)==len(related)==1:continue
        if related:conflicts.append(event)
        else:additions[event]=item
    status='conflict' if conflicts else ('add' if additions else 'reuse')
    return {'status': status, 'settings': str(p), 'entry': entry,
            'entries_to_add':additions,'conflicting_events':conflicts,
            'before_sha256': sha(raw) if raw is not None else None,
            'script': str(script), 'script_sha256': sha(script.read_bytes()),
            'gate_script':str(gate_script),'gate_sha256':sha(gate_script.read_bytes()),
            'existing_settings_changed': False,
            'activation': 'File plan only; observe a fresh normal WorkBuddy task before claiming activation.'}


def replace_checked(path, old_raw, value):
    if path.is_symlink() or (path.exists() and path.stat().st_nlink != 1):
        raise ValueError('Settings identity changed; preserve and review')
    current = path.read_bytes() if path.exists() else None
    if current != old_raw: raise ValueError('Settings changed since planning; preserve and re-plan')
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    fd, name = tempfile.mkstemp(prefix='.quality-entry-', dir=str(path.parent))
    candidate = Path(name)
    with os.fdopen(fd, 'wb') as f:
        f.write(payload); f.flush(); os.fsync(f.fileno())
    if json.loads(candidate.read_text(encoding='utf-8')) != value:
        raise ValueError('Saved candidate does not match planned settings')
    os.chmod(candidate, mode)
    current = path.read_bytes() if path.exists() else None
    if path.is_symlink() or current != old_raw:
        raise ValueError('Settings changed before replace; preserve candidate and review')
    os.replace(candidate, path)


def receipt_path(path, settings, script):
    p = Path(path).expanduser().absolute()
    if p.is_symlink() or p.exists() or not p.parent.is_dir() or p.parent.is_symlink():
        raise ValueError('Receipt must be new and have a real existing parent')
    p = p.parent.resolve() / p.name
    if p == settings or p.is_relative_to(script.parents[1]):
        raise ValueError('Keep receipt in a separate private configuration workspace')
    return p


def apply(settings, skill, python, receipt):
    proposal = plan(settings, skill, python)
    if proposal['status'] != 'add': return proposal
    p, raw, data = read_settings(settings)
    if (sha(raw) if raw is not None else None) != proposal['before_sha256']:
        raise ValueError('Settings changed since planning')
    script = Path(proposal['script'])
    rec = receipt_path(receipt, p, script)
    backup = rec.parent / (rec.name + '.before-' + uuid.uuid4().hex + '.json')
    record = dict(proposal, schema=SCHEMA, status='prepared', before_existed=raw is not None,
                  backup=str(backup) if raw is not None else None,
                  before_had_hooks='hooks' in data,
                  before_had_event=EVENT in data.get('hooks', {}),
                  before_had_events={e:e in data.get('hooks',{}) for e in proposal['entries_to_add']},
                  installed_entries=proposal['entries_to_add'])
    write_new(rec, record)
    if raw is not None:
        with backup.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.chmod(backup, 0o600)
    for event,item in proposal['entries_to_add'].items():
        data.setdefault('hooks', {}).setdefault(event, []).append(item)
    if sha(script.read_bytes()) != proposal['script_sha256']:
        raise ValueError('Hook script changed; preserve backup and stop')
    if sha(Path(proposal['gate_script']).read_bytes()) != proposal['gate_sha256']:
        raise ValueError('Gate script changed; preserve backup and stop')
    replace_checked(p, raw, data)
    record['status'] = 'installed_files_only'
    record['existing_settings_changed'] = raw is not None
    record['unrelated_settings_changed'] = False
    record['after_sha256'] = sha(p.read_bytes())
    replace_checked(rec, rec.read_bytes(), record)
    return dict(record, activation='Open an ordinary fresh WorkBuddy task; restart normally only if this product version requires it. File presence alone is not activation.')


def rollback(settings, receipt):
    rec = Path(receipt).expanduser()
    if rec.is_symlink() or not rec.is_file(): raise ValueError('Use the original owned receipt')
    record = json.loads(rec.read_text(encoding='utf-8'))
    if record.get('schema') != SCHEMA or record.get('status') not in ('prepared', 'installed_files_only'):
        raise ValueError('No owned reminder installation to revert')
    p, raw, data = read_settings(settings)
    if str(p) != record.get('settings'): raise ValueError('Settings/receipt mismatch')
    installed=record.get('installed_entries',{EVENT:record['entry']})
    for event,item in installed.items():
        if data.get('hooks',{}).get(event,[]).count(item)!=1:
            raise ValueError('Owned entry changed, missing or duplicated; preserve and review')
    for event,item in installed.items():
        entries=data['hooks'][event];entries.remove(item)
        had_event=record.get('before_had_events',{}).get(event,record.get('before_had_event') if event==EVENT else False)
        if not entries and not had_event:data['hooks'].pop(event)
    if not data['hooks'] and not record.get('before_had_hooks'): data.pop('hooks')
    replace_checked(p, raw, data)
    record['status'] = 'rolled_back'
    replace_checked(rec, rec.read_bytes(), record)
    return {'status': 'rolled_back', 'later_unrelated_settings_preserved': True,
            'backup_retained': record.get('backup'), 'settings': str(p)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['plan', 'apply', 'verify', 'rollback'])
    p.add_argument('--settings', required=True)
    p.add_argument('--skill-root')
    p.add_argument('--python', default=sys.executable)
    p.add_argument('--receipt')
    a = p.parse_args()
    try:
        if a.command == 'rollback':
            if not a.receipt: raise ValueError('rollback requires the owned receipt')
            result = rollback(a.settings, a.receipt)
        else:
            if not a.skill_root: raise ValueError('A verified --skill-root is required')
            if a.command == 'apply':
                if not a.receipt: raise ValueError('apply requires a new --receipt')
                result = apply(a.settings, a.skill_root, a.python, a.receipt)
            else: result = plan(a.settings, a.skill_root, a.python)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get('status') in ('conflict', 'disabled_preserved') else 0
    except Exception as error:
        print(json.dumps({'status': 'blocked_preserved', 'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__': raise SystemExit(main())
