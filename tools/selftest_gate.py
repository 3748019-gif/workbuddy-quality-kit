#!/usr/bin/env python3
"""Synthetic protocol tests only; no model, online access or personal fixtures."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parent
SCRIPTS = BASE / 'skills/workbuddy-quality-kit/scripts' if (BASE / 'skills').is_dir() else BASE.parent / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import content_gate as gate
from content_check import handoff


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gate-test-', dir=BASE)
        self.root = Path(self.temp.name).resolve()
        self.file = self.root / '成果 空格(一).md'
        self.file.write_text('合成报告；内容尚不代表语义验收。\n', encoding='utf-8')
        gate.initialize(str(self.root))
        self.start()

    def tearDown(self):
        self.temp.cleanup()

    def request(self, event='Stop', sid='session-a', generation='generation-a', **kw):
        return dict(hook_event_name=event, session_id=sid, generation_id=generation, cwd=str(self.root), **kw)

    def start(self, **kw):
        return gate.event(str(self.root), self.request('UserPromptSubmit', prompt='synthetic task', **kw))

    def receipt(self):
        return handoff(str(self.root), [self.file.name])

    def arm(self, **kw):
        return gate.register(str(self.root), self.receipt(), kw.get('sid', 'session-a'), kw.get('generation', 'generation-a'))

    def reply(self):
        return '\n'.join(self.receipt()['reply_lines'])

    def stop(self, text=None, **kw):
        return gate.event(str(self.root), self.request(last_assistant_message=self.reply() if text is None else text, **kw))

    def test_initializer_only_fragment(self):
        output = gate.initialize(str(self.root))
        self.assertTrue(output['merge_only'])
        self.assertFalse((self.root / '.codebuddy').exists())
        self.assertEqual(set(output['hooks']), {'UserPromptSubmit', 'Stop'})

    def test_initializer_rejects_unverified_platform(self):
        with patch.object(gate.os, 'name', 'nt'):
            with self.assertRaises(ValueError): gate.initialize(str(self.root))

    def test_initializer_unknown_owner_refused(self):
        (self.root / gate.DIRECTORY / 'owner.json').write_text('{}')
        with self.assertRaises(ValueError): gate.initialize(str(self.root))

    def test_initializer_unknown_directory_refused(self):
        other = self.root / 'other'; other.mkdir(); (other / gate.DIRECTORY).mkdir()
        with self.assertRaises(OSError): gate.initialize(str(other))

    def test_initializer_symlink_root_refused(self):
        link = self.root / 'alias'; link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError): gate.initialize(str(link))

    def test_unregistered_is_inactive(self):
        self.assertEqual(self.stop('free chat')[1]['gate_status'], 'inactive')

    def test_match_is_identity_only(self):
        self.arm(); code, result, _ = self.stop()
        self.assertEqual(code, 0)
        self.assertEqual(result['gate_status'], 'matched')
        self.assertNotIn('passed', result)

    def test_state_path_is_exposed_but_not_an_artifact(self):
        result = self.arm(); path = Path(result['state_file'])
        self.assertTrue(path.is_file()); self.assertTrue(path.is_relative_to(self.root / gate.DIRECTORY))
        self.assertNotIn(str(path), [item['path'] for item in self.receipt()['files']])

    def test_crlf_outer_whitespace_allowed(self):
        self.arm(); self.assertEqual(self.stop(' \n' + self.reply().replace('\n','\r\n') + '\n ')[1]['gate_status'], 'matched')

    def test_new_explanation_blocks_once(self):
        self.arm(); code, _, feedback = self.stop(self.reply() + '\n未经核对的新解释。')
        self.assertEqual(code, 2); self.assertIn(self.reply(), feedback)

    def test_changed_link_blocks(self):
        self.arm(); self.assertEqual(self.stop(self.reply().replace('具体内容', '结论正确'))[0], 2)

    def safe_link(self):
        target = '/safe/project/report.md'
        return ['文件已保存：', '- [report.md](<' + target + '>)', '具体内容见上述文件。']

    def test_safe_naked_target_equivalent(self):
        lines = self.safe_link(); text = '\n\n'.join(lines).replace('(</safe/project/report.md>)', '(/safe/project/report.md)')
        self.assertTrue(gate.receipt_text_matches(text, lines))

    def test_real_safe_file_naked_receipt_matches(self):
        self.file = self.root / 'report.md'; self.file.write_text('synthetic checked report')
        self.arm(); text = self.reply().replace('](<', '](').replace('>)', ')').replace('\n', '\n\n')
        self.assertEqual(self.stop(text)[1]['gate_status'], 'matched')

    def test_inert_line_spacing_equivalent(self):
        lines = self.safe_link(); text = '\n'.join('  ' + line + ' \t' for line in lines)
        self.assertTrue(gate.receipt_text_matches(text, lines))

    def test_label_change_rejected(self):
        lines = self.safe_link()
        self.assertFalse(gate.receipt_text_matches('\n'.join(lines).replace('[report.md]', '[结论已正确]'), lines))

    def test_target_change_rejected(self):
        lines = self.safe_link()
        self.assertFalse(gate.receipt_text_matches('\n'.join(lines).replace('/safe/project/', '/other/project/'), lines))

    def test_order_change_rejected(self):
        lines = self.safe_link(); swapped = [lines[1], lines[0], lines[2]]
        self.assertFalse(gate.receipt_text_matches('\n'.join(swapped), lines))

    def test_duplicate_link_rejected(self):
        lines = self.safe_link()
        self.assertFalse(gate.receipt_text_matches('\n'.join(lines + [lines[1]]), lines))

    def test_inline_business_assertion_rejected(self):
        lines = self.safe_link(); changed = list(lines); changed[1] += ' 所有结论正确'
        self.assertFalse(gate.receipt_text_matches('\n'.join(changed), lines))

    def test_hidden_html_comment_rejected(self):
        lines = self.safe_link()
        self.assertFalse(gate.receipt_text_matches('\n'.join(lines) + '\n<!-- 全部正确 -->', lines))

    def test_code_fence_rejected(self):
        lines = self.safe_link()
        self.assertFalse(gate.receipt_text_matches('```\n' + '\n'.join(lines) + '\n```', lines))

    def test_code_indent_rejected(self):
        lines = self.safe_link()
        self.assertFalse(gate.receipt_text_matches('\n'.join('    ' + line for line in lines), lines))

    def test_tab_indent_rejected(self):
        lines = self.safe_link()
        self.assertFalse(gate.receipt_text_matches('\n'.join('\t' + line for line in lines), lines))

    def test_space_path_still_requires_angles(self):
        lines = ['- [file](</safe/path with space.md>)']
        self.assertTrue(gate.receipt_text_matches(lines[0], lines))
        self.assertFalse(gate.receipt_text_matches('- [file](/safe/path with space.md)', lines))

    def test_parenthesis_path_still_requires_angles(self):
        lines = ['- [file](</safe/file(1).md>)']
        self.assertTrue(gate.receipt_text_matches(lines[0], lines))
        self.assertFalse(gate.receipt_text_matches('- [file](/safe/file(1).md)', lines))

    def test_encoded_alias_not_inferred(self):
        lines = ['- [file](</safe/path with space.md>)']
        self.assertFalse(gate.receipt_text_matches('- [file](/safe/path%20with%20space.md)', lines))

    def test_reference_style_not_inferred(self):
        lines = self.safe_link()
        self.assertFalse(gate.receipt_text_matches('文件已保存：\n- [report.md][r]\n具体内容见上述文件。\n[r]: /safe/project/report.md', lines))

    def test_second_failure_partial(self):
        self.arm(); self.stop('wrong'); code, result, _ = self.stop('still wrong')
        self.assertEqual(code, 0); self.assertEqual(result['gate_status'], 'partial'); self.assertIn('partial', result['systemMessage'])

    def test_later_failure_stays_partial(self):
        self.arm(); self.stop('bad'); self.stop('bad')
        self.assertEqual(self.stop('bad')[1]['gate_status'], 'partial')

    def test_correction_matches(self):
        self.arm(); self.stop('wrong'); self.assertEqual(self.stop()[1]['gate_status'], 'matched')

    def test_reregister_preserves_budget(self):
        self.arm(); self.stop('bad'); self.assertEqual(self.arm()['attempts_used'], 1)
        self.assertEqual(self.stop('bad')[1]['gate_status'], 'partial')

    def test_duplicate_prompt_is_idempotent(self):
        self.arm(); self.stop('bad'); self.start()
        self.assertEqual(self.stop('bad')[1]['gate_status'], 'partial')

    def test_internal_prompt_does_not_reset(self):
        self.arm(); self.stop('bad'); self.start(is_internal_continuation=True)
        self.assertEqual(self.stop('bad')[1]['gate_status'], 'partial')

    def test_new_user_turn_clears_receipt(self):
        self.arm(); self.start(generation='generation-b')
        self.assertEqual(self.stop('chat', generation='generation-b')[1]['gate_status'], 'inactive')

    def test_late_stop_cannot_block_new_turn(self):
        self.arm(); self.start(generation='generation-b'); self.arm(generation='generation-b')
        self.assertEqual(self.stop('bad')[1]['reason'], 'other_generation')
        self.assertEqual(self.stop(generation='generation-b')[1]['gate_status'], 'matched')

    def test_other_session_is_inactive(self):
        self.arm(); self.assertEqual(self.stop('chat', sid='session-b')[1]['gate_status'], 'inactive')

    def test_two_sessions_independent(self):
        self.arm(); self.start(sid='session-b'); self.arm(sid='session-b'); self.stop('bad')
        self.assertEqual(self.stop(sid='session-b')[1]['gate_status'], 'matched')

    def test_stop_active_flag_is_not_own_budget(self):
        self.arm(); self.assertEqual(self.stop('bad', stop_hook_active=True)[0], 2)

    def test_internal_stop_still_checks_match(self):
        self.arm(); self.assertEqual(self.stop(is_internal_continuation=True)[1]['gate_status'], 'matched')

    def test_internal_stop_still_checks_partial(self):
        self.arm(); self.stop('bad')
        self.assertEqual(self.stop('bad', is_internal_continuation=True)[1]['gate_status'], 'partial')

    def test_internal_stop_still_checks_changed_file(self):
        self.arm(); self.file.write_text('changed')
        self.assertEqual(self.stop('bad', is_internal_continuation=True)[0], 2)

    def test_optout_does_not_register(self):
        gate.event(str(self.root), self.request('UserPromptSubmit', generation='b', prompt='[quality:off] task'))
        with self.assertRaises(ValueError): self.arm(generation='b')
        self.assertEqual(self.stop('anything', generation='b')[1]['gate_status'], 'inactive')

    def test_other_project_not_touched(self):
        self.arm(); req = self.request(last_assistant_message='bad'); req['cwd'] = str(self.root.parent)
        self.assertEqual(gate.event(str(self.root), req)[1]['reason'], 'other_project')

    def test_wrong_generation_registration_refused(self):
        with self.assertRaises(ValueError): self.arm(generation='old')

    def test_no_environment_identity_refused(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError): gate.register(str(self.root), self.receipt())

    def test_artifact_changed_blocks(self):
        self.arm(); self.file.write_text('changed')
        code, _, feedback = self.stop('bad')
        self.assertEqual(code, 2); self.assertIn('重新核对', feedback)

    def test_rechecked_artifact_can_reregister(self):
        self.arm(); self.file.write_text('changed'); self.stop('bad'); self.arm()
        self.assertEqual(self.stop()[1]['gate_status'], 'matched')

    def test_deleted_artifact_blocks(self):
        self.arm(); self.file.unlink(); self.assertEqual(self.stop('bad')[0], 2)

    def test_forged_reply_rejected(self):
        receipt = self.receipt(); receipt['reply_lines'].append('结论一定正确')
        with self.assertRaises(ValueError): gate.register(str(self.root), receipt, 'session-a', 'generation-a')

    def test_outside_artifact_rejected(self):
        receipt = self.receipt(); receipt['files'][0]['path'] = str(self.root.parent / 'outside.txt')
        with self.assertRaises(ValueError): gate.register(str(self.root), receipt, 'session-a', 'generation-a')

    def test_artifact_symlink_refused(self):
        self.arm(); old = self.root / 'old'; self.file.rename(old); self.file.symlink_to(old)
        self.assertEqual(self.stop('bad')[0], 2)

    def test_format_parser_error_becomes_bounded_feedback(self):
        self.arm()
        with patch('content_check.handoff', side_effect=RuntimeError('synthetic format failure')):
            code, _, feedback = self.stop('bad')
        self.assertEqual(code, 2); self.assertIn('重新核对', feedback)

    def test_marker_symlink_refused(self):
        owner = self.root / gate.DIRECTORY / 'owner.json'; moved = owner.with_suffix('.old'); owner.rename(moved); owner.symlink_to(moved)
        with self.assertRaises(ValueError): self.arm()

    def test_state_symlink_refused(self):
        path = self.root / gate.DIRECTORY / ('session-' + gate.session_key('session-a') + '.json')
        path.unlink(); path.symlink_to(self.file)
        with self.assertRaises(ValueError): self.arm()

    def test_invalid_owner_failopen_cli(self):
        (self.root / gate.DIRECTORY / 'owner.json').write_text('{}')
        result = self.cli('event', self.request())
        self.assertEqual(result.returncode, 0); self.assertEqual(json.loads(result.stdout)['gate_status'], 'unavailable')

    def test_bad_json_failopen_cli(self):
        result = self.cli('event', '{broken', raw=True)
        self.assertEqual(result.returncode, 0); self.assertEqual(json.loads(result.stdout)['gate_status'], 'unavailable')

    def test_oversize_hook_input_failopen(self):
        result = self.cli('event', 'x' * (gate.INPUT_LIMIT + 1), raw=True)
        self.assertEqual(result.returncode, 0); self.assertEqual(json.loads(result.stdout)['gate_status'], 'unavailable')

    def test_duplicate_json_rejected(self):
        with self.assertRaises(ValueError): gate.parse(b'{"a":1,"a":2}')

    def test_bounded_lock_failure(self):
        lock = self.root / gate.DIRECTORY / ('session-' + gate.session_key('session-a') + '.lock'); lock.write_text('occupied')
        result = self.cli('event', self.request())
        self.assertEqual(json.loads(result.stdout)['gate_status'], 'unavailable'); self.assertTrue(lock.exists())

    def test_registration_cli_and_real_environment(self):
        env = dict(os.environ, CODEBUDDY_SESSION_ID='session-a', CODEBUDDY_CONVERSATION_REQUEST_ID='generation-a')
        script = gate.SCRIPT.with_name('content_check.py')
        result = subprocess.run([sys.executable, '-B', str(script), 'handoff', '--root', str(self.root), '--artifact', self.file.name, '--register-stop'], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['gate']['status'], 'armed')

    def test_nonhandoff_registration_refused(self):
        result = subprocess.run([sys.executable, '-B', str(gate.SCRIPT.with_name('content_check.py')), 'facts', '--root', str(self.root), '--register-stop'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

    def saved_reply(self, text='条件仍未满足；需再确认至少一项。\n\n未确认不等于不存在。\n'):
        directory = self.root / 'output'; directory.mkdir(exist_ok=True)
        path = directory / 'final_reply.md'; path.write_text(text, encoding='utf-8')
        return path

    def reply_receipt(self, text=None):
        path = self.saved_reply() if text is None else self.saved_reply(text)
        return handoff(str(self.root), [self.file.name], reply_file=str(path.relative_to(self.root)), reply_root='output')

    def test_reply_file_preserves_complete_required_answer(self):
        text = '至少一项满足即可。\n\n| 项目 | 状态 |\n|---|---|\n| 甲 | 未确认 |\n\n```python\n    x = 1\n```\n'
        result = self.reply_receipt(text)
        self.assertEqual('\n'.join(result['reply_lines']), text)
        self.assertEqual(result['reply_source']['sha256'], result['files'][-1]['sha256'])

    def test_reply_file_can_be_only_chat_artifact(self):
        path = self.saved_reply(); result = handoff(str(self.root), [], reply_file=str(path), reply_root='output')
        self.assertEqual(len(result['files']), 1)

    def test_reply_requires_explicit_output_scope(self):
        path = self.saved_reply()
        with self.assertRaises(ValueError): handoff(str(self.root), [], reply_file=str(path))

    def test_reply_scope_without_file_refused(self):
        with self.assertRaises(ValueError): handoff(str(self.root), [self.file.name], reply_root='output')

    def test_input_outside_declared_output_scope_refused(self):
        self.saved_reply()
        with self.assertRaises(ValueError): handoff(str(self.root), [], reply_file=self.file.name, reply_root='output')

    def test_reply_scope_outside_project_refused(self):
        path = self.saved_reply()
        with self.assertRaises(ValueError): handoff(str(self.root), [], reply_file=str(path), reply_root=str(self.root.parent))

    def test_reply_scope_symlink_refused(self):
        path = self.saved_reply(); alias = self.root / 'alias'; alias.symlink_to(path.parent, target_is_directory=True)
        with self.assertRaises(ValueError): handoff(str(self.root), [], reply_file=str(path), reply_root='alias')

    def test_reply_symlink_refused(self):
        path = self.saved_reply(); alias = path.parent / 'alias.md'; alias.symlink_to(path)
        with self.assertRaises(ValueError): handoff(str(self.root), [], reply_file=str(alias), reply_root='output')

    def test_reply_duplicate_artifact_refused(self):
        path = self.saved_reply()
        with self.assertRaises(ValueError): handoff(str(self.root), [str(path)], reply_file=str(path), reply_root='output')

    def test_reply_non_utf8_refused(self):
        path = self.saved_reply(); path.write_bytes(b'\xff')
        with self.assertRaises(UnicodeError): handoff(str(self.root), [], reply_file=str(path), reply_root='output')

    def test_reply_empty_refused(self):
        with self.assertRaises(ValueError): self.reply_receipt(' \n\t')

    def test_reply_control_characters_refused(self):
        with self.assertRaises(ValueError): self.reply_receipt('answer\x00hidden')

    def test_reply_oversize_rejected_without_truncation(self):
        path = self.saved_reply('a' * (8 * 1024 + 1))
        with self.assertRaises(ValueError): handoff(str(self.root), [], reply_file=str(path), reply_root='output')
        self.assertEqual(path.stat().st_size, 8 * 1024 + 1)

    def test_reply_hash_is_last_checked_hash(self):
        receipt = self.reply_receipt(); hashes = [item['sha256'] for item in receipt['files']]
        result = handoff(str(self.root), [self.file.name], hashes, 'output/final_reply.md', 'output')
        self.assertTrue(all(item['expected_version_matched'] for item in result['files']))

    def test_reply_wrong_checked_hash_rejected(self):
        receipt = self.reply_receipt(); hashes = [item['sha256'] for item in receipt['files']]; hashes[-1] = '0' * 64
        with self.assertRaises(ValueError): handoff(str(self.root), [self.file.name], hashes, 'output/final_reply.md', 'output')

    def test_reply_missing_last_hash_rejected(self):
        receipt = self.reply_receipt()
        with self.assertRaises(ValueError): handoff(str(self.root), [self.file.name], [receipt['files'][0]['sha256']], 'output/final_reply.md', 'output')

    def test_custom_reply_gate_matches_actual_file(self):
        receipt = self.reply_receipt(); gate.register(str(self.root), receipt, 'session-a', 'generation-a')
        self.assertEqual(self.stop('\n'.join(receipt['reply_lines']))[1]['gate_status'], 'matched')

    def test_custom_reply_changed_after_registration_detected(self):
        receipt = self.reply_receipt(); gate.register(str(self.root), receipt, 'session-a', 'generation-a')
        (self.root / 'output/final_reply.md').write_text('changed')
        self.assertEqual(self.stop('\n'.join(receipt['reply_lines']))[0], 2)

    def test_artifact_change_invalidates_custom_reply_receipt(self):
        receipt = self.reply_receipt(); gate.register(str(self.root), receipt, 'session-a', 'generation-a'); self.file.write_text('changed')
        self.assertEqual(self.stop('\n'.join(receipt['reply_lines']))[0], 2)

    def test_custom_reply_free_expected_text_rejected(self):
        receipt = self.reply_receipt(); receipt['reply_lines'] = ['自行宣称的不同结论']
        with self.assertRaises(ValueError): gate.register(str(self.root), receipt, 'session-a', 'generation-a')

    def test_custom_reply_source_hash_forgery_rejected(self):
        receipt = self.reply_receipt(); receipt['reply_source']['sha256'] = '0' * 64
        with self.assertRaises(ValueError): gate.register(str(self.root), receipt, 'session-a', 'generation-a')

    def test_custom_reply_scope_drift_rejected(self):
        receipt = self.reply_receipt(); other = self.root / 'other'; other.mkdir(); receipt['reply_source']['output_root'] = str(other)
        with self.assertRaises(ValueError): gate.register(str(self.root), receipt, 'session-a', 'generation-a')

    def test_custom_reply_preserves_code_indentation(self):
        expected = '```python\n    x = 1\n```'
        self.assertFalse(gate.saved_reply_matches(expected.replace('    x', 'x'), expected))

    def test_custom_reply_preserves_internal_blank_lines(self):
        self.assertFalse(gate.saved_reply_matches('one\ntwo', 'one\n\ntwo'))

    def test_custom_reply_preserves_table_spacing(self):
        self.assertFalse(gate.saved_reply_matches('|a|b|', '| a | b |'))

    def test_custom_reply_crlf_and_outer_blank_lines_allowed(self):
        self.assertTrue(gate.saved_reply_matches('\r\ntext\r\n\r\n', 'text\n'))

    def test_custom_reply_rejects_extra_claim(self):
        receipt = self.reply_receipt(); gate.register(str(self.root), receipt, 'session-a', 'generation-a')
        self.assertEqual(self.stop('\n'.join(receipt['reply_lines']) + '已全部可用。')[0], 2)

    def test_custom_reply_cli_does_not_truncate_long_line(self):
        path = self.saved_reply('段' * 400)
        result = subprocess.run([sys.executable, '-B', str(gate.SCRIPT.with_name('content_check.py')), 'handoff', '--root', str(self.root), '--reply-file', str(path), '--reply-root', 'output'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('reply_lines', json.loads(result.stdout)); self.assertEqual(path.read_text(), '段' * 400)

    def cli(self, command, request, raw=False):
        return subprocess.run([sys.executable, '-B', str(gate.SCRIPT), command, '--project-root', str(self.root)],
                              input=request if raw else json.dumps(request), capture_output=True, text=True, timeout=3)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(GateTests)
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
    print(json.dumps({'passed': result.testsRun - len(result.failures) - len(result.errors),
                      'total': result.testsRun, 'scope': 'synthetic gate protocol, not GUI or semantic acceptance'}))
    raise SystemExit(0 if result.wasSuccessful() else 1)
