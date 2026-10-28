"""Offline synthetic tests; retains scratch only in this package directory. No network or live configuration."""
from pathlib import Path
import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import zipfile

BASE=Path(__file__).resolve().parent
SCRIPTS=BASE/'skills/workbuddy-quality-kit/scripts'
sys.path.insert(0,str(SCRIPTS))
import material_reader as m
import content_check as c

ROOT=Path(tempfile.mkdtemp(prefix='reader-test-',dir=BASE))
results=[]
def test(name,fn):
    try:
        assert fn()
        results.append({'case':name,'passed':True})
    except Exception as e:
        results.append({'case':name,'passed':False,'error':repr(e)})
def rejects(fn):
    try: fn()
    except (ValueError,OSError,UnicodeError,csv.Error): return True
    return False
def write(name,text):
    p=ROOT/name;p.write_text(text,encoding='utf-8');return p
def run(script,*args):
    return subprocess.run([sys.executable,'-B',str(SCRIPTS/script),*args],capture_output=True,text=True)

original='首部\n'+'长行😀资料'*900+'\n尾部必要例外\n'
write('long.txt',original)
meta,parts=m.project(ROOT,'long.txt')
test('long text fully reconstructs Unicode and newlines',lambda:''.join(p['text'] for p in parts)==original)
test('all text segments bounded to 300 characters',lambda:all(len(p['text'])<=300 for p in parts))
test('projection does not claim actual host reading',lambda:meta['proof']=='projection_generated_not_host_display_or_understanding')
data={'id':'001','number':123,'negative':-2,'precise':'0.000001','body':'材料'*2500,'array':[True,None,{},[]]}
write('long.json',json.dumps(data,ensure_ascii=False))
jm,jp=m.project(ROOT,'long.json')
test('JSON long field fully reconstructed',lambda:json.loads(''.join(p['text'] for p in jp if p['source']=='$/body'))==data['body'])
test('JSON numeric and string identifiers remain distinct',lambda:json.loads(next(p['text'] for p in jp if p['source']=='$/number'))=={'json_type':'number','lexeme':'123'} and next(p['text'] for p in jp if p['source']=='$/id')=='"001"')
write('duplicates.json','{"x":1,"x":2}')
test('duplicate JSON keys rejected',lambda:rejects(lambda:m.project(ROOT,'duplicates.json')))
write('nan.json','{"n":NaN}')
test('nonfinite JSON rejected',lambda:rejects(lambda:m.project(ROOT,'nan.json')))
with (ROOT/'data.csv').open('w',encoding='utf-8',newline='') as f:
    writer=csv.writer(f);writer.writerow(['id','body']);writer.writerow(['001','第一行\n第二行,引号"尾段'])
cm,cp=m.project(ROOT,'data.csv')
test('quoted CSV newline and commas preserved',lambda:json.loads(cp[1]['text'])==['001','第一行\n第二行,引号"尾段'])
write('bad.csv','a,b\n"unclosed,value')
r=run('material_reader.py','read','--root',str(ROOT),'--file','bad.csv')
test('bad CSV returns structured failure',lambda:r.returncode==2 and json.loads(r.stdout)['ok'] is False and not r.stderr)
write('bad.pdf','not pdf')
test('unsupported formats never claim complete reading',lambda:rejects(lambda:m.project(ROOT,'bad.pdf')))
test('outside-root path rejected',lambda:rejects(lambda:m.project(ROOT,'../CANDIDATE-STATUS.txt')))
(ROOT/'linked.txt').symlink_to(ROOT/'long.txt')
test('symbolic-link material rejected',lambda:rejects(lambda:m.project(ROOT,'linked.txt')))
test('directory passed as file rejected',lambda:rejects(lambda:m.project(ROOT,'.')))
r=run('material_reader.py','read','--root',str(ROOT),'--file','long.txt','--sha256','0'*64)
test('changed material SHA blocks continuation',lambda:r.returncode==2 and 'changed' in r.stdout)
collected=[];start=0;pages=0
while True:
    r=run('material_reader.py','read','--root',str(ROOT),'--file','long.txt','--start',str(start),'--sha256',meta['sha256'])
    assert r.returncode==0,r.stderr
    lines=[json.loads(line) for line in r.stdout.splitlines()]
    assert lines[0]['type']=='page' and lines[-1]['type']=='page_end'
    assert len(lines)<=14
    collected.extend(line['text'] for line in lines if line['type']=='segment');pages+=1
    start=lines[-1]['next_start']
    if start is None:break
test('CLI pagination no gaps, repeated segments or lost tail',lambda:''.join(collected)==original and pages>1)
test('reader leaves source hash unchanged',lambda:hashlib.sha256((ROOT/'long.txt').read_bytes()).hexdigest()==meta['sha256'])
for count in ('0','13'):
    r=run('material_reader.py','read','--root',str(ROOT),'--file','long.txt','--count',count)
    test('invalid page count '+count,lambda:r.returncode==2)

with zipfile.ZipFile(ROOT/'sample.docx','w') as z:
    z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>正文</w:t><w:tab/><w:t>尾段</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>表格条件</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:del><w:r><w:delText>旧条件</w:delText></w:r></w:del></w:p></w:body></w:document>')
    z.writestr('word/footer1.xml','<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>页脚例外</w:t></w:r></w:p></w:ftr>')
    z.writestr('word/comments.xml','<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:comment w:id="1"><w:p><w:r><w:t>人工批注</w:t></w:r></w:p></w:comment></w:comments>')
dm,dp=m.project(ROOT,'sample.docx');dt=' '.join(p['text'] for p in dp)
test('DOCX paragraph, table, footer and comment represented',lambda:all(s in dt for s in ['正文\t尾段','表格条件','页脚例外','人工批注']))
test('DOCX deleted text explicitly marked',lambda:'[deleted:旧条件]' in dt)
test('DOCX projection disclaims visual/revision acceptance',lambda:any('revision' in s and 'layout' in s for s in dm['warnings']))

with zipfile.ZipFile(ROOT/'sample.xlsx','w') as z:
    z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="隐藏规则" state="hidden" sheetId="1" r:id="r1"/></sheets></workbook>')
    z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>')
    z.writestr('xl/sharedStrings.xml','<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>001</t></si></sst>')
    z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><f>1+2</f><v>2</v></c></row></sheetData></worksheet>')
xm,xp=m.project(ROOT,'sample.xlsx')
test('XLSX hidden sheet and leading zeros preserved',lambda:json.loads(xp[0]['text'])['state']=='hidden' and json.loads(xp[1]['text'])['value']=='001')
test('XLSX stale cache never claimed recalculated',lambda:json.loads(xp[2]['text'])['formula']=='1+2' and json.loads(xp[2]['text'])['cached_value_unverified'])
with zipfile.ZipFile(ROOT/'entity.docx','w') as z:
    z.writestr('word/document.xml','<!DOCTYPE x [<!ENTITY d "bad">]><x>&d;</x>')
test('XML entity declarations refused',lambda:rejects(lambda:m.project(ROOT,'entity.docx')))

source=[{'id':'001'},{'id':'002'}]
test('ID exact coverage passes',lambda:c.coverage(source,[{'id':'002'},{'id':'001'}],'id','id')['passed'])
test('equal count wrong objects fails',lambda:not c.coverage(source,[{'id':'001'},{'id':'003'}],'id','id')['passed'])
test('duplicate result IDs fail',lambda:not c.coverage(source,[{'id':'001'},{'id':'001'}],'id','id')['passed'])
test('duplicate source IDs not silently collapsed',lambda:not c.coverage(source+source,source,'id','id')['passed'])
test('numeric JSON identifiers are not coerced',lambda:rejects(lambda:c.ids([{'id':m.JSONNumber('001')}],'id')))
test('ID whitespace only trimmed when explicit',lambda:not c.coverage(source,[{'id':' 001 '},{'id':'002'}],'id','id')['passed'] and c.coverage(source,[{'id':' 001 '},{'id':'002'}],'id','id',True)['passed'])
details=[{'group':'a','n':'0.1'},{'group':'a','n':'0.2'},{'group':'b','n':'-1.5'}]
summary=[{'group':'a','total':'0.3'},{'group':'b','total':'-1.5'}]
test('Decimal groups reconcile exactly and retain negatives',lambda:c.reconcile(details,summary,'n','total','group')['passed'])
test('equal global total but wrong group totals fail',lambda:not c.reconcile(details,[{'group':'a','total':'-1.5'},{'group':'b','total':'0.3'}],'n','total','group')['passed'])
test('summary duplicate group rejected',lambda:rejects(lambda:c.reconcile(details,summary+summary,'n','total','group')))
test('blank values never become zero',lambda:rejects(lambda:c.totals([{'n':''}],'n',None)))
test('nonfinite numbers refused',lambda:rejects(lambda:c.totals([{'n':'Infinity'}],'n',None)))
test('more than 28 digits remain exact',lambda:str(c.totals([{'n':'123456789012345678901234567890.1'},{'n':'0.2'}],'n',None)['(all)'])=='123456789012345678901234567890.3')
test('large and tiny decimals summed without rounding',lambda:str(c.totals([{'n':'1E+40'},{'n':'0.000001'}],'n',None)['(all)'])=='10000000000000000000000000000000000000000.000001')
write('dup-header.csv','id,id\n001,002\n')
test('duplicate CSV columns refused',lambda:rejects(lambda:c.rows(ROOT,'dup-header.csv')))
write('short-row.csv','id,value\n001\n')
test('CSV short row refused',lambda:rejects(lambda:c.rows(ROOT,'short-row.csv')))
write('rows.json','{"items":[{"id":"001"},{"id":"002"}]}')
test('JSON pointer selects complete row array',lambda:c.rows(ROOT,'rows.json','/items')==source)
write('result.json','[{"id":"001"},{"id":"003"}]')
r=run('content_check.py','coverage','--root',str(ROOT),'--source','rows.json','--source-array','/items','--result','result.json')
test('CLI mismatch has failure exit and specific IDs',lambda:r.returncode==1 and json.loads(r.stdout)['missing_ids']==['002'] and json.loads(r.stdout)['unexpected_ids']==['003'])
report={'tests':len(results),'passed':sum(r['passed'] for r in results),'results':results,'fixture_root':str(ROOT)}
report['scope']='Synthetic deterministic tool checks only; not WorkBuddy semantic task acceptance'
print(json.dumps(report,ensure_ascii=False,indent=2))
sys.exit(0 if all(r['passed'] for r in results) else 1)
