"""Read-only bounded projections of local material. No network or persistent state.

The page metadata proves what this process emitted, not what a host displayed or
what a model understood. Inspect unsupported parts before claiming completeness.
"""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import posixpath
import sys
import xml.etree.ElementTree as ET
import zipfile

MAX_FILE = 20 * 1024 * 1024
MAX_XML = 50 * 1024 * 1024
CHUNK = 200
PAGE = 12
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
S = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


class JSONNumber(str):
    """A JSON number's original lexeme, distinguishable from a JSON string."""


def safe_path(root, name):
    root = Path(os.path.abspath(root))
    target = Path(name)
    if not target.is_absolute():
        target = root / target
    target = Path(os.path.abspath(target))
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError('File is outside --root')
    for path in [root, *root.parents, target, *target.parents]:
        if path.is_symlink():
            raise ValueError('Symbolic links are not accepted')
    if not root.is_dir() or not target.is_file():
        raise ValueError('Expected an existing root and regular file')
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('Resolved file is outside --root')
    return root, target


def strict_json(text):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError('Duplicate JSON key: ' + key[:100])
            out[key] = value
        return out
    def constant(value):
        raise ValueError('Non-finite JSON number: ' + value)
    # Preserve numeric lexemes for exact financial/identifier inspection.
    return json.loads(text, object_pairs_hook=unique, parse_int=JSONNumber,
                      parse_float=JSONNumber, parse_constant=constant)


def xml(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('DTD/entity XML is unsupported')
    return ET.fromstring(data)


def json_units(value, pointer='$', depth=0):
    if depth > 60:
        raise ValueError('JSON nesting exceeds safe projection depth')
    if isinstance(value, dict):
        if not value:
            yield pointer, '{}'
        for key, child in value.items():
            key = key.replace('~', '~0').replace('/', '~1')
            yield from json_units(child, pointer + '/' + key, depth + 1)
    elif isinstance(value, list):
        if not value:
            yield pointer, '[]'
        for i, child in enumerate(value):
            yield from json_units(child, pointer + '/' + str(i), depth + 1)
    elif isinstance(value, JSONNumber):
        yield pointer, json.dumps({'json_type': 'number', 'lexeme': str(value)}, ensure_ascii=False)
    else:
        yield pointer, json.dumps(value, ensure_ascii=False)


def docx_units(z, warnings):
    parts = sorted(n for n in z.namelist() if n.startswith('word/') and
                   n.endswith('.xml') and (n in ['word/document.xml',
                   'word/footnotes.xml', 'word/endnotes.xml', 'word/comments.xml']
                   or Path(n).name.startswith(('header', 'footer'))))
    if 'word/document.xml' not in parts:
        raise ValueError('Missing DOCX document.xml')
    warnings.append('DOCX text only; layout, images, drawings, field evaluation and revision acceptance are not verified')
    for part in parts:
        tree = xml(z.read(part))
        for i, paragraph in enumerate(tree.iter(W + 'p'), 1):
            chunks = []
            def visit(node):
                for child in node:
                    if child.tag == W + 'p':
                        continue  # nested text-box paragraph gets its own locator
                    if child.tag == W + 't':
                        chunks.append(child.text or '')
                    elif child.tag == W + 'delText':
                        chunks.append('[deleted:' + (child.text or '') + ']')
                    elif child.tag == W + 'instrText':
                        chunks.append('[field-code:' + (child.text or '') + ']')
                    elif child.tag in (W + 'tab', W + 'br', W + 'cr'):
                        chunks.append('\t' if child.tag == W + 'tab' else '\n')
                    else:
                        visit(child)
            visit(paragraph)
            yield part + '#paragraph=' + str(i), ''.join(chunks)
        if any(e.tag == W + 'altChunk' for e in tree.iter()):
            warnings.append(part + ': embedded altChunk content is not projected')
    embedded = [n for n in z.namelist() if n.startswith(('word/media/', 'word/embeddings/'))]
    if embedded:
        warnings.append(str(len(embedded)) + ' image/embedded parts require separate inspection')


def xlsx_units(z, warnings):
    book = xml(z.read('xl/workbook.xml'))
    rels = xml(z.read('xl/_rels/workbook.xml.rels'))
    links = {e.attrib['Id']: e.attrib for e in rels}
    strings = []
    if 'xl/sharedStrings.xml' in z.namelist():
        strings = [''.join(n.text or '' for n in si.iter(S + 't'))
                   for si in xml(z.read('xl/sharedStrings.xml')).iter(S + 'si')]
    warnings.append('XLSX stored cells and formulas only; cached values may be stale; formatting/date display and recalculation are not verified')
    for sheet in book.iter(S + 'sheet'):
        relation = links.get(sheet.attrib.get(R + 'id'), {})
        if relation.get('TargetMode') == 'External' or 'Target' not in relation:
            raise ValueError('External/missing workbook sheet relationship')
        target = relation['Target']
        part = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
        if not part.startswith('xl/') or part not in z.namelist():
            raise ValueError('Invalid workbook sheet target')
        label = sheet.attrib.get('name', '?')
        yield part + '#sheet', json.dumps({'name': label, 'state': sheet.attrib.get('state', 'visible')}, ensure_ascii=False)
        for cell in xml(z.read(part)).iter(S + 'c'):
            kind = cell.attrib.get('t', 'n')
            raw = cell.find(S + 'v')
            value = raw.text if raw is not None else None
            if kind == 's' and value is not None:
                value = strings[int(value)]
            elif kind == 'inlineStr':
                value = ''.join(n.text or '' for n in cell.iter(S + 't'))
            formula = cell.find(S + 'f')
            data = {'sheet': label, 'type': kind, 'value': value,
                    'style_index': cell.attrib.get('s')}
            if formula is not None:
                data['formula'] = formula.text
                data['formula_attributes'] = formula.attrib
                data['cached_value_unverified'] = True
            yield part + '#' + cell.attrib.get('r', '?'), json.dumps(data, ensure_ascii=False)
    for part in sorted(n for n in z.namelist() if n.startswith('xl/comments') and n.endswith('.xml')):
        for comment in xml(z.read(part)).iter(S + 'comment'):
            yield part + '#' + comment.attrib.get('ref', '?'), ''.join(n.text or '' for n in comment.iter(S + 't'))
    extra = [n for n in z.namelist() if n.startswith(('xl/media/', 'xl/embeddings/', 'xl/threadedComments/'))]
    if extra:
        warnings.append(str(len(extra)) + ' image/embedded/threaded-comment parts require separate inspection')


def project(root, name):
    root, path = safe_path(root, name)
    if path.stat().st_size > MAX_FILE:
        raise ValueError('File exceeds 20 MiB; use a format-specific bounded reader')
    data = path.read_bytes()
    if len(data) > MAX_FILE:
        raise ValueError('File exceeds 20 MiB')
    sha = hashlib.sha256(data).hexdigest()
    suffix = path.suffix.lower()
    warnings = []
    units = []
    if suffix in ('.docx', '.xlsx'):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            entries = z.infolist()
            names = [e.filename for e in entries]
            if len(entries) > 5000 or sum(e.file_size for e in entries) > MAX_XML:
                raise ValueError('OOXML archive exceeds safe projection limit')
            if len(set(names)) != len(names):
                raise ValueError('Duplicate ZIP entries')
            if any(n.startswith('/') or '..' in Path(n).parts for n in names):
                raise ValueError('Unsafe ZIP part name')
            units = list(docx_units(z, warnings) if suffix == '.docx' else xlsx_units(z, warnings))
    else:
        if suffix not in ('.txt', '.md', '.csv', '.tsv', '.json', '.jsonl', '.ndjson', '.log', '.yaml', '.yml', '.xml', '.html'):
            raise ValueError('Unsupported format; use the existing format tool, do not infer complete reading')
        text = data.decode('utf-8-sig')
        if '\x00' in text:
            raise ValueError('NUL/binary text is unsupported')
        if suffix == '.json':
            units = list(json_units(strict_json(text)))
        elif suffix in ('.jsonl', '.ndjson'):
            for line, body in enumerate(text.splitlines(), 1):
                if body.strip():
                    units.extend(json_units(strict_json(body), '$line=' + str(line)))
        elif suffix in ('.csv', '.tsv'):
            csv.field_size_limit(MAX_FILE)
            reader = csv.reader(io.StringIO(text, newline=''), delimiter='\t' if suffix == '.tsv' else ',', strict=True)
            for row, cells in enumerate(reader, 1):
                units.append(('record=' + str(row) + ';end_line=' + str(reader.line_num), json.dumps(cells, ensure_ascii=False)))
        else:
            units = [('line=' + str(i), line) for i, line in enumerate(text.splitlines(keepends=True), 1)]
            if suffix in ('.html', '.xml', '.yaml', '.yml'):
                warnings.append('Raw text only; no execution, rendering or semantic parsing')
    segments = []
    for location, body in units:
        if len(json.dumps(location, ensure_ascii=False)) > 500:
            raise ValueError('Source locator exceeds safe display length; use source-specific reader')
        for start in range(0, max(1, len(body)), CHUNK):
            segments.append({'source': location, 'start': start,
                             'end': min(start + CHUNK, len(body)),
                             'length': len(body), 'text': body[start:start + CHUNK]})
    return {'file': path.relative_to(root).as_posix(), 'sha256': sha,
            'bytes': len(data), 'units': len(units), 'segments': len(segments),
            'warnings': list(dict.fromkeys(warnings)),
            'proof': 'projection_generated_not_host_display_or_understanding'}, segments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['inspect', 'read'])
    parser.add_argument('--root', required=True)
    parser.add_argument('--file', required=True, help='File relative to root, or an absolute path within root')
    parser.add_argument('--start', type=int, default=0, help='Zero-based segment, from next_start')
    parser.add_argument('--count', type=int, default=PAGE, help='1..12 segments per tool return')
    parser.add_argument('--sha256', help='Refuse changed material when continuing pages')
    args = parser.parse_args()
    try:
        if args.start < 0 or not 1 <= args.count <= PAGE:
            raise ValueError('start must be >=0 and count must be 1..12')
        meta, segments = project(args.root, args.file)
        if args.sha256 and args.sha256 != meta['sha256']:
            raise ValueError('Material changed; prior reading/review needs reconciliation')
        if args.start > len(segments):
            raise ValueError('start exceeds total segments')
        if args.command == 'inspect':
            emit({'type': 'inventory', **meta})
        else:
            end = min(args.start + args.count, len(segments))
            emit({'type': 'page', **meta, 'start': args.start, 'end': end,
                  'next_start': end if end < len(segments) else None})
            for i in range(args.start, end):
                emit({'type': 'segment', 'index': i, **segments[i]})
            emit({'type': 'page_end', 'sha256': meta['sha256'], 'end': end,
                  'next_start': end if end < len(segments) else None})
        return 0
    except (ValueError, OSError, UnicodeError, csv.Error, ET.ParseError, zipfile.BadZipFile, KeyError, IndexError) as error:
        emit({'ok': False, 'error': str(error)})
        return 2


def emit(value):
    line = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    if len(line) > 1900:
        raise ValueError('Projection metadata exceeds bounded line length; use a source-specific reader')
    print(line)


if __name__ == '__main__':
    sys.exit(main())
