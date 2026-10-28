"""Read-only PPTX structural checks; Python 3.9+, standard library only.
Does not render, edit, install dependencies, or prove native Office validity.
"""
import argparse
import hashlib
import json
import posixpath
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'


def text_body(node):
    if node is None:
        return ''
    return '\n'.join(''.join('\n' if t.tag == '{'+NS['a']+'}br' else (t.text or '')
                             for t in p.iter() if t.tag in ('{'+NS['a']+'}t', '{'+NS['a']+'}br'))
                     for p in node.findall('a:p', NS))


def notes_shell(data):
    root = ET.fromstring(data)
    for sp in root.findall('.//p:sp', NS):
        ph = sp.find('p:nvSpPr/p:nvPr/p:ph', NS)
        body = sp.find('p:txBody', NS)
        if ph is not None and ph.get('type') == 'body' and body is not None:
            for p in list(body.findall('a:p', NS)):
                body.remove(p)
    def shape(e):
        txt = e.text if e.text and e.text.strip() else None
        return (e.tag, tuple(sorted(e.attrib.items())), txt, tuple(shape(c) for c in e))
    return shape(root)


def target_part(owner, target):
    uri = urlsplit(target)
    if uri.scheme or uri.netloc:
        raise ValueError('Internal relationship contains a remote URI')
    path = unquote(uri.path)
    resolved = posixpath.normpath(path.lstrip('/') if path.startswith('/')
                                 else posixpath.join(posixpath.dirname(owner), path))
    if resolved == '..' or resolved.startswith('../'):
        raise ValueError('Relationship escapes the package')
    return resolved


def load(path):
    path = Path(path)
    raw = path.read_bytes()
    errors, warnings, pages = [], [], []
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:
            raise ValueError('ZIP integrity failure')
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate ZIP entries')
        if any(n.startswith('/') or '..' in n.split('/') or '\\' in n for n in names):
            raise ValueError('Unsafe package entry name')
        parts = {n: z.read(n) for n in names if not n.endswith('/')}
    types = ET.fromstring(parts['[Content_Types].xml'])
    defaults = {e.get('Extension', '').lower(): e.get('ContentType', '')
                for e in types.findall('{'+CT+'}Default')}
    overrides = {e.get('PartName', '').lstrip('/'): e.get('ContentType', '')
                 for e in types.findall('{'+CT+'}Override')}
    xml = {}
    for name, data in parts.items():
        content_type = overrides.get(name, defaults.get(name.rsplit('.', 1)[-1].lower(), ''))
        is_xml = name.lower().endswith(('.xml', '.rels', '.svg', '.vml')) or content_type.endswith('+xml') or content_type in ('application/xml', 'text/xml')
        if is_xml:
            try:
                xml[name] = ET.fromstring(data)
            except (ET.ParseError, ValueError) as exc:
                errors.append({'part': name, 'issue': 'invalid_xml', 'detail': str(exc)})
    relations = {}
    for name in sorted(n for n in parts if n.endswith('.rels')):
        root = xml.get(name)
        if root is None:
            continue
        if root.tag != '{'+REL+'}Relationships':
            errors.append({'part': name, 'issue': 'invalid_relationship_root'})
            continue
        directory, filename = posixpath.split(name)
        if name == '_rels/.rels':
            owner = ''
        elif posixpath.basename(directory) == '_rels':
            owner = posixpath.join(posixpath.dirname(directory), filename[:-5])
        else:
            errors.append({'part': name, 'issue': 'invalid_relationship_location'})
            continue
        current = {}
        for e in root:
            rid, typ, target = e.get('Id'), e.get('Type'), e.get('Target')
            if e.tag != '{'+REL+'}Relationship' or not all((rid, typ, target)) or rid in current:
                errors.append({'part': name, 'issue': 'invalid_relationship', 'id': rid})
                continue
            external = e.get('TargetMode') == 'External'
            try:
                resolved = target if external else target_part(owner, target)
                if not external and resolved not in parts:
                    errors.append({'part': name, 'issue': 'missing_relationship_target', 'id': rid, 'target': resolved})
                current[rid] = {'type': typ.rsplit('/', 1)[-1], 'target': resolved, 'external': external}
            except ValueError as exc:
                errors.append({'part': name, 'issue': 'invalid_relationship_target', 'detail': str(exc)})
        relations[owner] = current
    pres = xml.get('ppt/presentation.xml')
    if pres is None:
        errors.append({'issue': 'missing_or_invalid_presentation'})
        size = None
    else:
        sz = pres.find('p:sldSz', NS)
        size = [int(sz.get('cx')), int(sz.get('cy'))] if sz is not None else None
        if size is None or any(n <= 0 for n in size):
            errors.append({'issue': 'missing_or_invalid_slide_size'})
        ids = pres.find('p:sldIdLst', NS)
        if ids is None:
            errors.append({'issue': 'missing_slide_order'})
        for i, sid in enumerate(list(ids) if ids is not None else [], 1):
            rel = relations.get('ppt/presentation.xml', {}).get(sid.get('{'+NS['r']+'}id'))
            if not rel or rel['type'] != 'slide' or rel['external'] or rel['target'] not in xml:
                errors.append({'page': i, 'issue': 'invalid_slide_reference'})
                continue
            part = rel['target']
            root = xml[part]
            sr = relations.get(part, {})
            nt = [v['target'] for v in sr.values() if v['type'] == 'notesSlide' and not v['external']]
            notes = None
            if len(nt) > 1:
                errors.append({'page': i, 'issue': 'multiple_notes_parts'})
            if len(nt) == 1 and nt[0] in xml:
                bodies = []
                for sp in xml[nt[0]].findall('.//p:sp', NS):
                    ph = sp.find('p:nvSpPr/p:nvPr/p:ph', NS)
                    if ph is not None and ph.get('type') == 'body':
                        bodies.append(text_body(sp.find('p:txBody', NS)))
                if len(bodies) == 1:
                    notes = bodies[0]
                elif len(bodies) > 1:
                    errors.append({'page': i, 'issue': 'multiple_notes_bodies'})
            tables = root.findall('.//a:tbl', NS)
            for ti, tbl in enumerate(tables, 1):
                grid = tbl.find('a:tblGrid', NS)
                cols = len(list(grid)) if grid is not None else 0
                if not cols:
                    errors.append({'page': i, 'table': ti, 'issue': 'missing_table_grid'})
                for ri, row in enumerate(tbl.findall('a:tr', NS), 1):
                    cells = row.findall('a:tc', NS)
                    horizontal_merge = any(c.get('gridSpan') or c.get('hMerge') for c in cells)
                    if len(cells) != cols:
                        item = {'page': i, 'table': ti, 'row': ri, 'cells': len(cells), 'grid_columns': cols}
                        if horizontal_merge:
                            warnings.append(dict(item, issue='merged_row_requires_specific_review'))
                        else:
                            errors.append(dict(item, issue='table_row_column_mismatch'))
                    if any(c.find('a:tcPr/a:ln', NS) is not None for c in cells):
                        errors.append({'page': i, 'table': ti, 'row': ri, 'issue': 'invalid_cell_border_element_use_lnL_lnR_lnT_lnB'})
            pics = root.findall('.//p:pic', NS)
            for pic in pics:
                for blip in pic.findall('.//a:blip', NS):
                    rid = blip.get('{'+NS['r']+'}embed') or blip.get('{'+NS['r']+'}link')
                    if not rid or rid not in sr or sr[rid]['type'] != 'image':
                        errors.append({'page': i, 'issue': 'invalid_picture_reference', 'id': rid})
            pages.append({'page': i, 'part': part, 'notes_part': nt[0] if len(nt) == 1 else None,
                          'notes': notes, 'native_text_objects': len(root.findall('.//p:sp/p:txBody', NS)),
                          'native_tables': len(tables), 'pictures': len(pics)})
    report = {'ok': not errors, 'sha256': hashlib.sha256(raw).hexdigest(), 'slide_count': len(pages),
              'size_emu': size, 'xml_parts_parsed': len(xml), 'errors': errors, 'warnings': warnings,
              'pages': [{k: v for k, v in p.items() if k != 'notes'} for p in pages],
              'scope': 'Read-only structural subset; not rendering, fact checking or full Office schema validation.'}
    return report, parts, pages


def compare(source, candidate, expected):
    a, ap, pages_a = load(source)
    b, bp, pages_b = load(candidate)
    errors = []
    allowed = {p['notes_part'] for p in pages_a if p['notes_part']}
    changed = sorted(n for n in set(ap) | set(bp) if ap.get(n) != bp.get(n))
    unexpected = [n for n in changed if n not in allowed]
    if set(ap) != set(bp):
        errors.append({'issue': 'package_part_set_changed'})
    if unexpected:
        errors.append({'issue': 'non_notes_parts_changed', 'parts': unexpected})
    shell_changed = [n for n in changed if n in allowed and n in ap and n in bp
                     and notes_shell(ap[n]) != notes_shell(bp[n])]
    if shell_changed:
        errors.append({'issue': 'notes_outside_body_changed', 'parts': shell_changed})
    if [p['part'] for p in pages_a] != [p['part'] for p in pages_b] or a['size_emu'] != b['size_emu']:
        errors.append({'issue': 'slide_order_or_size_changed'})
    if expected is not None:
        rows = json.loads(Path(expected).read_text(encoding='utf-8'))
        if not isinstance(rows, list) or any(not isinstance(r, dict) or type(r.get('page')) is not int or not isinstance(r.get('text'), str) for r in rows):
            raise ValueError('Expected notes must be [{"page": 1, "text": "..."}, ...]')
        wanted = {r['page']: r['text'] for r in rows}
        if len(wanted) != len(rows) or set(wanted) != set(range(1, len(pages_b)+1)):
            raise ValueError('Expected notes must cover actual pages exactly once')
        mismatch = [p['page'] for p in pages_b if p['notes'] != wanted[p['page']]]
        if mismatch:
            errors.append({'issue': 'notes_mismatch', 'pages': mismatch})
    return {'ok': a['ok'] and b['ok'] and not errors, 'mode': 'notes_only',
            'source': a, 'candidate': b, 'changed_parts': changed, 'comparison_errors': errors,
            'expected_notes_checked': expected is not None,
            'scope': 'Exact non-notes part preservation; no visual or full Office schema validation.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    one = sub.add_parser('inspect'); one.add_argument('pptx')
    two = sub.add_parser('notes-only'); two.add_argument('source'); two.add_argument('candidate')
    two.add_argument('--expected-notes', help='UTF-8 JSON array of page/text pairs; page is actual display order')
    args = p.parse_args()
    try:
        report = load(args.pptx)[0] if args.command == 'inspect' else compare(args.source, args.candidate, args.expected_notes)
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, ET.ParseError) as exc:
        report = {'ok': False, 'error': str(exc)}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 2


if __name__ == '__main__':
    sys.exit(main())
