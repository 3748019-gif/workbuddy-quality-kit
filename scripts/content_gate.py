#!/usr/bin/env python3
"""Optional project-scoped, one-retry delivery-receipt gate. No semantic verdict.

`initialize` creates an owned runtime directory and prints a hooks fragment; it
never edits settings. `event` consumes a WorkBuddy command-hook JSON input.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import sys
import time
import uuid

sys.dont_write_bytecode = True
OWNER = 'workbuddy-quality-kit-content-gate-v1'
DIRECTORY = '.quality-kit-runtime'
LIMIT = 64 * 1024
INPUT_LIMIT = 256 * 1024
SCRIPT = Path(__file__).resolve()
PARTIAL = '交付回执检查未通过（partial）；最终聊天不能视为已核结论，请以已保存文件及其待确认事项为准。本回合不再自动重试。'
HINT = ('本项目启用可选交付一致性检查。复杂材料按local-review：review_request.py prepare声明全部必交路径；新Agent先只读原要求/原资料，再resume同一Agent对照全量成品。'
        '正确稿零修改；有据实质修复与漏件补齐合用一次recheck，不核后润色。使用review_request.py handoff --record RECORD --agent-id ID --register-stop从记录派生真实文件与SHA，最终直接引用reply_lines。'
        '普通文件默认中性链接回执；用户明确聊天必答或有阻断时，compare阶段以--reply-file绑定完整拟回复，不删必答或藏未完成项。'
        '普通聊天不强制；底层content_check.py独立handoff只是文件身份检查，不能代替本轮复核清单闭合。')


def encoded(value):
    data = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if len(data) > LIMIT:
        raise ValueError('Runtime state exceeds 64 KiB')
    return data


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def parse(data):
    return json.loads(data.decode('utf-8'), object_pairs_hook=unique_object)


def real_root(value):
    root = Path(value).absolute()
    if root != root.resolve(strict=True) or not root.is_dir():
        raise ValueError('Project must be an existing directory without symlink aliases')
    return root


def regular_read(path, limit=LIMIT):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise ValueError('Expected bounded regular runtime file')
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError('Runtime file changed before reading')
        data = stream.read(limit + 1)
    after = path.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if identity(before) != identity(after) or len(data) != before.st_size or len(data) > limit:
        raise ValueError('Runtime file changed while reading')
    return data


def owned(root):
    directory = root / DIRECTORY
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Project runtime owner is missing or invalid')
    owner = parse(regular_read(directory / 'owner.json'))
    if owner != {'owner': OWNER, 'project_root': str(root), 'gate_script': str(SCRIPT)}:
        raise ValueError('Project runtime belongs to another configuration')
    return directory


def write_state(path, data):
    if path.exists() or path.is_symlink():
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError('Refusing to replace a nonregular runtime file')
    payload = encoded(data)
    temp = path.parent / ('.gate-' + uuid.uuid4().hex + '.tmp')
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(payload)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def session_key(value):
    if not isinstance(value, str) or not value or len(value) > 512 or any(ord(c) < 32 for c in value):
        raise ValueError('Missing or invalid session identity')
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


@contextmanager
def session_state(root, sid):
    directory = owned(root)
    key = session_key(sid)
    path = directory / ('session-' + key + '.json')
    lock = directory / ('session-' + key + '.lock')
    descriptor = None
    for _ in range(50):
        try:
            descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            time.sleep(0.01)
    if descriptor is None:
        raise ValueError('Runtime session is busy; no automatic blocking')
    os.close(descriptor)
    try:
        value = parse(regular_read(path)) if path.exists() or path.is_symlink() else None
        if value is not None and (not isinstance(value, dict) or value.get('owner') != OWNER or value.get('session_key') != key):
            raise ValueError('Invalid session state')
        yield path, value, key
    finally:
        lock.unlink()


def initialize(value):
    if os.name != 'posix':
        raise ValueError('Optional gate initializer is validated for macOS/POSIX only; ordinary skill remains usable')
    root = real_root(value)
    directory = root / DIRECTORY
    if directory.exists() or directory.is_symlink():
        owned(root)
    else:
        directory.mkdir(mode=0o700)
        write_state(directory / 'owner.json', {'owner': OWNER, 'project_root': str(root), 'gate_script': str(SCRIPT)})
    command = ' '.join(shlex.quote(s) for s in [sys.executable, '-B', str(SCRIPT), 'event', '--project-root', str(root)])
    return {'project_root': str(root), 'settings_file': str(root / '.codebuddy' / 'settings.local.json'),
            'merge_only': True, 'hooks': {event: [{'hooks': [{'type': 'command', 'command': command, 'timeout': 5}]}]
                                        for event in ('UserPromptSubmit', 'Stop')},
            'scope': 'macOS/POSIX fragment only; existing settings and hooks were not changed. Gate is inactive until receipt registration.'}


def locate_project(artifact_root):
    root = real_root(artifact_root)
    owned(root)
    return root


def validate_receipt(root, receipt):
    if not isinstance(receipt, dict) or receipt.get('proof') != 'saved_artifact_identity_not_semantic_acceptance':
        raise ValueError('Expected a real handoff receipt')
    files = receipt.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= 12:
        raise ValueError('Invalid receipt files')
    names, hashes = [], []
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get('path'), str):
            raise ValueError('Invalid receipt path')
        path = Path(item['path'])
        if not path.is_absolute() or not path.is_relative_to(root):
            raise ValueError('Receipt artifact escapes project')
        names.append(str(path.relative_to(root)))
        hashes.append(item.get('sha256'))
    reply = receipt.get('reply_source')
    reply_file = reply_root = None
    if reply is not None:
        if not isinstance(reply, dict) or set(reply) != {'path', 'sha256', 'output_root'} or reply.get('path') != files[-1]['path'] or reply.get('sha256') != hashes[-1]:
            raise ValueError('Saved reply identity must match the final checked file')
        reply_file, reply_root = names.pop(), reply['output_root']
    # Rebuild replies from actual files; stored free text is not authority.
    from content_check import handoff
    try:
        actual = handoff(str(root), names, hashes, reply_file, reply_root)
    except Exception as error:
        # Includes parser/container failures from supported document formats.
        # A malformed artifact must not crash the command hook without a status.
        raise ValueError('Artifact version or supported format could not be rechecked') from error
    if receipt.get('reply_lines') != actual['reply_lines']:
        raise ValueError('Receipt text is not generated from its actual artifacts')
    return actual


def register(artifact_root, receipt, session_id=None, generation_id=None):
    root = locate_project(artifact_root)
    sid = session_id if session_id is not None else os.environ.get('CODEBUDDY_SESSION_ID')
    generation = generation_id if generation_id is not None else os.environ.get('CODEBUDDY_CONVERSATION_REQUEST_ID')
    with session_state(root, sid) as (path, state, key):
        if not state or state.get('opted_out') or state.get('generation_key') != session_key(generation):
            raise ValueError('No active eligible user turn; receipt was not registered')
        actual = validate_receipt(root, receipt)
        if len(encoded(actual)) > 12 * 1024:
            raise ValueError('Receipt exceeds 12 KiB; not registered')
        result = {'status': 'armed', 'turn': state['turn'], 'attempts_used': state['attempts'],
                  'state_file': str(path), 'proof': 'receipt_registered_not_semantic_acceptance'}
        if len(encoded(result)) > 768:
            raise ValueError('Registration metadata exceeds output bounds; use a shorter project path. Not registered')
        state['receipt'] = actual
        state['status'] = 'armed'
        # attempts deliberately survives re-registration in the same user turn.
        write_state(path, state)
        return result


def receipt_text_matches(text, expected_lines):
    """Allow only inert spacing and two literal spellings of known safe links.

    No general Markdown parsing, URL decoding or target inference: alternatives
    are derived from the tool's actual receipt, never from assistant text.
    """
    lines = []
    for line in text.replace('\r\n', '\n').split('\n'):
        if not line.strip():
            continue
        stripped = line.lstrip(' ')
        # Four spaces or a tab can create a Markdown code block rather than a
        # clickable receipt. Do not treat that as nonsemantic whitespace.
        if len(line) - len(stripped) > 3 or stripped.startswith('\t'):
            return False
        lines.append(stripped.rstrip(' \t'))
    if len(lines) != len(expected_lines):
        return False
    for actual, expected in zip(lines, expected_lines):
        if actual == expected:
            continue
        if not expected.startswith('- [') or not expected.endswith('>)') or '](<' not in expected:
            return False
        prefix, target = expected.rsplit('](<', 1)
        target = target[:-2]
        unsafe = '()<>[]\\`"\''
        if not target.startswith('/') or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 or ch in unsafe for ch in target):
            return False
        if actual != prefix + '](' + target + ')':
            return False
    return True


def saved_reply_matches(text, expected):
    # Preserve indentation, table/code-block spacing and all interior blank lines.
    # Only line endings and blank outer lines are presentation-normalized.
    def normalize(value):
        lines = value.replace('\r\n', '\n').split('\n')
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        return '\n'.join(lines)
    return normalize(text) == normalize(expected)


def event(root_value, request):
    root = real_root(root_value)
    owned(root)
    if not isinstance(request, dict) or request.get('hook_event_name') not in ('UserPromptSubmit', 'Stop'):
        return 0, {'gate_status': 'inactive', 'reason': 'unrelated_event'}, ''
    if not isinstance(request.get('cwd'), str) or Path(request['cwd']).resolve() != root:
        return 0, {'gate_status': 'inactive', 'reason': 'other_project'}, ''
    if request['hook_event_name'] == 'UserPromptSubmit' and request.get('is_internal_continuation') is True:
        return 0, {'gate_status': 'unchanged', 'reason': 'internal_continuation'}, ''
    generation = session_key(request.get('generation_id'))
    with session_state(root, request.get('session_id')) as (path, state, key):
        if request['hook_event_name'] == 'UserPromptSubmit':
            if state and state.get('generation_key') == generation:
                return 0, {'gate_status': 'unchanged', 'reason': 'same_generation'}, ''
            prompt = request.get('prompt', '')
            optout = isinstance(prompt, str) and '[quality:off]' in prompt
            state = {'owner': OWNER, 'session_key': key, 'turn': uuid.uuid4().hex,
                     'generation_key': generation,
                     'started_at_ns': time.time_ns(), 'attempts': 0, 'receipt': None,
                     'status': 'opted_out' if optout else 'not_armed', 'opted_out': optout}
            write_state(path, state)
            output = {'gate_status': state['status']}
            if not optout:
                output['hookSpecificOutput'] = {'hookEventName': 'UserPromptSubmit', 'additionalContext': HINT}
            return 0, output, ''
        if state and state.get('generation_key') != generation:
            return 0, {'gate_status': 'inactive', 'reason': 'other_generation'}, ''
        if not state or state.get('opted_out') or not state.get('receipt'):
            return 0, {'gate_status': 'inactive', 'reason': 'no_registered_receipt'}, ''
        if state.get('status') == 'partial':
            return 0, {'gate_status': 'partial', 'systemMessage': PARTIAL}, ''
        if type(state.get('attempts')) is not int or state['attempts'] not in (0, 1):
            raise ValueError('Invalid retry state')
        try:
            actual = validate_receipt(root, state['receipt'])
            expected = '\n'.join(actual['reply_lines'])
            text = request.get('last_assistant_message')
            valid = isinstance(text, str) and (saved_reply_matches(text, expected) if 'reply_source' in actual else receipt_text_matches(text, actual['reply_lines']))
            reason = 'reply_changed' if not valid else 'matched'
        except (OSError, ValueError, TypeError, KeyError) as error:
            valid, reason, expected = False, 'artifact_or_receipt_changed', ''
        if valid:
            state['status'] = 'matched'
            write_state(path, state)
            return 0, {'gate_status': 'matched', 'proof': 'reply_and_artifact_identity_only'}, ''
        if state['attempts'] == 0:
            state.update(attempts=1, status='correction_requested', last_reason=reason)
            write_state(path, state)
            feedback = ('交付一致性检查：最终聊天添加或改变了未登记内容。请直接发送以下已保存回复，不新增解释：\n' + expected
                        if expected else '交付回执对应文件或记录已改变。请按原资料重新核对受影响内容，再调用 handoff --register-stop 登记实际最终文件，直接引用回执。不要以此工具代替语义核验。')
            return 2, {}, feedback
        state.update(status='partial', last_reason=reason)
        write_state(path, state)
        return 0, {'gate_status': 'partial', 'systemMessage': PARTIAL}, ''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['initialize', 'event'])
    parser.add_argument('--project-root', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'initialize':
            print(json.dumps(initialize(args.project_root), ensure_ascii=False, indent=2))
            return 0
        payload = sys.stdin.buffer.read(INPUT_LIMIT + 1)
        if len(payload) > INPUT_LIMIT:
            raise ValueError('Hook input exceeds 256 KiB')
        code, output, feedback = event(args.project_root, parse(payload))
        if output:
            print(json.dumps(output, ensure_ascii=False))
        if feedback:
            print(feedback, file=sys.stderr)
        return code
    except (OSError, ValueError, TypeError, KeyError) as error:
        if args.command == 'event':
            # Fail open without claiming acceptance, and without disclosing paths
            # or original prompts from malformed inputs in a user-facing error.
            print(json.dumps({'gate_status': 'unavailable', 'systemMessage': '交付回执检查不可用；本次未获得回执一致性验证。'}, ensure_ascii=False))
            return 0
        print(json.dumps({'error': str(error), 'registered': False}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
