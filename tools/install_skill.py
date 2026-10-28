"""Add one isolated skill without overwriting existing configuration. Python 3.9+.
No settings, credentials, memory, network, subprocesses, or package installation.
The caller must identify the actual WorkBuddy skills directory first.
"""
from pathlib import Path, PurePosixPath
import argparse, hashlib, json, os, shutil, sys, uuid

NAME = 'workbuddy-quality-kit'
MARKER = '.quality-kit-owner.json'
BASE = Path(__file__).resolve().parent

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write_new(path, data):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')

def tree(path):
    files, dirs = {}, []
    if path.is_symlink(): raise ValueError('Symlink target is not supported')
    for p in path.rglob('*'):
        if p.is_symlink(): raise ValueError('Symlink inside skill is not supported')
        rel = p.relative_to(path).as_posix()
        if p.is_file(): files[rel] = digest(p)
        elif p.is_dir(): dirs.append(rel)
        else: raise ValueError('Non-regular file in skill')
    return {'files': files, 'dirs': sorted(dirs)}

def bundle(base=BASE):
    manifest = json.loads((base / 'bundle-manifest.json').read_text(encoding='utf-8'))
    expected = manifest['files']
    if manifest['skill'] != NAME or not expected: raise ValueError('Invalid bundle')
    for rel in expected:
        p = PurePosixPath(rel)
        if p.is_absolute() or '..' in p.parts or '\\' in rel or rel == MARKER:
            raise ValueError('Unsafe bundle path')
    source = base / 'skills' / NAME
    observed = tree(source)
    if observed['files'] != expected: raise ValueError('Bundle content/hash mismatch')
    return source, observed

def destination(root):
    root = Path(root).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Root must be an existing real skills directory')
    root = root.resolve()
    target = root / NAME
    if target.is_symlink(): raise ValueError('Refusing a symlink destination')
    return root, target

def plan(root, base=BASE):
    _, expected = bundle(base)
    root, target = destination(root)
    if not target.exists(): return {'status': 'add', 'target': str(target)}
    if not target.is_dir(): return {'status': 'conflict', 'reason': 'Name occupied by a file'}
    current = tree(target)
    current['files'].pop(MARKER, None)
    return {'status': 'reuse' if current == expected else 'conflict',
            'target': str(target), 'existing_files_will_be_changed': False}

def apply(root, receipt, base=BASE):
    source, expected = bundle(base)
    root, target = destination(root)
    proposal = plan(root, base)
    if proposal['status'] != 'add': return proposal
    receipt = Path(receipt).expanduser().absolute()
    if receipt.is_symlink() or receipt.exists(): raise ValueError('Receipt must be new')
    if not receipt.parent.is_dir() or receipt.parent.is_symlink(): raise ValueError('Receipt parent must exist')
    receipt = receipt.parent.resolve() / receipt.name
    if receipt.is_relative_to(root): raise ValueError('Keep receipt outside skills root')
    token = uuid.uuid4().hex
    record = {'schema': 1, 'status': 'prepared', 'root': str(root),
              'target': str(target), 'token': token, 'expected': expected}
    write_new(receipt, record)
    # Exclusive mkdir: never replace even an empty existing directory.
    target.mkdir(exist_ok=False)
    write_new(target / MARKER, {'token': token, 'receipt': str(receipt)})
    # Create only new owned directories; some managed runtimes reject mkdir on
    # existing paths even with exist_ok=True. Do not remove their safety hooks.
    for rel in sorted(expected['dirs'], key=lambda name: (name.count('/'), name)):
        (target / rel).mkdir(exist_ok=False)
    for rel, sha in expected['files'].items():
        dest = target / rel
        payload = (source / rel).read_bytes()
        if hashlib.sha256(payload).hexdigest() != sha: raise ValueError('Bundle changed during copy')
        with dest.open('xb') as f: f.write(payload)
    final = tree(target)
    expected_with_marker = {'files': dict(expected['files'], **{MARKER: digest(target / MARKER)}),
                            'dirs': expected['dirs']}
    if final != expected_with_marker: raise ValueError('Target changed during installation')
    record.update(status='installed_files_only', installed=final)
    receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'status': record['status'], 'target': str(target), 'receipt': str(receipt),
            'activation': 'Not verified. Confirm discovery/enablement and use in a new WorkBuddy task.'}

def rollback(root, receipt):
    root, target = destination(root)
    receipt = Path(receipt).resolve()
    record = json.loads(receipt.read_text(encoding='utf-8'))
    if record.get('status') != 'installed_files_only': raise ValueError('No completed owned installation to roll back')
    if record.get('root') != str(root) or record.get('target') != str(target): raise ValueError('Root/receipt mismatch')
    if not target.is_dir() or tree(target) != record['installed']:
        raise ValueError('Skill changed or contains new files; preserve it and review manually')
    marker = json.loads((target / MARKER).read_text(encoding='utf-8'))
    if marker != {'token': record['token'], 'receipt': str(receipt)}: raise ValueError('Ownership mismatch')
    retired = receipt.parent / (NAME + '-retired-' + record['token'])
    if retired.exists() or retired.is_symlink(): raise ValueError('Archive target already exists')
    # Move the unchanged owned directory; keep a recoverable copy, never delete it.
    shutil.move(str(target), str(retired))
    record.update(status='rolled_back', archived_skill=str(retired))
    receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'status': 'rolled_back', 'archive': str(retired), 'original_settings_changed': False}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['plan', 'apply', 'verify', 'rollback'])
    parser.add_argument('--root', required=True)
    parser.add_argument('--receipt')
    a = parser.parse_args()
    try:
        if a.command in ('plan', 'verify'):
            result = plan(a.root)
            if a.command == 'verify': result['files_match'] = result['status'] == 'reuse'
        else:
            if not a.receipt: raise ValueError('--receipt is required')
            result = apply(a.root, a.receipt) if a.command == 'apply' else rollback(a.root, a.receipt)
        ok = result['status'] != 'conflict' and (a.command != 'verify' or result['files_match'])
    except Exception as e:
        result, ok = {'status': 'error', 'error': str(e),
                      'action': 'Preserve existing files; inspect receipt/partial output before retrying.'}, False
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if ok else 1

if __name__ == '__main__': sys.exit(main())
