"""Read-only source hashes and strict OOXML change-scope checks. Python 3 stdlib.
No network, document renderer, macros, subprocesses, or modification of documents.
Only the requested JSON report/manifest is written. Unsupported transformations fail closed.
"""
from pathlib import Path
import argparse, copy, hashlib, json, posixpath, re, sys, zipfile
import xml.etree.ElementTree as ET

NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    's':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'p':'http://schemas.openxmlformats.org/package/2006/relationships'}
S='{'+NS['s']+'}'

def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def emit(data,out):
    p=Path(out)
    if p.suffix.lower()!='.json':raise ValueError('Reports must use a .json filename')
    if not p.parent.is_dir():p.parent.mkdir(parents=True)
    p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def protect_report(out,inputs):
    target=Path(out).resolve()
    if Path(out).is_symlink():raise ValueError('Report cannot be a symlink')
    if any(target==Path(p).resolve() or (target.exists() and Path(p).exists() and target.samefile(p)) for p in inputs):
        raise ValueError('Report cannot overwrite an input, rule or manifest')
def snapshot(root,files,out):
    root=Path(root).resolve(); out=Path(out).resolve(); result={}
    if out.exists(): raise ValueError('Refusing to overwrite an existing snapshot')
    for name in files:
        p=(root/name).resolve()
        if not p.is_relative_to(root) or not p.is_file() or p==out: raise ValueError('Invalid input path: '+name)
        result[p.relative_to(root).as_posix()]=digest(p)
    emit({'schema':1,'files':result},out)
    return {'ok':True,'files':len(result)}
def check(root,manifest):
    root=Path(root).resolve(); data=json.loads(Path(manifest).read_text(encoding='utf-8')); differences=[]
    if not isinstance(data,dict) or not isinstance(data.get('files'),dict) or not data['files']:
        raise ValueError('Manifest must contain a nonempty files mapping')
    for name,old in data['files'].items():
        if not isinstance(name,str) or not name or not isinstance(old,str) or not re.fullmatch(r'[0-9a-f]{64}',old):
            raise ValueError('Manifest requires relative filenames and lowercase SHA-256 values')
        p=(root/name).resolve()
        if not p.is_relative_to(root): raise ValueError('Path outside root')
        now=digest(p) if p.is_file() else None
        if now!=old: differences.append({'file':name,'before':old,'now':now})
    return {'ok':not differences,'checked':len(data['files']),'differences':differences}
def canonical(e):
    # Ignore indentation only; significant text, attributes, child order and namespace URIs survive.
    # Leaf values (including deleted text, field codes and cached strings) can be spaces.
    keep_space = len(e)==0 or e.get('{http://www.w3.org/XML/1998/namespace}space')=='preserve'
    txt=e.text if e.text and (e.text.strip() or keep_space) else ''
    tail=e.tail if e.tail and e.tail.strip() else ''
    return (e.tag,tuple(sorted(e.attrib.items())),txt,tail,tuple(canonical(c) for c in e))
def package(path):
    with zipfile.ZipFile(path) as z:
        if len(z.namelist())!=len(set(z.namelist())): raise ValueError('Duplicate ZIP entries')
        if sum(i.file_size for i in z.infolist())>100_000_000: raise ValueError('Package exceeds 100MB review limit')
        bad=z.testzip()
        if bad: raise ValueError('Corrupt ZIP: '+bad)
        return {n:(ET.fromstring(z.read(n)) if n.endswith(('.xml','.rels')) else z.read(n)) for n in z.namelist() if not n.endswith('/')}
def sheets(parts):
    rels={r.attrib['Id']:r.attrib['Target'] for r in parts['xl/_rels/workbook.xml.rels']}
    return {e.attrib['name']:posixpath.normpath(posixpath.join('xl',rels[e.attrib['{'+NS['r']+'}id']])) .lstrip('/') for e in parts['xl/workbook.xml'].findall('s:sheets/s:sheet',NS)}
def normalize_strings(parts):
    strings=parts.get('xl/sharedStrings.xml'); items=list(strings) if strings is not None else []
    for name,root in parts.items():
        if name.startswith('xl/worksheets/') and name.endswith('.xml'):
            for c in root.findall('.//s:sheetData/s:row/s:c',NS):
                if c.get('t')=='s':
                    v=c.find('s:v',NS); si=items[int(v.text)]
                    c.remove(v); c.set('t','inlineStr'); inline=ET.SubElement(c,S+'is')
                    for child in si: inline.append(copy.deepcopy(child))
    # Storage indirection can change without changing any displayed string or rich text.
    parts.pop('xl/sharedStrings.xml',None)
    for part,tag,attr,value in [('[Content_Types].xml','Override','PartName','/xl/sharedStrings.xml'),('xl/_rels/workbook.xml.rels','Relationship','Type',NS['r']+'/sharedStrings')]:
        root=parts.get(part)
        if root is not None:
            for c in list(root):
                if c.tag.endswith('}'+tag) and c.get(attr)==value: root.remove(c)
def getcell(parts,sheet,addr):
    root=parts[sheets(parts)[sheet]]
    found=root.findall('.//s:sheetData/s:row/s:c[@r="'+addr+'"]',NS)
    if len(found)!=1: raise ValueError('Expected one existing cell: '+sheet+'!'+addr)
    return found[0]
def value(c):
    if c.find('s:f',NS) is not None: return '='+c.find('s:f',NS).text
    if c.get('t')=='inlineStr': return ''.join(c.find('s:is',NS).itertext())
    v=c.find('s:v',NS)
    if v is None or v.text is None:return None
    if c.get('t') in ('str','e'):return v.text
    if c.get('t')=='b':return v.text=='1'
    from decimal import Decimal
    return Decimal(v.text)
def numeric_equal(a,b):
    from decimal import Decimal
    if isinstance(a,bool) or isinstance(b,bool):return type(a) is type(b) and a==b
    if isinstance(a,(int,float,Decimal)) and not isinstance(a,bool) and isinstance(b,(int,float,Decimal)) and not isinstance(b,bool):return Decimal(str(a))==Decimal(str(b))
    return a==b
def diff(before,after,allow):
    if not isinstance(allow,dict) or set(allow)-{'xml_text','xlsx_cells','formula_cache_may_change'}:
        raise ValueError('Unknown or invalid allowed-change fields')
    if type(allow.get('formula_cache_may_change',False)) is not bool:
        raise ValueError('formula_cache_may_change must be a JSON boolean')
    for key,fields,textfields in [('xml_text',{'part','xpath','before','after'},{'part','xpath','before','after'}),('xlsx_cells',{'sheet','cell','before','after'},{'sheet','cell'})]:
        if not isinstance(allow.get(key,[]),list):raise ValueError(key+' must be a list')
        for rule in allow.get(key,[]):
            if not isinstance(rule,dict) or set(rule)!=fields:raise ValueError('Missing or unknown edit rule fields')
            if any(not isinstance(rule[f],str) for f in textfields):raise ValueError('Invalid text field in edit rule')
            if key=='xlsx_cells' and any(not isinstance(rule[f],(str,int,float,bool,type(None))) for f in ['before','after']):
                raise ValueError('Cell values must be JSON scalars')
    a=package(before);b=package(after); violations=[]
    if str(before).lower().endswith('.xlsx'):
        normalize_strings(a);normalize_strings(b)
    for rule in allow.get('xml_text',[]):
        aa=a[rule['part']].findall(rule['xpath'],NS);bb=b[rule['part']].findall(rule['xpath'],NS)
        if len(aa)!=1 or len(bb)!=1: raise ValueError('Text rule must address exactly one element')
        if aa[0].text!=rule['before'] or bb[0].text!=rule['after']:
            violations.append({'rule':rule,'error':'Expected text edit is missing or mismatched'})
        aa[0].text=rule['after']
    for rule in allow.get('xlsx_cells',[]):
        aa=getcell(a,rule['sheet'],rule['cell']);bb=getcell(b,rule['sheet'],rule['cell'])
        if not numeric_equal(value(aa),rule['before']) or not numeric_equal(value(bb),rule['after']):
            violations.append({'rule':rule,'error':'Expected cell edit is missing or mismatched'})
        if aa.find('s:f',NS) is not None or bb.find('s:f',NS) is not None:
            raise ValueError('Scalar edit rule cannot authorize formula changes')
        for c in list(aa):
            if c.tag in (S+'v',S+'is'):aa.remove(c)
        aa.attrib.pop('t',None)
        if bb.get('t') is not None:aa.set('t',bb.get('t'))
        for c in bb:
            if c.tag in (S+'v',S+'is'):aa.append(copy.deepcopy(c))
    if allow.get('formula_cache_may_change',False):
        for parts in [a,b]:
            for n,root in parts.items():
                if n.startswith('xl/worksheets/') and n.endswith('.xml'):
                    for c in root.findall('.//s:c',NS):
                        if c.find('s:f',NS) is not None:
                            v=c.find('s:v',NS)
                            if v is not None:c.remove(v)
    added=sorted(set(b)-set(a));removed=sorted(set(a)-set(b));changed=[]
    for n in sorted(set(a)&set(b)):
        av=canonical(a[n]) if isinstance(a[n],ET.Element) else a[n]
        bv=canonical(b[n]) if isinstance(b[n],ET.Element) else b[n]
        if av!=bv:changed.append(n)
    return {'ok':not(violations or added or removed or changed),'expected_edit_errors':violations,'unapproved_changed_parts':changed,'added_parts':added,'removed_parts':removed,'limits':'Strict structure comparison; legitimate serialization differences may require manual review. Does not verify visual layout, business truth, native recalculation or macro safety.'}
def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('snapshot');p.add_argument('--root',required=True);p.add_argument('--out',required=True);p.add_argument('files',nargs='+')
    p=sub.add_parser('check');p.add_argument('--root',required=True);p.add_argument('--manifest',required=True);p.add_argument('--out',required=True)
    p=sub.add_parser('diff');p.add_argument('before');p.add_argument('after');p.add_argument('--allow',required=True);p.add_argument('--out',required=True)
    args=parser.parse_args()
    try:
        if args.command=='snapshot':result=snapshot(args.root,args.files,args.out)
        elif args.command=='check':
            manifest=json.loads(Path(args.manifest).read_text(encoding='utf-8'))
            protect_report(args.out,[args.manifest]+[Path(args.root)/n for n in manifest['files']])
            result=check(args.root,args.manifest);emit(result,args.out)
        else:
            protect_report(args.out,[args.before,args.after,args.allow])
            result=diff(args.before,args.after,json.loads(Path(args.allow).read_text(encoding='utf-8')));emit(result,args.out)
    except Exception as e:result={'ok':False,'error':str(e)}
    print(json.dumps(result,ensure_ascii=False));return 0 if result['ok'] else 1
if __name__=='__main__':sys.exit(main())
