"""Read-only ID coverage, exact-decimal sums and field facts for saved results.

These checks do not validate semantic choices, scope interpretation or provenance.
Source rows must be selected by the task's independently established rules.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
from decimal import Decimal, InvalidOperation, localcontext
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import xml.etree.ElementTree as ET
import zipfile

sys.dont_write_bytecode = True
from material_reader import MAX_FILE, JSONNumber, safe_path, strict_json

MAX_FACT_OUTPUT = 12 * 1024


def rows(root, name, pointer=''):
    _, path = safe_path(root, name)
    if path.stat().st_size > MAX_FILE:
        raise ValueError('File exceeds 20 MiB')
    data = path.read_bytes()
    if len(data) > MAX_FILE:
        raise ValueError('File exceeds 20 MiB')
    text = data.decode('utf-8-sig')
    if path.suffix.lower() in ('.csv', '.tsv'):
        if pointer:
            raise ValueError('JSON pointer is not applicable to CSV')
        csv.field_size_limit(MAX_FILE)
        reader = csv.reader(io.StringIO(text, newline=''), delimiter='\t' if path.suffix.lower() == '.tsv' else ',', strict=True)
        header = next(reader, None)
        if not header or any(not key for key in header) or len(header) != len(set(header)):
            raise ValueError('CSV header must contain distinct nonempty fields')
        result = []
        for i, cells in enumerate(reader, 2):
            if len(cells) != len(header):
                raise ValueError('CSV record ' + str(i) + ' has wrong field count')
            result.append(dict(zip(header, cells)))
        return result
    if path.suffix.lower() != '.json':
        raise ValueError('Use saved .csv/.tsv or a .json row array')
    value = strict_json(text)
    if pointer:
        if not pointer.startswith('/'):
            raise ValueError('JSON pointer must begin with /')
        for token in pointer.split('/')[1:]:
            token = token.replace('~1', '/').replace('~0', '~')
            value = value[int(token)] if isinstance(value, list) else value[token]
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError('Expected array of objects at JSON pointer')
    return value


def ids(data, key, trim=False):
    values = []
    for i, row in enumerate(data, 1):
        value = row.get(key)
        if not isinstance(value, str) or isinstance(value, JSONNumber):
            raise ValueError('ID must be a string; row ' + str(i) + ', field ' + key)
        value = value.strip() if trim else value
        if not value:
            raise ValueError('Empty ID at row ' + str(i))
        values.append(value)
    return values


def coverage(source, result, source_key, result_key, trim=False):
    a, b = Counter(ids(source, source_key, trim)), Counter(ids(result, result_key, trim))
    missing = sorted(a.keys() - b.keys())
    extra = sorted(b.keys() - a.keys())
    repeated_source = {key: n for key, n in a.items() if n > 1}
    repeated_result = {key: n for key, n in b.items() if n > 1}
    return {'passed': not (missing or extra or repeated_source or repeated_result),
            'source_count': len(source), 'result_count': len(result),
            'missing_ids': missing, 'unexpected_ids': extra,
            'duplicate_source_ids': repeated_source, 'duplicate_result_ids': repeated_result,
            'scope': 'IDs only; disposition/reason and source selection are not verified'}


def number(value):
    if isinstance(value, bool) or value is None or not isinstance(value, (str, int, Decimal)):
        raise ValueError('Expected an exact decimal literal; floats/booleans/null are not accepted')
    try:
        result = Decimal(value.strip() if isinstance(value, str) else value)
    except (InvalidOperation, ValueError):
        raise ValueError('Invalid decimal literal')
    if not result.is_finite():
        raise ValueError('Non-finite decimal')
    return result


def totals(data, column, group):
    result = defaultdict(lambda: Decimal(0))
    for i, row in enumerate(data, 1):
        if column not in row:
            raise ValueError('Missing numeric field at row ' + str(i))
        key = row.get(group) if group else '(all)'
        if not isinstance(key, str) or isinstance(key, JSONNumber):
            raise ValueError('Group must be a string at row ' + str(i))
        amount = number(row[column])
        previous = result[key]
        exponent = min(previous.as_tuple().exponent, amount.as_tuple().exponent)
        precision = max(previous.adjusted(), amount.adjusted(), 0) - exponent + 3
        if precision > 20000:
            raise ValueError('Exact total exceeds supported 20,000-digit span')
        with localcontext() as context:
            context.prec = max(precision, 28)
            result[key] = previous + amount
    return dict(result)


def reconcile(source, summary, value, total, group=None):
    computed = totals(source, value, group)
    reported = {}
    for i, row in enumerate(summary, 1):
        key = row.get(group) if group else '(all)'
        if not isinstance(key, str) or isinstance(key, JSONNumber):
            raise ValueError('Summary group must be a string at row ' + str(i))
        if key in reported:
            raise ValueError('Duplicate summary group: ' + key)
        if total not in row:
            raise ValueError('Missing summary total')
        reported[key] = number(row[total])
    keys = sorted(computed.keys() | reported.keys())
    differences = [{'group': key, 'computed': str(computed[key]) if key in computed else None,
                    'reported': str(reported[key]) if key in reported else None}
                   for key in keys if key not in computed or key not in reported or computed[key] != reported[key]]
    return {'passed': not differences, 'source_rows': len(source),
            'summary_rows': len(summary), 'differences': differences,
            'computed': {key: str(value) for key, value in computed.items()},
            'scope': 'Exact sums of supplied rows; filtering, units, currency and business rules are not verified'}


def field_facts(data, fields, group=None):
    """Describe actual rows without accepting expected values or judging prose."""
    if (not fields or len(fields) > 20 or len(set(fields)) != len(fields)
            or any(not f or len(f) > 160 for f in fields)):
        raise ValueError('Choose 1 to 20 distinct nonempty field names, each at most 160 characters')
    def is_numeric_zero(value):
        if isinstance(value, JSONNumber):
            coefficient = value.lower().split('e', 1)[0]
            return not coefficient.replace('-', '').replace('.', '').strip('0')
        return isinstance(value, (int, Decimal)) and not isinstance(value, bool) and value == 0
    def describe(items):
        facts = {}
        for field in fields:
            values = [row[field] for row in items if field in row]
            facts[field] = {
                'present': len(values), 'missing': len(items) - len(values),
                'null': sum(v is None for v in values),
                'empty_string': sum(type(v) is str and v == '' for v in values),
                'whitespace_string': sum(type(v) is str and v != '' and not v.strip() for v in values),
                'false_boolean': sum(v is False for v in values),
                'numeric_zero': sum(is_numeric_zero(v) for v in values),
            }
        return {'row_count': len(items), 'fields': facts}
    result = describe(data)
    if group:
        groups = {}
        for row in data:
            if group not in row:
                key = ('missing', None)
            elif row[group] is None:
                key = ('null', None)
            elif type(row[group]) is str:
                if len(row[group]) > 160:
                    raise ValueError('Group label exceeds 160 characters; use a concise source field')
                key = ('string', row[group])
            else:
                raise ValueError('Group values must be exact strings, null, or missing; do not coerce values')
            groups.setdefault(key, []).append(row)
            if len(groups) > 100:
                raise ValueError('More than 100 groups; choose a lower-cardinality source field')
        result['groups'] = [dict(group_field=group, group_type=key[0], group_value=key[1], **describe(items))
                            for key, items in groups.items()]
    result['scope'] = ('Stored rows and field states only; rows are not necessarily unique objects. '
                       'Missing, null, empty string, whitespace, false and numeric zero stay distinct. '
                       'CSV cells are strings, including 0. Grouping does not establish business scope. '
                       'No prose, completeness of the source, causation or semantic correctness is certified.')
    return result


def artifact_format(path, data):
    """Limited syntax/container checks, never semantic acceptance."""
    suffix = path.suffix.lower()
    if suffix in ('.txt', '.md', '.html', '.json', '.jsonl', '.csv', '.tsv'):
        text = data.decode('utf-8-sig')
        if suffix == '.json':
            strict_json(text)
            return 'JSON syntax only'
        if suffix == '.jsonl':
            for line in text.splitlines():
                if line.strip():
                    strict_json(line)
            return 'JSONL syntax only'
        if suffix in ('.csv', '.tsv'):
            csv.field_size_limit(MAX_FILE)
            list(csv.reader(io.StringIO(text, newline=''), delimiter='\t' if suffix == '.tsv' else ',', strict=True))
            return 'Delimited-text syntax only; schema and cells not verified'
        return 'UTF-8 text only; content and rendering not verified'
    if suffix in ('.docx', '.xlsx', '.pptx', '.zip'):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)) or sum(e.file_size for e in entries) > 200 * 1024 * 1024:
                raise ValueError('Duplicate ZIP member or expanded size over 200 MiB')
            if archive.testzip() is not None:
                raise ValueError('ZIP integrity failure')
            part = {'.docx': 'word/document.xml', '.xlsx': 'xl/workbook.xml', '.pptx': 'ppt/presentation.xml'}.get(suffix)
            if part:
                for name in ('[Content_Types].xml', part):
                    xml = archive.read(name)
                    if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
                        raise ValueError('XML declarations are not supported')
                    ET.fromstring(xml)
                return 'Office ZIP and main XML syntax only; layout/recalculation not verified'
            return 'ZIP integrity only; member content not verified'
    if suffix == '.pdf':
        if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-1024:]:
            raise ValueError('PDF header/end marker missing')
        return 'PDF header/end marker only; pages and rendering not verified'
    return 'Existence and SHA only; this file format is not verified'


def handoff(root, names, expected=None, reply_file=None, reply_root=None):
    """Read actual artifact versions and return a neutral delivery receipt."""
    names = list(names or [])
    reply_path = reply_scope = reply_text = None
    if bool(reply_file) != bool(reply_root):
        raise ValueError('--reply-file and --reply-root must be supplied together')
    if reply_file:
        project, reply_path = safe_path(root, reply_file)
        reply_scope = Path(reply_root)
        if not reply_scope.is_absolute():
            reply_scope = project / reply_scope
        reply_scope = Path(os.path.abspath(reply_scope))
        if not reply_scope.is_relative_to(project) or not reply_scope.is_dir() or any(p.is_symlink() for p in (reply_scope, *reply_scope.parents)):
            raise ValueError('Reply output scope must be an existing nonsymlink directory inside root')
        if not reply_path.is_relative_to(reply_scope):
            raise ValueError('Reply file is outside the explicitly selected task output scope')
        names.append(reply_file)
    if not names or len(names) > 12 or len(set(names)) != len(names):
        raise ValueError('Choose 1 to 12 distinct artifact paths')
    if expected is not None and (len(expected) != len(names) or any(not re.fullmatch('[0-9a-fA-F]{64}', h) for h in expected)):
        raise ValueError('Provide one valid --expect-sha256 for each artifact, in the same order')
    files, replies, seen_paths = [], ['文件已保存：'], set()
    for index, name in enumerate(names):
        if any(ord(ch) < 32 for ch in name):
            raise ValueError('Control characters in artifact path are not supported')
        _, path = safe_path(root, name)
        if path in seen_paths:
            raise ValueError('Artifact paths resolve to the same file')
        seen_paths.add(path)
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE:
            raise ValueError('Artifact must be a regular file no larger than 20 MiB')
        if path == reply_path and before.st_size > 8 * 1024:
            raise ValueError('Saved reply exceeds 8 KiB; no partial reply emitted')
        with path.open('rb') as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise ValueError('Artifact changed before reading')
            data = stream.read(MAX_FILE + 1)
        after = path.lstat()
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        if identity(before) != identity(after) or len(data) != before.st_size or len(data) > MAX_FILE:
            raise ValueError('Artifact changed while reading; preserve and recheck the final version')
        digest = hashlib.sha256(data).hexdigest()
        if expected is not None and digest != expected[index].lower():
            raise ValueError('Artifact no longer matches the specified checked version: ' + name)
        kind = artifact_format(path, data)
        if path == reply_path:
            reply_text = data.decode('utf-8-sig').replace('\r\n', '\n')
            if not reply_text.strip() or any(ord(ch) < 32 and ch not in '\n\t' or ord(ch) == 127 for ch in reply_text):
                raise ValueError('Saved reply must be nonempty UTF-8 text without control characters')
        target = path.as_posix()
        if any(ord(ch) < 32 for ch in target):
            raise ValueError('Control characters in resolved path are not supported')
        target = target.replace('%', '%25').replace('<', '%3C').replace('>', '%3E').replace('\\', '%5C').replace('#', '%23').replace('?', '%3F')
        label = path.name.replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]')
        link = '- [' + label + '](<' + target + '>)'
        replies.append(link)
        files.append({'path': path.as_posix(), 'bytes': len(data), 'sha256': digest,
                      'format_check': kind, 'expected_version_matched': expected is not None})
    replies.append('具体内容见上述文件。')
    report = {'proof': 'saved_artifact_identity_not_semantic_acceptance', 'files': files,
            'reply_lines': replies,
            'scope': 'Only the listed saved files at the observed versions. No claim of task completion, semantic review, or review after later edits.'}
    if reply_path is not None:
        report['reply_source'] = {'path': str(reply_path), 'sha256': files[-1]['sha256'], 'output_root': str(reply_scope)}
        report['reply_lines'] = reply_text.split('\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['coverage', 'reconcile', 'facts', 'handoff'])
    parser.add_argument('--root', required=True)
    parser.add_argument('--source')
    parser.add_argument('--result')
    parser.add_argument('--source-array', default='', help='JSON pointer to source array')
    parser.add_argument('--result-array', default='', help='JSON pointer to result array')
    parser.add_argument('--id', default='id')
    parser.add_argument('--result-id')
    parser.add_argument('--trim-ids', action='store_true', help='Only when task authorizes trimming')
    parser.add_argument('--value', help='Source numeric column, reconcile only')
    parser.add_argument('--total', help='Summary total column, reconcile only')
    parser.add_argument('--group', help='Same exact group field in both tables')
    parser.add_argument('--field', action='append', help='Stored field to count, repeatable; facts only')
    parser.add_argument('--artifact', action='append', help='Saved artifact path relative to root; repeat for handoff only')
    parser.add_argument('--expect-sha256', action='append', help='Previously checked SHA for each artifact in order, then reply-file SHA last if present; handoff only')
    parser.add_argument('--reply-file', help='Saved final UTF-8 reply, automatically appended to checked files; handoff only')
    parser.add_argument('--reply-root', help='Explicit task output/work directory inside root; required with reply-file')
    parser.add_argument('--register-stop', action='store_true', help='Explicitly register receipt in an initialized project gate; handoff only, needs actual WorkBuddy session/generation environment')
    args = parser.parse_args()
    try:
        if args.command == 'handoff':
            if args.source or args.result or args.field or args.group or args.value or args.total or args.source_array or args.result_array or args.trim_ids:
                raise ValueError('handoff only accepts root, artifact and optional expect-sha256')
            report = handoff(args.root, args.artifact, args.expect_sha256, args.reply_file, args.reply_root)
            rendered = json.dumps(report, ensure_ascii=False, indent=2)
            if len(rendered.encode('utf-8')) > MAX_FACT_OUTPUT or any(len(line.encode('utf-8')) > 1000 for line in rendered.splitlines()):
                raise ValueError('Handoff exceeds bounded output; use fewer paths or a shorter root-relative path. No partial receipt emitted')
            if args.register_stop:
                if len(rendered.encode('utf-8')) > MAX_FACT_OUTPUT - 1024:
                    raise ValueError('Registered handoff needs 1 KiB headroom; use fewer or shorter paths. Not registered')
                from content_gate import register
                report['gate'] = register(args.root, report)
                rendered = json.dumps(report, ensure_ascii=False, indent=2)
            print(rendered)
            return 0
        if args.artifact or args.expect_sha256 or args.register_stop or args.reply_file or args.reply_root:
            raise ValueError('--artifact/--expect-sha256/--register-stop/--reply-file/--reply-root are only applicable to handoff')
        if not args.source:
            raise ValueError('coverage/reconcile/facts requires --source')
        if args.command == 'facts':
            if args.result or args.result_array or args.value or args.total or args.trim_ids:
                raise ValueError('facts only accepts source, source-array, field and optional group')
            _, path = safe_path(args.root, args.source)
            if path.stat().st_size > MAX_FILE:
                raise ValueError('File exceeds 20 MiB')
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            source = rows(args.root, args.source, args.source_array)
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            if before != after:
                raise ValueError('Source changed while facts were being read; retry on the saved version')
            report = field_facts(source, args.field, args.group)
            report.update(source=args.source, source_array=args.source_array, source_sha256=after,
                          proof='stored_field_counts_not_semantic_acceptance')
            rendered = json.dumps(report, ensure_ascii=False, indent=2)
            if len(rendered.encode('utf-8')) > MAX_FACT_OUTPUT:
                raise ValueError('Facts output exceeds 12 KiB; request fewer fields or omit grouping. No facts were emitted')
            if any(len(line.encode('utf-8')) > 1000 for line in rendered.splitlines()):
                raise ValueError('Facts output contains an oversized line; shorten the relative source path or field selection. No facts were emitted')
            print(rendered)
            return 0
        if not args.result:
            raise ValueError('coverage/reconcile requires --result')
        if args.field:
            raise ValueError('--field is only applicable to facts')
        source = rows(args.root, args.source, args.source_array)
        result = rows(args.root, args.result, args.result_array)
        if args.command == 'coverage':
            report = coverage(source, result, args.id, args.result_id or args.id, args.trim_ids)
        else:
            if not args.value or not args.total:
                raise ValueError('reconcile requires --value and --total')
            report = reconcile(source, result, args.value, args.total, args.group)
        print(json.dumps(report, ensure_ascii=False, separators=(',', ':')))
        return 0 if report['passed'] else 1
    except (ValueError, OSError, KeyError, IndexError, UnicodeError, csv.Error, zipfile.BadZipFile, ET.ParseError, RuntimeError, NotImplementedError) as error:
        print(json.dumps({'passed': False, 'error': str(error)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
