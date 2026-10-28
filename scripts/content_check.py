"""Read-only ID coverage and exact-decimal reconciliation for saved results.

These checks do not validate semantic choices, scope interpretation or provenance.
Source rows must be selected by the task's independently established rules.
"""
import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal, InvalidOperation, localcontext
import io
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from material_reader import MAX_FILE, JSONNumber, safe_path, strict_json


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['coverage', 'reconcile'])
    parser.add_argument('--root', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--result', required=True)
    parser.add_argument('--source-array', default='', help='JSON pointer to source array')
    parser.add_argument('--result-array', default='', help='JSON pointer to result array')
    parser.add_argument('--id', default='id')
    parser.add_argument('--result-id')
    parser.add_argument('--trim-ids', action='store_true', help='Only when task authorizes trimming')
    parser.add_argument('--value', help='Source numeric column, reconcile only')
    parser.add_argument('--total', help='Summary total column, reconcile only')
    parser.add_argument('--group', help='Same exact group field in both tables')
    args = parser.parse_args()
    try:
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
    except (ValueError, OSError, KeyError, IndexError, UnicodeError, csv.Error) as error:
        print(json.dumps({'passed': False, 'error': str(error)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
