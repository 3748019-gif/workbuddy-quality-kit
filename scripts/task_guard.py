"""Small local checks for task boundaries and saved deliverables. Python 3.9+.
No network, settings, memory, package installation, or permission changes.
Passing these checks does not establish business correctness or visual fidelity.
"""
from pathlib import Path
import argparse, hashlib, json, os, stat, sys, tempfile, zipfile
import xml.etree.ElementTree as ET


def digest(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for part in iter(lambda: f.read(1048576), b''): h.update(part)
    return h.hexdigest()


def within(root, path):
    root = Path(root).resolve(strict=True)
    raw = Path(path)
    if not raw.is_absolute(): raw = root / raw
    resolved = raw.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ValueError('Path escapes task root: ' + str(path))
    return raw.absolute(), resolved


def check_separation(inputs, outputs, root=None):
    if root is not None: root = Path(root).resolve(strict=True)
    def locate(p):
        q = Path(p)
        return Path(root) / q if root is not None and not q.is_absolute() else q
    ins = [locate(p).resolve(strict=True) for p in inputs]
    outs = [locate(p) for p in outputs]
    resolved = []
    for p in outs:
        q = p.resolve(strict=False)
        if root is not None: within(root, p)
        for src in ins:
            if q == src or (src.is_dir() and q.is_relative_to(src)):
                raise ValueError('Output aliases or enters a protected input: ' + str(p))
            if p.exists() and src.is_file() and p.samefile(src):
                raise ValueError('Output is a hard-link alias of an input: ' + str(p))
            if p.is_file() and src.is_dir():
                # A directory input also protects its regular descendants.
                # Walk without following directory links; inspect inode aliases
                # only for an already-existing output, avoiding content reads.
                identity = (p.stat().st_dev, p.stat().st_ino)
                for folder, _, names in os.walk(src, followlinks=False):
                    for name in names:
                        child = Path(folder) / name
                        if child.is_symlink() or not child.is_file(): continue
                        info = child.stat()
                        if (info.st_dev, info.st_ino) == identity:
                            raise ValueError('Output aliases a file in a protected input directory: ' + str(p))
        for old in resolved:
            if q == old or (q.exists() and old.exists() and q.samefile(old)):
                raise ValueError('Outputs alias one another: ' + str(p))
        resolved.append(q)
    return resolved


def atomic_write(path, payload, *, inputs, root=None, validate=None):
    """Publish one byte payload after validation; leave existing output on failure.
    Caller supplies every protected input. Not a multi-file transaction or a
    defense against another process racing filesystem changes.
    """
    if not isinstance(payload, bytes): raise TypeError('payload must be bytes')
    raw = within(root, path)[0] if root is not None else Path(path)
    target = check_separation(inputs, [raw], root)[0]
    if raw.is_symlink(): raise ValueError('Refuse replacing a symlink output')
    if target.exists() and not target.is_file(): raise ValueError('Output must be a file')
    if not target.parent.is_dir(): raise ValueError('Output parent must already exist')
    mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
    fd, name = tempfile.mkstemp(prefix='.task-candidate-', dir=str(target.parent))
    candidate = Path(name)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(payload); f.flush(); os.fsync(f.fileno())
        if validate is not None: validate(candidate)
        check_separation(inputs, [raw], root)
        if raw.is_symlink(): raise ValueError('Output changed to symlink')
        if mode is not None: os.chmod(candidate, mode)
        os.replace(candidate, target)
    finally:
        if candidate.exists(): candidate.unlink()


def snapshot(root, paths):
    root = Path(root).resolve(strict=True)
    if not paths: raise ValueError('At least one protected input is required')
    result = {}
    def visit(p):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            result[rel] = {'kind': 'link', 'target': os.readlink(p)}
        elif p.is_dir():
            result[rel] = {'kind': 'directory'}
            for child in sorted(p.iterdir()): visit(child)
        elif p.is_file(): result[rel] = {'kind': 'file', 'sha256': digest(p)}
        else: raise ValueError('Missing or non-regular input: ' + rel)
    for value in paths:
        p = Path(value)
        if p.is_absolute() or '..' in p.parts: raise ValueError('Use task-relative input paths')
        raw = root / p
        # Do not follow a link itself, and reject links in its parent chain.
        if not raw.parent.resolve().is_relative_to(root): raise ValueError('Input parent escapes root')
        visit(raw)
    return {'schema': 1, 'paths': list(paths), 'entries': result}


def inspect_file(p):
    p = Path(p)
    if not p.is_file() or p.is_symlink(): raise ValueError('Required regular file missing: ' + str(p))
    if p.stat().st_size == 0: raise ValueError('Required deliverable is empty: ' + str(p))
    if p.suffix.lower() == '.json':
        def bad(x): raise ValueError('Non-finite JSON constant: ' + x)
        json.loads(p.read_text(encoding='utf-8'), parse_constant=bad)
    elif p.suffix.lower() in ('.docx', '.xlsx', '.pptx'):
        with zipfile.ZipFile(p) as z:
            if z.testzip() is not None: raise ValueError('Invalid ZIP member')
            required = {'.docx':'word/document.xml','.xlsx':'xl/workbook.xml','.pptx':'ppt/presentation.xml'}[p.suffix.lower()]
            if required not in z.namelist(): raise ValueError('Missing Office main part')
            for name in z.namelist():
                if name.endswith(('.xml', '.rels')): ET.fromstring(z.read(name))
    return {'bytes': p.stat().st_size, 'sha256': digest(p)}


def verify(root, state, required):
    root = Path(root).resolve(strict=True)
    if state.get('schema') != 1 or not isinstance(state.get('entries'), dict) or not state['entries']:
        raise ValueError('Invalid snapshot schema')
    current = snapshot(root, state['paths'])
    changed = sorted(k for k in set(current['entries']) | set(state['entries'])
                     if current['entries'].get(k) != state['entries'].get(k))
    results, errors = {}, []
    for rel in required:
        try:
            raw, resolved = within(root, rel)
            check_separation([Path(root)/p for p in state['paths']], [raw], root)
            results[rel] = inspect_file(raw)
        except Exception as e: errors.append({'path': rel, 'error': str(e)})
    return {'passed': not changed and not errors, 'changed_inputs': changed,
            'deliverables': results, 'errors': errors,
            'limits': 'Checks input preservation, required files and basic parsing only; not facts, formulas, visual layout, or completeness of unspecified requirements.'}


def _relative_name(name):
    if not isinstance(name, str) or not name or '\\' in name:
        raise ValueError('Use a nonempty task-relative path')
    p = Path(name)
    if p.is_absolute() or '..' in p.parts or p.as_posix() != name or name == '.':
        raise ValueError('Use canonical task-relative paths without parent traversal')
    return name


def _dependencies(outputs, dependencies):
    if not isinstance(dependencies, dict) or set(dependencies) != set(outputs):
        raise ValueError('Dependency map must cover exactly the tracked outputs')
    for name, sources in dependencies.items():
        _relative_name(name)
        if not isinstance(sources, list) or not sources:
            raise ValueError('Each output requires at least one dependency')
        for source in sources: _relative_name(source)
    visiting, done = set(), set()
    def visit(name):
        if name in visiting: raise ValueError('Cyclic output dependencies')
        if name in done or name not in dependencies: return
        visiting.add(name)
        for source in dependencies[name]: visit(source)
        visiting.remove(name); done.add(name)
    for name in dependencies: visit(name)
    return dependencies


def checkpoint(root, inputs, outputs, dependencies):
    """Describe saved versions. This function is read-only and does not certify QA."""
    root = Path(root).resolve(strict=True)
    for name in list(inputs) + list(outputs): _relative_name(name)
    if len(set(inputs)) != len(inputs) or len(set(outputs)) != len(outputs):
        raise ValueError('Duplicate tracked paths')
    dependencies = _dependencies(outputs, dependencies)
    for sources in dependencies.values():
        for source in sources:
            if source not in outputs and not any(source == p or source.startswith(p+'/') for p in inputs):
                raise ValueError('Dependency is outside tracked inputs/outputs: ' + source)
    state = snapshot(root, inputs)
    check_separation([root/p for p in inputs], [root/p for p in outputs], root)
    saved = {name: inspect_file(within(root, name)[0]) for name in outputs}
    return {'schema': 2, 'inputs': state, 'outputs': saved,
            'dependencies': dependencies,
            'limits': 'Version evidence only. Saved does not mean verified, and changed outputs must be reviewed before replacement.'}


def resume(root, state):
    """Compare checkpoint versions and report affected outputs; never repair files."""
    root = Path(root).resolve(strict=True)
    if state.get('schema') != 2 or not isinstance(state.get('outputs'), dict) or not state['outputs']:
        raise ValueError('Invalid checkpoint schema')
    previous = state.get('inputs', {})
    if previous.get('schema') != 1 or not isinstance(previous.get('entries'), dict) or not previous['entries']:
        raise ValueError('Invalid input version evidence')
    inputs = previous.get('paths')
    if not isinstance(inputs, list) or not inputs: raise ValueError('Missing tracked inputs')
    outputs = list(state['outputs'])
    for name in inputs + outputs + list(previous['entries']): _relative_name(name)
    dependencies = _dependencies(outputs, state.get('dependencies'))
    for sources in dependencies.values():
        for source in sources:
            if source not in outputs and not any(source == p or source.startswith(p+'/') for p in inputs):
                raise ValueError('Dependency is outside tracked inputs/outputs: ' + source)
    check_separation([root/p for p in inputs if (root/p).exists()], [root/p for p in outputs], root)
    # Missing tracked inputs are a change, not permission to restore old files.
    present, missing_inputs = [], []
    for name in inputs:
        if (root/name).exists() or (root/name).is_symlink(): present.append(name)
        else: missing_inputs.append(name)
    current = snapshot(root, present)['entries'] if present else {}
    changed = sorted(k for k in set(current) | set(previous['entries'])
                     if current.get(k) != previous['entries'].get(k))
    modified, missing, errors = [], [], []
    for name, old in state['outputs'].items():
        raw, _ = within(root, name)
        if not raw.exists(): missing.append(name); continue
        try:
            if inspect_file(raw) != old: modified.append(name)
        except Exception as e: errors.append({'path': name, 'error': str(e)})
    affected = set()
    frontier = set(changed + missing_inputs + modified + missing + [e['path'] for e in errors])
    while True:
        new = {name for name, sources in dependencies.items() if any(
            source == item or source.startswith(item+'/') or item.startswith(source+'/')
            for source in sources for item in frontier)} - affected
        if not new: break
        affected.update(new); frontier.update(new)
    return {'passed': not (changed or missing_inputs or modified or missing or errors),
            'changed_inputs': changed, 'missing_inputs': missing_inputs,
            'modified_outputs_preserve_and_review': sorted(modified),
            'missing_outputs': sorted(missing), 'output_errors': errors,
            'recheck_outputs': sorted(affected),
            'limits': 'Read-only comparison, not a semantic check or automatic merge. Preserve manual edits; do not restore deleted files without current task justification.'}


_COHORT_TYPE = 'workbuddy-quality-cohort-v1'
_ACTIVE = 'quality-publish-active.json'


def _fingerprint(path):
    if path.is_symlink(): raise ValueError('Symlink in publication state or output')
    if not path.exists(): return None
    if not path.is_file(): raise ValueError('Publication requires regular files')
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o7000: raise ValueError('Special permission bits require manual review')
    return {'sha256': digest(path), 'mode': mode}


def review_outputs(root, names):
    """Record versions before reading/merging human edits in existing outputs.
    These outputs may intentionally be replaced later; this is a precondition
    record, not permission to overwrite or a semantic text-merge operation.
    """
    root=Path(root).resolve(strict=True)
    if not isinstance(names,list) or not names or len(set(names))!=len(names):
        raise ValueError('List each reviewed output exactly once')
    entries={}
    for name in names:
        raw,resolved=within(root,_relative_name(name))
        if raw!=resolved:raise ValueError('Reviewed output must not use symlink aliases')
        if any(name.casefold()==old.casefold() for old in entries):
            raise ValueError('Ambiguous portable reviewed-output names')
        entries[name]=_fingerprint(raw)
    return {'schema':'reviewed-outputs/1','paths':list(names),'entries':entries}


def _publication_paths(root, names, inputs, workdir):
    if not names or len(set(names)) != len(names): raise ValueError('Empty or duplicate publication set')
    workdir = within(root, _relative_name(workdir))[0]
    if workdir.resolve() != workdir or not workdir.is_dir():
        raise ValueError('Publication work directory must already exist without symlinks')
    targets = {}
    for name in names:
        raw, resolved = within(root, _relative_name(name))
        if raw != resolved or not raw.parent.is_dir():
            raise ValueError('Output parent must exist without symlinks')
        if resolved.is_relative_to(workdir): raise ValueError('Keep outputs outside publication work directory')
        if raw.parent.stat().st_dev != workdir.stat().st_dev:
            raise ValueError('Publication/recovery must use one filesystem')
        _fingerprint(raw)
        for other in targets.values():
            if raw.parent.samefile(other.parent) and raw.name.casefold() == other.name.casefold():
                raise ValueError('Ambiguous portable output names')
        targets[name] = raw
    # Missing inputs still reserve their original paths during a rollback.
    for source in inputs:
        path = within(root, _relative_name(source))[1]
        if any(p == path or p.is_relative_to(path) for p in targets.values()):
            raise ValueError('Output overlaps a protected input path')
    present = [root/n for n in inputs if (root/n).exists()]
    check_separation(present, list(targets.values()) + [workdir/_ACTIVE], root)
    return targets, workdir


def _write_publication_json(path, value, root, inputs):
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode('utf-8'),
                 inputs=[root/n for n in inputs if (root/n).exists()], root=root)


def _read_active(root, workdir):
    active = workdir/_ACTIVE
    if not active.exists() and not active.is_symlink(): return None
    _fingerprint(active)
    value = json.loads(active.read_text(encoding='utf-8'))
    if value.get('type') != _COHORT_TYPE: raise ValueError('Preserve unknown publication marker')
    journal = within(root, _relative_name(value.get('journal')))[0]
    if journal.parent.parent != workdir or journal.name != 'state.json':
        raise ValueError('Publication marker points outside its work directory')
    return journal


def _load_publication(root, journal):
    journal = within(root, _relative_name(journal))[0]
    if journal.resolve() != journal or journal.name != 'state.json' or not journal.parent.name.startswith('publish-'):
        raise ValueError('Invalid publication journal path')
    _fingerprint(journal)
    value = json.loads(journal.read_text(encoding='utf-8'))
    if (value.get('type') != _COHORT_TYPE or value.get('generation') != journal.parent.name
            or value.get('state') not in ('prepared','committed','rolled_back')
            or value.get('validated') is not True):
        raise ValueError('Invalid publication journal')
    entries = value.get('entries')
    if not isinstance(entries, list) or not entries: raise ValueError('Missing publication entries')
    inputs = value.get('inputs', {}).get('paths')
    if not isinstance(inputs, list) or not inputs: raise ValueError('Missing protected inputs')
    targets, workdir = _publication_paths(root, [e['name'] for e in entries], inputs,
                                         journal.parent.parent.relative_to(root).as_posix())
    for i, entry in enumerate(entries):
        for key, folder in [('new','candidate'),('old','previous')]:
            info = entry.get(key)
            if key == 'old' and info is None: continue
            if (not isinstance(info, dict) or set(info) != {'sha256','mode'}
                    or not isinstance(info['sha256'],str) or len(info['sha256']) != 64
                    or any(c not in '0123456789abcdef' for c in info['sha256'])
                    or type(info['mode']) is not int or not 0 <= info['mode'] <= 0o777):
                raise ValueError('Invalid saved publication fingerprint')
            saved = journal.parent/folder/(f'{i:04d}-'+Path(entry['name']).name)
            if saved.resolve() != saved or _fingerprint(saved) != info:
                raise ValueError('Saved publication cohort changed or is missing')
    return journal, value, targets, workdir


def _publish_one(target, saved, *, root, inputs):
    # Kept separate so tests can interrupt only this operation, without patching
    # managed-runtime safety hooks or process-global filesystem functions.
    atomic_write(target, saved.read_bytes(), inputs=[root/n for n in inputs if (root/n).exists()], root=root)


def recover_set(root, journal, action='status'):
    """Inspect or finish/roll back a prepared cohort; never overwrite later edits.
    This is process-interruption recovery, not simultaneous multi-file visibility,
    power-loss durability, automatic human-text merging or a version-control tool.
    """
    root = Path(root).resolve(strict=True)
    if action not in ('status','commit','rollback'): raise ValueError('Unknown recovery action')
    journal, value, targets, workdir = _load_publication(root, journal)
    def allowed(entry):
        if value['state'] == 'committed': return (entry['new'],)
        if value['state'] == 'rolled_back': return (entry['old'],)
        return (entry['old'],entry['new'])
    conflicts = [e['name'] for e in value['entries']
                 if _fingerprint(targets[e['name']]) not in allowed(e)]
    try:
        input_check = verify(root, value['inputs'], [])
        input_changes = input_check['changed_inputs']
    except Exception as error: input_changes = ['unavailable: '+str(error)]
    if action != 'status':
        if conflicts: raise ValueError('Later output edits preserved; review before recovery: '+', '.join(conflicts))
        active = _read_active(root, workdir)
        if active != journal: raise ValueError('Only the active pending publication can recover')
        desired = 'committed' if action == 'commit' else 'rolled_back'
        if value['state'] != 'prepared':
            if value['state'] != desired: raise ValueError('Completed generations are not an automatic undo operation')
        else:
            if action == 'commit' and input_changes:
                raise ValueError('Inputs changed; preserve candidate and review instead of committing stale results')
            for i, entry in enumerate(value['entries']):
                target = targets[entry['name']]
                # Check again before each write, including changes made after preflight.
                current = _fingerprint(target)
                if current not in (entry['old'],entry['new']): raise ValueError('Later output edit preserved')
                info = entry['new'] if action == 'commit' else entry['old']
                if current == info: continue
                if info is None:
                    retired = journal.parent/'retired'/(f'{i:04d}-'+target.name)
                    if retired.exists() or retired.is_symlink(): raise ValueError('Retired file already exists; preserve and review')
                    os.replace(target, retired)  # archive only this known newly-created output
                else:
                    folder = 'candidate' if action == 'commit' else 'previous'
                    saved = journal.parent/folder/(f'{i:04d}-'+target.name)
                    _publish_one(target, saved, root=root, inputs=value['inputs']['paths'])
                    if _fingerprint(target) != info: raise ValueError('Published file differs from saved cohort')
            expected_key = 'new' if action == 'commit' else 'old'
            if any(_fingerprint(targets[e['name']]) != e[expected_key] for e in value['entries']):
                raise ValueError('Final cohort changed during publication; preserve and review')
            try: input_changes = verify(root, value['inputs'], [])['changed_inputs']
            except Exception as error: input_changes = ['unavailable: '+str(error)]
            if action == 'commit' and input_changes:
                raise ValueError('Inputs changed during publication; candidate is stale')
            value['state'] = desired
            _write_publication_json(journal, value, root, value['inputs']['paths'])
    return {'passed': not conflicts and (value['state'] != 'prepared') and not input_changes,
            'state': value['state'], 'journal': journal.relative_to(root).as_posix(),
            'conflicts_preserved': conflicts, 'changed_inputs': input_changes,
            'recovery_needed': value['state'] == 'prepared',
            'limits': 'Complete saved generations and explicit recovery, not crash-atomic visibility, semantic QA or power-loss certification.'}


def publish_set(root, payloads, *, inputs, workdir, validate, input_state=None, output_state=None):
    """Validate a complete candidate and retain an on-disk previous generation.
    Inputs/outputs/workdir are canonical task-relative paths; all output parents
    and workdir must already exist. validate(mapping_of_names_to_saved_paths)
    must return True. Keep one workdir per publication stream. Generation files
    are retained, never bulk-cleaned. A pending journal blocks later publication.
    """
    root = Path(root).resolve(strict=True)
    if not isinstance(payloads, dict) or not payloads or not callable(validate):
        raise ValueError('A nonempty byte-payload mapping and validation callback are required')
    if not isinstance(inputs,list) or not inputs: raise ValueError('List every protected input')
    if any(not isinstance(p,bytes) for p in payloads.values()): raise TypeError('Payloads must be bytes')
    names = sorted(payloads)
    targets, workdir = _publication_paths(root, names, inputs, workdir)
    for name in inputs:
        raw, resolved = within(root, _relative_name(name))
        if raw != resolved: raise ValueError('Publication input aliases require explicit review')
    state = input_state if input_state is not None else snapshot(root, inputs)
    if state.get('paths') != inputs or any(e.get('kind')=='link' for e in state.get('entries',{}).values()):
        raise ValueError('Input evidence must cover the same regular input set')
    if not verify(root, state, [])['passed']: raise ValueError('Inputs changed since computation began')
    active = _read_active(root, workdir)
    if active is not None:
        _, previous, _, _ = _load_publication(root, active.relative_to(root).as_posix())
        if previous['state'] == 'prepared': raise ValueError('Recover pending publication first: '+str(active.relative_to(root)))
    before = {n:_fingerprint(p) for n,p in targets.items()}
    if output_state is not None:
        if (not isinstance(output_state,dict) or output_state.get('schema')!='reviewed-outputs/1'
                or not isinstance(output_state.get('paths'),list) or not output_state['paths']
                or len(set(output_state['paths']))!=len(output_state['paths'])
                or not isinstance(output_state.get('entries'),dict)
                or set(output_state['entries'])!=set(output_state['paths'])
                or not set(output_state['paths']).issubset(targets)):
            raise ValueError('Reviewed output evidence must cover actual publication targets')
        changed=[n for n in output_state['paths'] if output_state['entries'][n]!=before[n]]
        if changed:
            raise ValueError('Outputs changed since review; preserve later edits: '+', '.join(changed))
    if all(before[n] is not None and before[n]['sha256']==hashlib.sha256(payloads[n]).hexdigest() for n in names):
        if validate(targets) is not True: raise ValueError('Saved-output validation did not return True')
        if not verify(root, state, [])['passed']: raise ValueError('Inputs changed during validation')
        if any(_fingerprint(targets[n])!=before[n] for n in names): raise ValueError('Output changed during validation')
        return {'passed':True,'state':'unchanged','journal':None,'recovery_needed':False}
    generation = Path(tempfile.mkdtemp(prefix='publish-', dir=workdir))
    for folder in ('candidate','previous','retired'): (generation/folder).mkdir()
    entries, candidates = [], {}
    for i,name in enumerate(names):
        candidate = generation/'candidate'/(f'{i:04d}-'+Path(name).name)
        atomic_write(candidate, payloads[name], inputs=[root/p for p in inputs], root=root)
        mode = before[name]['mode'] if before[name] is not None else 0o600
        if os.name != 'nt' and stat.S_IMODE(candidate.stat().st_mode) != mode: os.chmod(candidate,mode)
        old = before[name]
        if old is not None:
            saved = generation/'previous'/candidate.name
            atomic_write(saved, targets[name].read_bytes(), inputs=[root/p for p in inputs], root=root)
            if os.name != 'nt' and stat.S_IMODE(saved.stat().st_mode) != old['mode']: os.chmod(saved,old['mode'])
            if _fingerprint(saved) != old: raise ValueError('Output changed while saving prior generation')
        entries.append({'name':name,'old':old,'new':_fingerprint(candidate)})
        candidates[name] = candidate
    if validate(candidates) is not True: raise ValueError('Candidate validation did not return True')
    if any(_fingerprint(candidates[e['name']]) != e['new'] for e in entries):
        raise ValueError('Validation must not modify candidate files')
    if not verify(root, state, [])['passed']: raise ValueError('Inputs changed during candidate validation')
    if any(_fingerprint(targets[n])!=before[n] for n in names): raise ValueError('Output changed during preparation; preserve and review')
    value = {'type':_COHORT_TYPE,'generation':generation.name,'state':'prepared',
             'validated':True,'inputs':state,'entries':entries}
    journal = generation/'state.json'
    _write_publication_json(journal,value,root,inputs)
    _write_publication_json(workdir/_ACTIVE,{'type':_COHORT_TYPE,'journal':journal.relative_to(root).as_posix()},root,inputs)
    try:
        return recover_set(root,journal.relative_to(root).as_posix(),'commit')
    except Exception as error:
        try:
            result = recover_set(root,journal.relative_to(root).as_posix(),'rollback')
            state_text = result['state']
        except Exception: state_text = 'prepared; explicit recovery/review required'
        raise RuntimeError('Publication failed; '+state_text+'; journal '+journal.relative_to(root).as_posix()) from error


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('snapshot'); s.add_argument('--root', required=True); s.add_argument('--inputs', nargs='+', required=True)
    v = sub.add_parser('verify'); v.add_argument('--root', required=True); v.add_argument('--state', required=True); v.add_argument('--require', nargs='+', required=True)
    a = sub.add_parser('paths'); a.add_argument('--root', required=True); a.add_argument('--input', nargs='+', required=True); a.add_argument('--output', nargs='+', required=True)
    c = sub.add_parser('checkpoint'); c.add_argument('--root', required=True); c.add_argument('--inputs', nargs='+', required=True); c.add_argument('--outputs', nargs='+', required=True); c.add_argument('--dependencies', required=True)
    r = sub.add_parser('resume'); r.add_argument('--root', required=True); r.add_argument('--state', required=True)
    g = sub.add_parser('recover'); g.add_argument('--root', required=True); g.add_argument('--journal', required=True); g.add_argument('--action', choices=['status','commit','rollback'], default='status')
    q = sub.add_parser('review'); q.add_argument('--root', required=True); q.add_argument('--outputs', nargs='+', required=True)
    args = p.parse_args()
    try:
        if args.command == 'snapshot': result = snapshot(args.root, args.inputs)
        elif args.command == 'verify':
            raw, _ = within(args.root, args.state)
            result = verify(args.root, json.loads(raw.read_text(encoding='utf-8')), args.require)
        elif args.command == 'checkpoint':
            raw, _ = within(args.root, args.dependencies)
            result = checkpoint(args.root, args.inputs, args.outputs, json.loads(raw.read_text(encoding='utf-8')))
        elif args.command == 'resume':
            raw, _ = within(args.root, args.state)
            result = resume(args.root, json.loads(raw.read_text(encoding='utf-8')))
        elif args.command == 'recover': result = recover_set(args.root,args.journal,args.action)
        elif args.command == 'review': result = review_outputs(args.root,args.outputs)
        else:
            inputs = [within(args.root, x)[0] for x in args.input]
            outputs = [within(args.root, x)[0] for x in args.output]
            result = {'passed': True, 'outputs': [str(x) for x in check_separation(inputs, outputs, args.root)]}
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result.get('passed',True) else 1
    except Exception as e:
        print(json.dumps({'passed':False,'error':str(e)},ensure_ascii=False)); return 1

if __name__ == '__main__': sys.exit(main())
