#!/usr/bin/env python3
"""Негативные регрессионные проверки документационного валидатора."""
import shutil
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
        self.assertEqual(counts['этапов'], 23)
        self.assertEqual(counts['задач'], 101)

    def test_broken_link(self):
        self.change('README.md', '](AGENTS.md)', '](MISSING.md)')
        self.rejected('нет цели ссылки')

    def test_missing_anchor(self):
        self.change('docs/development/tasks/FOUNDATION-001.md', '#control-ship-only', '#missing-anchor')
        self.rejected('нет якоря')

    def test_duplicate_id(self):
        stage = self.root / 'docs/development/stages/01-FOUNDATION.md'
        row = next(line for line in stage.read_text().splitlines() if line.startswith('| FOUNDATION-001 |'))
        stage.write_text(stage.read_text() + '\n' + row + '\n')
        self.rejected('Повтор ID задачи')

    def test_invalid_status(self):
        self.change('docs/development/stages/01-FOUNDATION.md', '| FOUNDATION-001 | P0 | TODO |', '| FOUNDATION-001 | P0 | READY |')
        self.rejected('неверный статус READY')

    def test_missing_dependency(self):
        self.change('docs/development/stages/01-FOUNDATION.md', '| AUDIT-003 |', '| MISSING-001 |')
        self.rejected('отсутствующая зависимость MISSING-001')

    def test_cycle(self):
        self.change('docs/development/stages/01-FOUNDATION.md', '| AUDIT-003 |', '| FOUNDATION-003 |')
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
        source.write_text('# Изменённый источник\n')
        errors, _ = validate(self.root, source)
        self.assertTrue(any('SHA-256 не совпадает' in e for e in errors), errors)


if __name__ == '__main__':
    unittest.main(verbosity=2)
