"""Local PreToolUse loading check. Never grants a tool permission.

Read only the current transcript supplied by WorkBuddy and this skill's own
instructions. Keep no prompt, transcript copy, personal memory or state file.
Unknown product formats fail open with a short reminder to avoid a deadlock.
"""
from pathlib import Path
import ast, json, re, sys

TOOLS = {'Bash', 'Write', 'Edit', 'MultiEdit'}


def text_output(value):
    if isinstance(value, str):
        if value.startswith(('{', '[')):
            try: value = json.loads(value)
            except ValueError:
                try: value = ast.literal_eval(value)
                except (ValueError, SyntaxError, MemoryError, RecursionError): return value
        else: return value
    if isinstance(value, dict):
        if value.get('isError') is True: return ''
        if value.get('type') in ('text', 'input_text', 'output_text'): return value.get('text', '')
        return text_output(value.get('content', ''))
    if isinstance(value, list): return '\n'.join(text_output(v) for v in value)
    return ''


def instruction_body(path):
    text = path.read_text(encoding='utf-8')
    if text.startswith('---\n'):
        text = text.split('---\n', 2)[-1]
    return text.strip()


def loading_proof(transcript, required):
    p = Path(transcript)
    if p.suffix != '.jsonl' or 'projects' not in p.parts or not p.is_file() or p.is_symlink():
        return None
    calls, proven, recognized, user_opt_out = {}, set(), False, False
    with p.open('rb') as f:
        f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 4*1024*1024))
        if size > 4*1024*1024: f.readline()
        for line in f:
            try: d = json.loads(line)
            except (ValueError, UnicodeError): continue
            if not isinstance(d, dict): continue
            typ = d.get('type')
            if typ == 'session-meta' and d.get('sessionId'): recognized = True
            if typ == 'message' and d.get('role') == 'user':
                recognized = True
                user_text = text_output(d.get('content', ''))
                if '<user_query>' in user_text:
                    user_text = user_text.rsplit('<user_query>',1)[-1].rsplit('</user_query>',1)[0]
                user_text=user_text.lstrip()
                user_opt_out = user_text.startswith('[quality:off]') or bool(re.match(
                    r'^(?:(?:本次|这次|本轮|当前任务)[，,：:]?)?\s*(?:请)?(?:不要|不用|跳过|禁用|关闭)(?:再)?(?:调用|读取|加载|使用)?(?:workbuddy-quality-kit|质量技能|质量入口|任何技能|所有技能)',user_text,re.I))
            if typ in ('compact_boundary', 'compaction-boundary'):
                calls, proven = {}, set()
                continue
            if typ == 'function_call':
                recognized = True
                try: args = json.loads(d.get('arguments', '{}'))
                except (ValueError, TypeError): continue
                if not isinstance(args, dict): continue
                if d.get('name') == 'Skill' and args.get('skill') == 'workbuddy-quality-kit':
                    calls[d.get('callId')] = 'main'
                if d.get('name') == 'Read' and isinstance(args.get('file_path'), str):
                    path = Path(args['file_path']).resolve()
                    for key, value in required.items():
                        if path == value['path']: calls[d.get('callId')] = key
            elif typ == 'function_call_result':
                recognized = True
                key = calls.get(d.get('callId'))
                if key and d.get('status') == 'completed' and d.get('isError') is not True:
                    out = text_output(d.get('output', ''))
                    normalized=re.sub(r'(?m)^[ \t]*\d+→','',out.replace('\r\n','\n'))
                    if required[key]['body'] in normalized: proven.add(key)
            # Classic Claude-shaped JSONL is recognized only with actual completed
            # tool results; unsupported variants fall open, never lock the task.
    return (proven | {'user_opt_out'} if user_opt_out else proven) if recognized else None


def decision(payload):
    if payload.get('hook_event_name') != 'PreToolUse' or payload.get('tool_name') not in TOOLS:
        return {}, 0
    root = Path(__file__).resolve().parents[1]
    paths = {'main': root/'SKILL.md', 'execution': root/'references/execution-review.md'}
    required = {k: {'path': p.resolve(), 'body': instruction_body(p)} for k,p in paths.items()}
    proof = loading_proof(payload.get('transcript_path', ''), required)
    if proof is not None and 'user_opt_out' in proof: return {}, 0
    if proof is None:
        return {'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                'additionalContext': '本版本无法核验技能读取记录；请在实现前实际读取workbuddy-quality-kit主说明及适用参考，沿用用户范围和权限。'}}, 0
    missing = [k for k in required if k not in proof]
    if not missing: return {}, 0
    reason = ('本机通用质量流程尚缺实际读取：' + '、'.join(str(paths[k]) for k in missing) +
              '。先调用workbuddy-quality-kit或用Read完整读取这些文件，再继续本次工具操作；'
              '无需向使用者再次确认。这项检查不授权修改设置、记忆或权限。')
    return {'reason': reason, 'hookSpecificOutput': {'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny', 'permissionDecisionReason': reason}}, 2


def main():
    try:
        payload = json.loads(sys.stdin.read(2*1024*1024))
        value, rc = decision(payload)
    except (ValueError, TypeError, AttributeError, OSError, RecursionError):
        value, rc = {}, 0
    if value: print(json.dumps(value, ensure_ascii=False))
    return rc


if __name__ == '__main__': raise SystemExit(main())
