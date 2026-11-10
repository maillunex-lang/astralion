#!/usr/bin/env python3
"""Негативные регрессионные проверки документационного валидатора."""
import shutil
import json
import re
from pathlib import Path
import tempfile
import unittest

from check_development_docs import validate

ROOT = Path(__file__).resolve().parents[1]


class DocumentationValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / 'docs', self.root / 'docs')
        for name in ['README.md', 'AGENTS.md']:
            shutil.copy2(ROOT / name, self.root / name)

    def change(self, relative, old, new):
        path = self.root / relative
        text = path.read_text(encoding='utf-8')
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding='utf-8')

    def rejected(self, expected):
        errors, _ = validate(self.root)
        self.assertTrue(any(expected in e for e in errors), errors)

    def test_baseline(self):
        errors, counts = validate(self.root)
        self.assertEqual(errors, [])
        self.assertGreater(counts['этапов'], 0)
        self.assertGreater(counts['задач'], 0)
        self.assertEqual(sum(counts['статусы'].values()), counts['задач'])

    def test_broken_link(self):
        self.change('README.md', '](AGENTS.md)', '](MISSING.md)')
        self.rejected('нет цели ссылки')

    def test_missing_anchor(self):
        self.change('docs/development/tasks/FOUNDATION-001.md', '#control-ship-only', '#missing-anchor')
        self.rejected('нет якоря')

    def test_duplicate_id(self):
        stage = self.root / 'docs/development/stages/01-FOUNDATION.md'
        row = next(line for line in stage.read_text(encoding='utf-8').splitlines() if line.startswith('| FOUNDATION-001 |'))
        stage.write_text(stage.read_text(encoding='utf-8') + '\n' + row + '\n', encoding='utf-8')
        self.rejected('Повтор ID задачи')

    def test_invalid_status(self):
        self.change('docs/development/stages/01-FOUNDATION.md', '| FOUNDATION-001 | P0 | TODO |', '| FOUNDATION-001 | P0 | READY |')
        self.rejected('неверный статус READY')

    def test_missing_dependency(self):
        self.change('docs/development/stages/01-FOUNDATION.md', '| AUDIT-004 |', '| MISSING-001 |')
        self.rejected('отсутствующая зависимость MISSING-001')

    def test_cycle(self):
        self.change('docs/development/stages/01-FOUNDATION.md', '| AUDIT-004 |', '| FOUNDATION-003 |')
        self.rejected('Цикл задач:')

    def test_stage_status_mismatch(self):
        self.change('docs/development/stages/01-FOUNDATION.md', '**Статус:** TODO', '**Статус:** DONE')
        self.rejected('не соответствует задачам')

    def test_task_mirror_mismatch(self):
        self.change('docs/development/tasks/FOUNDATION-001.md', '**Статус:** TODO', '**Статус:** DONE')
        self.rejected('TASK/Статус не совпадает')

    def test_done_before_dependency(self):
        self.change('docs/development/stages/01-FOUNDATION.md', '| FOUNDATION-002 | P0 | TODO |', '| FOUNDATION-002 | P0 | DONE |')
        self.rejected('DONE при незавершённой зависимости FOUNDATION-001')

    def test_roadmap_progress_mismatch(self):
        self.change('docs/development/ROADMAP.md', '| 0/3 |', '| 3/3 |')
        self.rejected('счёт ROADMAP не совпадает')

    def test_missing_decision(self):
        self.change('docs/development/DECISIONS_INDEX.md', '</a>CONCEPT-001 |', '</a>NONEXISTENT-001 |')
        self.rejected('Покрытие исходных ID')

    def test_modified_source(self):
        source = self.root / 'GAME.md'
        source.write_text('# Изменённый источник\n', encoding='utf-8')
        errors, _ = validate(self.root, source)
        self.assertTrue(any('SHA-256 не совпадает' in e for e in errors), errors)

    def test_invalid_task_id_is_not_silently_skipped(self):
        self.change('docs/development/stages/01-FOUNDATION.md', '| FOUNDATION-003 |', '| FOUNDATION_003 |')
        self.rejected('неверный ID задачи')

    def test_blank_decision_description(self):
        path = self.root / 'docs/development/DECISIONS_INDEX.md'
        text = path.read_text(encoding='utf-8')
        changed, count = re.subn(r'(</a>SCENE-02-DETAIL \|)[^|]+', r'\1 ', text, count=1)
        self.assertEqual(count, 1)
        path.write_text(changed, encoding='utf-8')
        self.rejected('пустое описание')

    def test_index_task_points_to_its_stage(self):
        self.change('docs/development/DECISIONS_INDEX.md',
                    '[FOUNDATION-001](stages/01-FOUNDATION.md)',
                    '[FOUNDATION-001](stages/03-SERVER.md)')
        self.rejected('ссылается на чужой этап')

    def test_unknown_index_task(self):
        self.change('docs/development/DECISIONS_INDEX.md',
                    '[FOUNDATION-001](stages/01-FOUNDATION.md)',
                    '[NONEXISTENT-999](stages/01-FOUNDATION.md)')
        self.rejected('неизвестная связанная задача')

    def test_empty_manifest(self):
        path = self.root / 'docs/development/SOURCE_MANIFEST.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['entries'] = []
        path.write_text(json.dumps(manifest), encoding='utf-8')
        self.rejected('непустой список записей')

    def test_source_line_range(self):
        path = self.root / 'docs/development/SOURCE_MANIFEST.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['entries'][0]['end'] = manifest['lines'] + 1
        path.write_text(json.dumps(manifest), encoding='utf-8')
        self.rejected('неверный диапазон')

    def test_source_link_cannot_change_commit(self):
        self.change('docs/development/DECISIONS_INDEX.md',
                    '/34fa8738fb97a78127b598283de51d782b03d23a/GAME.md#L6-L20',
                    '/main/GAME.md#L6-L20')
        self.rejected('диапазону/commit источника')

    def test_stage_id_matches_filename(self):
        self.change('docs/development/stages/01-FOUNDATION.md', '**ID:** STAGE-01', '**ID:** STAGE-99')
        self.rejected('ID этапа не совпадает с именем файла')

    def test_stage_priority_mirror(self):
        self.change('docs/development/stages/01-FOUNDATION.md', '**Приоритет:** P0', '**Приоритет:** P4')
        self.rejected('приоритет ROADMAP не совпадает')

    def test_task_stage_mirror(self):
        self.change('docs/development/tasks/FOUNDATION-001.md', '../stages/01-FOUNDATION.md', '../stages/03-SERVER.md')
        self.rejected('ссылка TASK на другой этап')

    def test_duplicate_task_dependency(self):
        self.change('docs/development/tasks/FOUNDATION-001.md', '**Зависимости:** AUDIT-004',
                    '**Зависимости:** AUDIT-004, AUDIT-004')
        self.rejected('повтор зависимости в TASK')

    def test_task_list_status_mirror(self):
        self.change('docs/development/tasks/README.md',
                    '[FOUNDATION-001](FOUNDATION-001.md) | TODO',
                    '[FOUNDATION-001](FOUNDATION-001.md) | DONE')
        self.rejected('статус в списке TASK не совпадает')

    def test_review_reading_coverage_has_no_gaps(self):
        self.change('docs/development/handoffs/FULL-REVIEW.md', '| 204–420 |', '| 205–420 |')
        self.rejected('пропуск/перекрытие диапазонов')

    def test_mvp_gate_includes_real_verifications(self):
        # Правило приёмки из GAME.md: нельзя завершить MVP только локальным smoke.
        dependencies = {}
        for path in (self.root / 'docs/development/stages').glob('*.md'):
            for line in path.read_text(encoding='utf-8').splitlines():
                if re.match(r'^\| [A-Z][A-Z0-9]*-\d{3} \|', line):
                    cells = [c.strip() for c in line.strip('|').split('|')]
                    dependencies[cells[0]] = [] if cells[3] == '—' else cells[3].split(', ')
        pending, ancestors = ['TEST-002'], set()
        while pending:
            task = pending.pop()
            if task not in ancestors:
                ancestors.add(task)
                pending.extend(dependencies[task])
        self.assertTrue({'INFRA-005', 'NET-004', 'INFRA-002', 'PERF-002',
                         'CLIENT-004', 'ASSET-004', 'INFRA-003'} <= ancestors)


if __name__ == '__main__':
    unittest.main(verbosity=2)
