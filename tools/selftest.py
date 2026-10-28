"""Offline checks in an isolated temporary directory; never touches WorkBuddy settings.
Run before deployment with the same Python interpreter intended for installation.
"""
from contextlib import nullcontext
from unittest.mock import patch
from pathlib import Path
from decimal import Decimal
import csv, importlib.util, json, os, shutil, sys, tempfile, zipfile
sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def main():
    installer = load('quality_installer', BASE / 'install_skill.py')
    guard = load('quality_guard', BASE / 'skills/workbuddy-quality-kit/scripts/office_guard.py')
    task_guard = load('task_guard', BASE / 'skills/workbuddy-quality-kit/scripts/task_guard.py')
    results = []
    def test(name, fn):
        try:
            assert fn(), 'Invariant failed'
            results.append({'case': name, 'passed': True})
        except Exception as error:
            results.append({'case': name, 'passed': False, 'error': str(error)})
    def refuses(fn):
        try: fn()
        except (ValueError, FileExistsError): return True
        return False
    # Retain only these synthetic fixtures for inspection; no directory deletion
    # is needed to prove installation safeguards in a managed runtime.
    with nullcontext(tempfile.mkdtemp(dir=BASE, prefix='workbuddy-quality-test-')) as temporary:
        t = Path(temporary)
        root = t / 'skills'; root.mkdir()
        receipts = t / 'receipts'; receipts.mkdir()
        original = root / 'existing'; original.mkdir()
        (original / 'SKILL.md').write_text('Existing skill', encoding='utf-8')
        settings = t / 'settings.json'; settings.write_text('{"custom":true}', encoding='utf-8')
        before = (installer.tree(original), settings.read_bytes())
        target = root / installer.NAME; receipt = receipts / 'install.json'
        test('plan does not write', lambda: installer.plan(root)['status'] == 'add' and not target.exists())
        test('fresh isolated installation', lambda: installer.apply(root, receipt)['status'] == 'installed_files_only')
        test('installed contents match', lambda: installer.plan(root)['status'] == 'reuse')
        test('repeat installation creates no receipt', lambda: installer.apply(root, receipts / 'second.json')['status'] == 'reuse' and not (receipts / 'second.json').exists())
        test('existing settings preserved', lambda: before == (installer.tree(original), settings.read_bytes()))
        entry = target / 'SKILL.md'; old = entry.read_bytes(); entry.write_text('Later user edit', encoding='utf-8')
        test('changed namesake is not overwritten', lambda: installer.apply(root, receipts / 'third.json')['status'] == 'conflict' and entry.read_text() == 'Later user edit')
        test('later edit blocks rollback', lambda: refuses(lambda: installer.rollback(root, receipt)) and target.exists())
        entry.write_bytes(old)
        added = target / 'user-added.txt'; added.write_text('Keep', encoding='utf-8')
        test('new file blocks rollback', lambda: refuses(lambda: installer.rollback(root, receipt)) and added.exists())
        added.rename(t / 'preserved-added-file.txt')
        extra = target / 'empty-user-directory'; extra.mkdir()
        test('new directory blocks rollback', lambda: refuses(lambda: installer.rollback(root, receipt)) and extra.exists())
        extra.rename(t / 'preserved-extra-directory')
        test('wrong root blocks rollback', lambda: refuses(lambda: installer.rollback(receipts, receipt)))
        test('unchanged owned skill can be archived', lambda: Path(installer.rollback(root, receipt)['archive']).is_dir() and not target.exists())
        target.mkdir()
        test('empty namesake directory is preserved', lambda: installer.apply(root, receipts / 'empty.json')['status'] == 'conflict' and target.is_dir())
        target.rename(t / 'preserved-empty-namesake')
        test('existing receipt is preserved', lambda: refuses(lambda: installer.apply(root, receipt)))
        test('receipt cannot be placed in skills root', lambda: refuses(lambda: installer.apply(root, root / 'receipt.json')))
        test('missing root is not auto-created', lambda: refuses(lambda: installer.plan(t / 'missing')) and not (t / 'missing').exists())
        source = t / 'source.txt'; source.write_text('original', encoding='utf-8')
        manifest = t / 'manifest.json'; guard.snapshot(t, ['source.txt'], manifest)
        test('unchanged source verified', lambda: guard.check(t, manifest)['ok'])
        source.write_text('changed', encoding='utf-8')
        test('changed source detected', lambda: not guard.check(t, manifest)['ok'])
        empty = t / 'empty.json'; empty.write_text('{"files":{}}', encoding='utf-8')
        test('empty manifest refused', lambda: refuses(lambda: guard.check(t, empty)))
        test('input cannot be a report destination', lambda: refuses(lambda: guard.protect_report(source, [source])))
        doc = t / 'before.docx'; same = t / 'same.docx'; bad = t / 'bad.docx'
        xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>old</w:t></w:r></w:p></w:body></w:document>'
        with zipfile.ZipFile(doc, 'w') as z:
            z.writestr('word/document.xml', xml)
            z.writestr('word/header1.xml', '<header>unchanged</header>')
        shutil.copyfile(doc, same)
        test('identical structure accepted', lambda: guard.diff(doc, same, {})['ok'])
        test('unknown allowed-change key refused', lambda: refuses(lambda: guard.diff(doc, same, {'xlsx_cellz': []})))
        test('string boolean refused', lambda: refuses(lambda: guard.diff(doc, same, {'formula_cache_may_change': 'false'})))
        test('boolean is not numeric one', lambda: not guard.numeric_equal(True, 1))
        with zipfile.ZipFile(bad, 'w') as z:
            z.writestr('word/document.xml', xml)
            z.writestr('word/header1.xml', '<header>unexpected</header>')
        test('unexpected header edit detected', lambda: not guard.diff(doc, bad, {})['ok'])
        for tag, ns, part in [('delText', guard.NS['w'], 'word/document.xml'),
                              ('instrText', guard.NS['w'], 'word/document.xml'),
                              ('v', guard.NS['s'], 'xl/worksheets/sheet1.xml')]:
            for path, text in [(doc, ' '), (bad, '')]:
                with zipfile.ZipFile(path, 'w') as z:
                    z.writestr(part, '<root xmlns:x="'+ns+'"><x:'+tag+'>'+text+'</x:'+tag+'></root>')
            test('significant whitespace in '+tag+' preserved', lambda: not guard.diff(doc, bad, {})['ok'])
        for path, text in [(doc, '<root><item>value</item></root>'),
                           (same, '<root>\n  <item>value</item>\n</root>')]:
            with zipfile.ZipFile(path, 'w') as z: z.writestr('word/document.xml', text)
        test('XML indentation remains ignorable', lambda: guard.diff(doc, same, {})['ok'])
        task_input=t/'task-input';task_output=t/'task-output';task_input.mkdir();task_output.mkdir()
        sample=task_input/'source.txt';sample.write_text('keep',encoding='utf-8')
        delivered=task_output/'result.json';delivered.write_text('{"old":true}',encoding='utf-8')
        snapshot=task_guard.snapshot(t,['task-input'])
        test('task same path refused',lambda:refuses(lambda:task_guard.check_separation([sample],[sample],t)))
        test('task required output verified',lambda:task_guard.verify(t,snapshot,['task-output/result.json'])['passed'] and task_guard.verify(os.path.relpath(t,Path.cwd()),snapshot,['task-output/result.json'])['passed'])
        test('task missing output fails',lambda:not task_guard.verify(t,snapshot,['task-output/missing.json'])['passed'])
        sample.write_text('changed',encoding='utf-8')
        test('task changed input fails',lambda:not task_guard.verify(t,snapshot,['task-output/result.json'])['passed'])
        sample.write_text('keep',encoding='utf-8')
        def reject_candidate(p):raise ValueError('test validation failure')
        test('task candidate failure preserves output',lambda:refuses(lambda:task_guard.atomic_write(delivered,b'{bad',inputs=[sample],root=t,validate=reject_candidate)) and delivered.read_text()=='{"old":true}')
        test('task relative output respects root',lambda:task_guard.atomic_write('task-output/new.json',b'{"new":true}',inputs=['task-input/source.txt'],root=t) is None and (task_output/'new.json').exists())
        report = task_output/'summary.txt'; report.write_text('old summary', encoding='utf-8')
        dependencies={'task-output/result.json':['task-input'], 'task-output/summary.txt':['task-output/result.json']}
        checkpoint=task_guard.checkpoint(t,['task-input'],list(dependencies),dependencies)
        test('saved checkpoint versions match',lambda:task_guard.resume(t,checkpoint)['passed'])
        sample.write_text('new version',encoding='utf-8')
        test('changed input invalidates dependent reports',lambda:task_guard.resume(t,checkpoint)['recheck_outputs']==['task-output/result.json','task-output/summary.txt'])
        sample.write_text('keep',encoding='utf-8')
        delivered.write_text('{"manual_note":"KEEP"}',encoding='utf-8')
        test('later manual edit preserved and reported',lambda:task_guard.resume(t,checkpoint)['modified_outputs_preserve_and_review']==['task-output/result.json'] and delivered.read_text()=='{"manual_note":"KEEP"}')
        report.rename(task_output/'user-archived-summary.txt')
        test('missing result is not silently restored',lambda:'task-output/summary.txt' in task_guard.resume(t,checkpoint)['missing_outputs'] and not report.exists())
        test('all original simulated configuration retained', lambda: before == (installer.tree(original), settings.read_bytes()))
        fixtures=BASE/'验收材料';reference=json.loads((fixtures/'验收预期.json').read_text(encoding='utf-8'))
        test('acceptance reference binds actual input versions',lambda:all(installer.digest(fixtures/name)==sha for name,sha in reference['inputs'].items()))
        def acceptance_arithmetic():
            with (fixtures/'records.csv').open(encoding='utf-8',newline='') as handle: rows=list(csv.DictReader(handle))
            totals={'A':Decimal(0),'B':Decimal(0)}
            for item in reference['expected']['included']:
                for line in item['source_rows']:
                    row=rows[line-2]
                    if (row['编号'].strip(),row['批次'],Decimal(row['数值'])) != (item['id'],item['batch'],Decimal(item['value'])): return False
                totals[item['batch']]+=Decimal(item['value'])
            totals['all']=sum(totals.values(),Decimal(0))
            return all(value==Decimal(reference['expected']['totals'][key]) for key,value in totals.items())
        test('acceptance arithmetic agrees with actual source rows',acceptance_arithmetic)
        cohort=t/'cohort';cohort.mkdir()
        for name in ['input','output','publication']:(cohort/name).mkdir()
        (cohort/'input/source.txt').write_text('fictional source',encoding='utf-8')
        payloads={'output/a.json':b'{"v":1}','output/b.txt':b'first'}
        def check_saved(paths):return all(paths[n].read_bytes()==value for n,value in payloads.items())
        def publish_group(validate=check_saved,input_state=None):
            return task_guard.publish_set(cohort,payloads,inputs=['input'],workdir='publication',validate=validate,input_state=input_state)
        def active_journal():return json.loads((cohort/'publication/quality-publish-active.json').read_text(encoding='utf-8'))['journal']
        test('complete multi-file cohort is published and checked',lambda:publish_group()['state']=='committed' and check_saved({n:cohort/n for n in payloads}))
        def repeat_group():
            before=sorted(p.name for p in (cohort/'publication').iterdir())
            return publish_group()['state']=='unchanged' and before==sorted(p.name for p in (cohort/'publication').iterdir())
        test('unchanged group does not add generations',repeat_group)
        original_payloads=dict(payloads);payloads={'output/a.json':b'{"v":2}','output/b.txt':b'second'}
        test('failed candidate check retains complete old group',lambda:refuses(lambda:publish_group(lambda paths:False)) and all((cohort/n).read_bytes()==v for n,v in original_payloads.items()))
        def interrupt_group():
            original=task_guard._publish_one;calls=0
            def interrupt(target,saved,**kwargs):
                nonlocal calls
                calls+=1
                if calls==2:raise SystemExit(77)
                return original(target,saved,**kwargs)
            with patch.object(task_guard,'_publish_one',interrupt):
                try:publish_group()
                except SystemExit as error:return error.code==77
            return False
        def pending_group():
            return interrupt_group() and task_guard.recover_set(cohort,active_journal())['recovery_needed'] and refuses(publish_group)
        test('interrupted group is pending and blocks another publication',pending_group)
        test('pending rollback restores the entire old group',lambda:task_guard.recover_set(cohort,active_journal(),'rollback')['state']=='rolled_back' and all((cohort/n).read_bytes()==v for n,v in original_payloads.items()))
        test('pending commit finishes the complete new group',lambda:interrupt_group() and task_guard.recover_set(cohort,active_journal(),'commit')['passed'] and check_saved({n:cohort/n for n in payloads}))
        payloads={'output/a.json':b'{"v":3}','output/b.txt':b'third'}
        def manual_group_conflict():
            if not interrupt_group():return False
            (cohort/'output/b.txt').write_bytes(b'human addition')
            return refuses(lambda:task_guard.recover_set(cohort,active_journal(),'rollback')) and (cohort/'output/b.txt').read_bytes()==b'human addition'
        test('later human edit is preserved during recovery',manual_group_conflict)
        def stale_group_input():
            baseline=task_guard.snapshot(cohort,['input'])
            before={n:(cohort/n).read_bytes() for n in payloads}
            (cohort/'input/source.txt').write_text('new fictional input',encoding='utf-8')
            return refuses(lambda:publish_group(input_state=baseline)) and all((cohort/n).read_bytes()==v for n,v in before.items())
        test('stale computation input blocks group publication',stale_group_input)
        reviewed=t/'reviewed-output';reviewed.mkdir()
        for name in ('input','output','publication'):(reviewed/name).mkdir()
        (reviewed/'input/source.txt').write_text('source',encoding='utf-8')
        note=reviewed/'output/note.txt';note.write_text('old human note',encoding='utf-8')
        reviewed_state=task_guard.review_outputs(reviewed,['output/note.txt'])
        note.write_text('later human note',encoding='utf-8')
        def publish_reviewed(state):
            return task_guard.publish_set(reviewed,{'output/note.txt':b'later human note plus new result'},inputs=['input'],workdir='publication',validate=lambda paths:paths['output/note.txt'].read_bytes()==b'later human note plus new result',output_state=state)
        test('later human edit blocks a stale computed candidate',lambda:refuses(lambda:publish_reviewed(reviewed_state)) and note.read_text()=='later human note')
        fresh_review=task_guard.review_outputs(reviewed,['output/note.txt'])
        test('reviewed human content can be intentionally merged and published',lambda:publish_reviewed(fresh_review)['state']=='committed' and note.read_text()=='later human note plus new result')
        absent=task_guard.review_outputs(reviewed,['output/new-user-file.txt']);(reviewed/'output/new-user-file.txt').write_text('user created meanwhile',encoding='utf-8')
        test('newly appeared user output is not overwritten by an old absent baseline',lambda:refuses(lambda:task_guard.publish_set(reviewed,{'output/new-user-file.txt':b'candidate'},inputs=['input'],workdir='publication',validate=lambda paths:True,output_state=absent)) and (reviewed/'output/new-user-file.txt').read_text()=='user created meanwhile')
        # Real subprocess behavior, confined to these fictional task fixtures.
        sys.path.insert(0, str(BASE/'skills/workbuddy-quality-kit/scripts'))
        runner=load('quality_run_guard',BASE/'skills/workbuddy-quality-kit/scripts/run_guard.py')
        entry_installer=load('quality_entry_installer',BASE/'install_entry.py')
        command_root=t/'command-cases';command_root.mkdir();(command_root/'work').mkdir();(command_root/'input').mkdir()
        (command_root/'input/source.txt').write_text('keep',encoding='utf-8')
        def run_code(code,name,**kw):
            return runner.run_checked(command_root,[sys.executable,'-c',code],state='work/'+name+'.json',evidence=['input'],**kw)
        test('command runner retains real success status',lambda:run_code("print('done')",'normal')['returncode']==0)
        test('failed process not hidden by printed exit zero',lambda:(lambda r:not r['ok'] and r['returncode']==7)(run_code("print('exit=0');raise SystemExit(7)",'nonzero')))
        test('JSON failure detected despite process exit zero',lambda:(lambda r:not r['ok'] and r['returncode']==0)(run_code("print('{\"ok\":false}')",'semantic')))
        def limited_retry():
            code="raise SystemExit(3)"
            a=run_code(code,'retry');b=run_code(code,'retry');c=run_code(code,'retry')
            return not a['ok'] and not b['ok'] and c['blocked'] and not c['executed']
        test('unchanged failure stops before a third execution',limited_retry)
        test('real timeout is bounded',lambda:(lambda r:r['timed_out'] and not r['ok'])(run_code('import time;time.sleep(10)','timeout',timeout=.1)))
        test('required missing file is not reported complete',lambda:not run_code("print('done')",'required',expected=['work/missing.txt'])['ok'])
        test('runner state cannot replace a protected input',lambda:refuses(lambda:runner.run_checked(command_root,[sys.executable,'-c',"print('x')"],state='input/source.txt',evidence=['input'])))
        test('failure words in ordinary result are not misclassified',lambda:run_code("print('{\"ok\":true,\"literal\":\"permission denied; sitecustomize error\"}')",'literal')['ok'])
        entry_settings=t/'entry-settings.json';entry_settings.write_text('{"custom":{"keep":true},"hooks":{"Stop":[]}}',encoding='utf-8')
        entry_original=entry_settings.read_bytes();entry_receipt=t/'entry-receipt.json'
        skill_root=BASE/'skills/workbuddy-quality-kit'
        test('entry plan makes no settings changes',lambda:entry_installer.plan(entry_settings,skill_root,sys.executable)['status']=='add' and entry_settings.read_bytes()==entry_original)
        test('entry install preserves unrelated configuration',lambda:entry_installer.apply(entry_settings,skill_root,sys.executable,entry_receipt)['status']=='installed_files_only' and json.loads(entry_settings.read_text())['custom']=={'keep':True} and json.loads(entry_settings.read_text())['hooks']['Stop']==[])
        test('entry repeated install reuses without another receipt',lambda:entry_installer.apply(entry_settings,skill_root,sys.executable,t/'entry-unused.json')['status']=='reuse' and not (t/'entry-unused.json').exists())
        changed_entry=json.loads(entry_settings.read_text());changed_entry['later_user_note']='keep';entry_settings.write_text(json.dumps(changed_entry),encoding='utf-8')
        test('entry rollback retains later user configuration',lambda:entry_installer.rollback(entry_settings,entry_receipt)['status']=='rolled_back' and json.loads(entry_settings.read_text())=={'custom':{'keep':True},'hooks':{'Stop':[]},'later_user_note':'keep'})
        entry_gate=load('quality_entry_gate',skill_root/'scripts/entry_gate.py')
        trace_dir=t/'projects/fictional';trace_dir.mkdir(parents=True);trace=trace_dir/'session.jsonl'
        def save_trace(entries):
            trace.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in [{'type':'session-meta','sessionId':'fictional'}]+entries)+'\n',encoding='utf-8')
        def gate_result(tool='Bash'):
            return entry_gate.decision({'hook_event_name':'PreToolUse','tool_name':tool,'transcript_path':str(trace)})
        def read_pair(key,name,completed=True):
            f=skill_root/name
            return [{'type':'function_call','callId':key,'name':'Read','arguments':json.dumps({'file_path':str(f)})},{'type':'function_call_result','callId':key,'status':'completed' if completed else 'error','output':repr({'type':'text','text':f.read_text(encoding='utf-8')})}]
        save_trace([])
        test('quality entry waits for current skill reads',lambda:gate_result()[1]==2)
        test('quality entry never blocks Read itself',lambda:gate_result('Read')==({},0))
        save_trace(read_pair('m','SKILL.md'))
        test('execution reference is read before implementation',lambda:gate_result()[1]==2)
        save_trace(read_pair('m','SKILL.md')+read_pair('e','references/execution-review.md'))
        test('completed current instructions permit continuation',lambda:gate_result()==({},0))
        save_trace(read_pair('m','SKILL.md',False)+read_pair('e','references/execution-review.md'))
        test('failed instruction read is not accepted',lambda:gate_result()[1]==2)
        save_trace([{'type':'message','role':'user','content':[{'type':'input_text','text':'<user_query>[quality:off] one task</user_query>'}]}])
        test('human per-turn quality opt-out is retained',lambda:gate_result()==({},0))
        trace.write_text('{"type":"unknown-provider-record"}\n',encoding='utf-8')
        test('unknown transcript does not lock the application',lambda:gate_result()[1]==0)
    result = {'passed': sum(r['passed'] for r in results), 'total': len(results), 'cases': results,
              'scratch_directory': str(t), 'scratch_retained': True,
              'cleanup_note': 'Synthetic fixtures retained for inspection; no directory cleanup required.',
              'scope': 'Local deterministic file safeguards only; not application discovery, model capability, Windows UI or visual Office validation.'}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['passed'] == result['total'] else 1

if __name__ == '__main__': sys.exit(main())
