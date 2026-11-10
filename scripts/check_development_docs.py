#!/usr/bin/env python3
"""Проверка дорожной карты без зависимостей и без автоматического изменения статусов."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

STATUSES = {'TODO', 'IN_PROGRESS', 'PARTIAL', 'BLOCKED', 'DONE', 'UNKNOWN'}
PRIORITIES = {'P0', 'P1', 'P2', 'P3', 'P4'}
TASK_ID = re.compile(r'^[A-Z][A-Z0-9]*-\d{3}(?:-\d+)?$')
LINK = re.compile(r'(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)|!\[[^\]\n]*\]\(([^)\n]+)\)')


def field(text: str, name: str) -> str:
    match = re.search(r'^\*\*' + re.escape(name) + r':\*\*\s*(.+)$', text, re.M)
    return match.group(1).strip() if match else ''


def table_rows(text: str):
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith('|') and line.endswith('|'):
            yield number, [c.strip() for c in line[1:-1].split('|')]


def task_table_rows(text: str):
    """Читать именно каноническую таблицу, включая ошибочные ID её строк."""
    in_table = False
    for number, line in enumerate(text.splitlines(), 1):
        if not line.startswith('|') or not line.endswith('|'):
            in_table = False
            continue
        cells = [c.strip() for c in line[1:-1].split('|')]
        if cells[:3] == ['ID', 'Приоритет', 'Статус']:
            in_table = True
            continue
        if in_table and not all(re.fullmatch(r':?-+:?', c) for c in cells):
            yield number, cells
        elif not in_table and TASK_ID.fullmatch(cells[0]) and len(cells) == 7:
            # Отдельно дописанная строка не должна скрывать дубль определения задачи.
            yield number, cells


def expected_stage_status(values: list[str]) -> str:
    states = set(values)
    if states == {'DONE'}:
        return 'DONE'
    if states == {'UNKNOWN'}:
        return 'UNKNOWN'
    if states <= {'TODO', 'BLOCKED'}:
        return 'TODO' if 'TODO' in states else 'BLOCKED'
    if 'IN_PROGRESS' in states:
        return 'IN_PROGRESS'
    return 'PARTIAL'


def anchors(text: str) -> set[str]:
    result = set(re.findall(r'<a\s+id=[\"\']([^\"\']+)[\"\']', text))
    counts: collections.Counter = collections.Counter()
    # Повторяющиеся Markdown-заголовки получают суффиксы как на GitHub.
    for title in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', text, re.M):
        title = re.sub(r'\[([^]]+)\]\([^)]+\)', r'\1', title)
        slug = re.sub(r'[^\w\- ]', '', title.lower(), flags=re.UNICODE).replace(' ', '-')
        result.add(slug if not counts[slug] else f'{slug}-{counts[slug]}')
        counts[slug] += 1
    return result


def validate(root: Path, source: Path | None = None) -> tuple[list[str], dict]:
    errors: list[str] = []
    dev = root / 'docs/development'
    tasks: dict[str, dict] = {}
    stages: dict[str, dict] = {}
    docs = list(dev.rglob('*.md')) + [root / 'README.md', root / 'AGENTS.md']
    required = ['README.md', 'ROADMAP.md', 'PROJECT_STATE.md', 'DECISIONS_INDEX.md',
                'ARCHITECTURE.md', 'DEPENDENCIES.md', 'RISKS.md', 'CHANGELOG.md',
                'SOURCE_MANIFEST.json', 'tasks/README.md', 'handoffs/INITIAL-AUDIT.md']
    for name in required:
        if not (dev / name).is_file():
            errors.append(f'Нет обязательного документа: {name}')
    for path in docs:
        if not path.is_file():
            errors.append(f'Нет файла: {path}')
            continue
        content = path.read_text(encoding='utf-8')
        for value, count in collections.Counter(re.findall(r'<a\s+id="([^"]+)"', content)).items():
            if count > 1:
                errors.append(f'{path.name}: повтор HTML-якоря {value}')
        for match in LINK.finditer(content):
            target = (match.group(1) or match.group(2)).strip().strip('<>')
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc:
                continue  # Сеть намеренно не нужна; источник проверяется отдельно по снимку.
            dest = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path.resolve()
            if not dest.is_relative_to(root.resolve()):
                errors.append(f'{path.relative_to(root)}: ссылка выходит за репозиторий: {target}')
            elif not dest.exists():
                errors.append(f'{path.relative_to(root)}: нет цели ссылки: {target}')
            elif parsed.fragment and dest.suffix == '.md':
                if unquote(parsed.fragment) not in anchors(dest.read_text(encoding='utf-8')):
                    errors.append(f'{path.relative_to(root)}: нет якоря: {target}')

    for path in sorted((dev / 'stages').glob('*.md')):
        content = path.read_text(encoding='utf-8')
        sid, status = field(content, 'ID'), field(content, 'Статус')
        if not re.fullmatch(r'STAGE-\d{2}', sid):
            errors.append(f'{path.name}: неверный ID этапа {sid!r}')
        if sid in stages:
            errors.append(f'Повтор ID этапа: {sid}')
        if sid != 'STAGE-' + path.name[:2]:
            errors.append(f'{path.name}: ID этапа не совпадает с именем файла')
        stage_priority = field(content, 'Приоритет')
        if stage_priority not in PRIORITIES:
            errors.append(f'{sid}: неверный приоритет этапа {stage_priority}')
        if status not in STATUSES:
            errors.append(f'{sid}: неверный статус {status}')
        local = []
        for line, cells in task_table_rows(content):
            if not TASK_ID.fullmatch(cells[0]):
                errors.append(f'{path.name}:{line}: неверный ID задачи {cells[0]!r}')
                continue
            if len(cells) != 7:
                errors.append(f'{path.name}:{line}: ожидается 7 столбцов')
                continue
            ident, priority, state, dep, title, acceptance, check = cells
            if ident in tasks:
                errors.append(f'Повтор ID задачи: {ident}')
                continue
            if state not in STATUSES:
                errors.append(f'{ident}: неверный статус {state}')
            if priority not in PRIORITIES:
                errors.append(f'{ident}: неверный приоритет {priority}')
            deps = [] if dep == '—' else [d.strip() for d in dep.split(',')]
            if not all(TASK_ID.fullmatch(d) for d in deps):
                errors.append(f'{ident}: неверный формат зависимостей {dep}')
            if len(deps) != len(set(deps)):
                errors.append(f'{ident}: повтор зависимости')
            if not title or not acceptance or not check:
                errors.append(f'{ident}: отсутствуют результат, приёмка или проверка')
            tasks[ident] = dict(stage=sid, status=state, priority=priority, deps=deps)
            local.append(state)
        if not local:
            errors.append(f'{sid}: нет проверяемых задач')
        elif status != expected_stage_status(local):
            errors.append(f'{sid}: статус {status} не соответствует задачам ({expected_stage_status(local)})')
        progress = re.search(r'^\*\*Прогресс:\*\*\s*(\d+)/(\d+)', content, re.M)
        if not progress or tuple(map(int, progress.groups())) != (local.count('DONE'), len(local)):
            errors.append(f'{sid}: неверный счёт DONE/всего')
        stages[sid] = dict(status=status, priority=stage_priority, path=path, done=local.count('DONE'), total=len(local))

    # Проверяем граф на уровне задач: этапы могут обмениваться результатами подзадач.
    for ident, task in tasks.items():
        for dep in task['deps']:
            if dep not in tasks:
                errors.append(f'{ident}: отсутствующая зависимость {dep}')
            elif task['status'] in {'DONE', 'IN_PROGRESS'} and tasks[dep]['status'] != 'DONE':
                errors.append(f'{ident}: {task["status"]} при незавершённой зависимости {dep}')
    visited: set[str] = set()
    active: list[str] = []

    def visit(ident: str):
        if ident in active:
            errors.append('Цикл задач: ' + ' → '.join(active[active.index(ident):] + [ident]))
            return
        if ident in visited or ident not in tasks:
            return
        active.append(ident)
        for dep in tasks[ident]['deps']:
            visit(dep)
        active.pop()
        visited.add(ident)

    for ident in tasks:
        visit(ident)
    for path in (dev / 'tasks').glob('*.md'):
        if path.name == 'README.md':
            continue
        content = path.read_text(encoding='utf-8')
        ident = field(content, 'ID')
        if ident != path.stem or ident not in tasks:
            errors.append(f'{path.name}: имя/ID не найдено в каноническом реестре')
            continue
        for key, label in [('status', 'Статус'), ('priority', 'Приоритет')]:
            if field(content, label) != tasks[ident][key]:
                errors.append(f'{ident}: TASK/{label} не совпадает с этапом')
        deps = [d.strip() for d in field(content, 'Зависимости').split(',') if d.strip() and d.strip() != '—']
        if set(deps) != set(tasks[ident]['deps']):
            errors.append(f'{ident}: зависимости TASK не совпадают с этапом')
        if len(deps) != len(set(deps)):
            errors.append(f'{ident}: повтор зависимости в TASK')
        stage_link = re.search(r'\]\(([^)]+)\)', field(content, 'Этап'))
        if not stage_link or (path.parent / stage_link.group(1)).resolve() != stages[tasks[ident]['stage']]['path'].resolve():
            errors.append(f'{ident}: ссылка TASK на другой этап')
        if not field(content, 'Владелец') or not field(content, 'Ветка'):
            errors.append(f'{ident}: нет владельца/ветки')
        if tasks[ident]['status'] == 'IN_PROGRESS' and field(content, 'Владелец') == 'не назначен':
            errors.append(f'{ident}: IN_PROGRESS без исполнителя')

    roadmap = (dev / 'ROADMAP.md').read_text(encoding='utf-8') if (dev / 'ROADMAP.md').exists() else ''
    seen_stages = set()
    for _, cells in table_rows(roadmap):
        if not re.fullmatch(r'\d{2}', cells[0]):
            continue
        sid = 'STAGE-' + cells[0]
        if sid in seen_stages:
            errors.append(f'Повтор этапа в ROADMAP: {sid}')
        seen_stages.add(sid)
        if sid not in stages or len(cells) != 8:
            errors.append(f'Неверная строка этапа в ROADMAP: {sid}')
            continue
        if cells[3] != stages[sid]['status']:
            errors.append(f'{sid}: статус ROADMAP не совпадает с этапом')
        if cells[2] != stages[sid]['priority']:
            errors.append(f'{sid}: приоритет ROADMAP не совпадает с этапом')
        if cells[4] != f'{stages[sid]["done"]}/{stages[sid]["total"]}':
            errors.append(f'{sid}: счёт ROADMAP не совпадает с этапом')
    if seen_stages != set(stages):
        errors.append('Список этапов ROADMAP не совпадает со stages/')

    manifest_path = dev / 'SOURCE_MANIFEST.json'
    index_path = dev / 'DECISIONS_INDEX.md'
    manifest = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except (ValueError, OSError) as exc:
            errors.append(f'Нельзя прочитать манифест: {exc}')
    if not isinstance(manifest, dict):
        errors.append('Манифест должен быть объектом')
        manifest = {}
    entries = manifest.get('entries', [])
    if not isinstance(entries, list) or not entries or not all(isinstance(e, dict) for e in entries):
        errors.append('Манифест: отсутствует непустой список записей источника')
        entries = []
    for key, length in [('commit', 40), ('blob', 40), ('sha256', 64)]:
        if not re.fullmatch(r'[0-9a-f]{' + str(length) + '}', str(manifest.get(key, ''))):
            errors.append(f'Манифест: неверный {key}')
    for entry in entries:
        start, end = entry.get('start'), entry.get('end')
        if not isinstance(start, int) or not isinstance(end, int) or not 1 <= start <= end <= manifest.get('lines', 0):
            errors.append(f'Манифест: неверный диапазон {entry.get("id")}')
        if entry.get('kind') not in {'ТРЕБОВАНИЕ', 'ПРЕДЛОЖЕНИЕ', 'ТЕХПЛАН'}:
            errors.append(f'Манифест: неверная категория {entry.get("id")}')
    if index_path.is_file():
        index = index_path.read_text(encoding='utf-8')
        ids = re.findall(r'<a id="([^"]+)"></a>([^|\n]+)', index)
        anchors_list = [a for a, _ in ids]
        source_ids = [i.strip() for _, i in ids]
        for values, label in [(anchors_list, 'якоря'), (source_ids, 'ID индекса')]:
            for value, count in collections.Counter(values).items():
                if count != 1:
                    errors.append(f'Повтор {label}: {value}')
        wanted = [e['id'] for e in entries]
        if len(wanted) != len(set(wanted)):
            errors.append('Повтор ID в SOURCE_MANIFEST')
        if set(source_ids) != set(wanted):
            errors.append('Покрытие исходных ID в индексе не совпадает с манифестом')
        for number, cells in table_rows(index):
            if not cells or not cells[0].startswith('<a id='):
                continue
            if len(cells) != 6 or not cells[1]:
                errors.append(f'Индекс:{number}: пустое описание или неверное число столбцов')
                continue
            if cells[-1] not in STATUSES:
                errors.append(f'Индекс:{number}: неверный статус {cells[-1]}')
            ident = cells[0].split('</a>', 1)[-1].strip()
            entry = next((e for e in entries if e['id'] == ident), None)
            if entry:
                pinned = f'https://github.com/{manifest["repository"]}/blob/{manifest["commit"]}/{manifest["path"]}'
                expected = f'{pinned}#L{entry["start"]}-L{entry["end"]}'
                if f']({expected})' not in cells[2]:
                    errors.append(f'Индекс:{number}: ссылка не соответствует диапазону/commit источника')
            for task_id, target in re.findall(r'\[([^]]+)\]\(([^)]+)\)', cells[4]):
                if task_id not in tasks:
                    errors.append(f'Индекс:{number}: неизвестная связанная задача {task_id}')
                elif (dev / target).resolve() != stages[tasks[task_id]['stage']]['path'].resolve():
                    errors.append(f'Индекс:{number}: задача {task_id} ссылается на чужой этап')
    task_index_path = dev / 'tasks/README.md'
    if task_index_path.is_file():
        for _, cells in table_rows(task_index_path.read_text(encoding='utf-8')):
            link = re.fullmatch(r'\[([^]]+)\]\(([^)]+)\)', cells[0])
            if not link:
                continue
            ident = link.group(1)
            if ident not in tasks or len(cells) != 5:
                errors.append(f'Список TASK: неизвестный пакет {ident}')
            elif cells[1] != tasks[ident]['status']:
                errors.append(f'{ident}: статус в списке TASK не совпадает с этапом')
    review_path = dev / 'handoffs/FULL-REVIEW.md'
    if review_path.is_file():
        review = review_path.read_text(encoding='utf-8')
        if field(review, 'SHA-256 источника') != manifest.get('sha256'):
            errors.append('Полная вычитка: SHA-256 не совпадает с манифестом')
        if field(review, 'Записей источника') != str(len(entries)):
            errors.append('Полная вычитка: неверное число записей')
        covered_until = 0
        for _, cells in table_rows(review):
            match = re.fullmatch(r'(\d+)–(\d+)', cells[0])
            if not match:
                continue
            start, end = map(int, match.groups())
            if start != covered_until + 1 or end < start:
                errors.append('Полная вычитка: пропуск/перекрытие диапазонов чтения')
            covered_until = end
        if covered_until != manifest.get('lines'):
            errors.append('Полная вычитка: диапазоны не покрывают весь источник')
    if source:
        payload = source.read_bytes()
        if hashlib.sha256(payload).hexdigest() != manifest.get('sha256'):
            errors.append('GAME.md: SHA-256 не совпадает с закреплённым снимком')
        blob = hashlib.sha1(b'blob ' + str(len(payload)).encode() + b'\0' + payload).hexdigest()
        if blob != manifest.get('blob') or len(payload) != manifest.get('bytes'):
            errors.append('GAME.md: blob или размер не совпадает')
        source_lines = payload.decode('utf-8').splitlines()
        if len(source_lines) != manifest.get('lines'):
            errors.append('GAME.md: число строк не совпадает')
        found = set()
        for number, line in enumerate(source_lines, 1):
            match = re.match(r'^#{2,3} (?:Уточнение )?([A-ZА-ЯЁ][A-ZА-ЯЁ0-9]+(?:-[A-ZА-ЯЁ0-9]+)+)', line)
            if line.startswith('## ') and match or line.startswith('### Уточнение CLASS-SHIP-') or re.match(r'^### BATTLEPASS-00[2-5]\.', line):
                if match:
                    found.add(match.group(1))
        wanted = {e['id'] for e in manifest.get('entries', []) if not re.fullmatch(r'L\d{4}', e['id'])}
        if found != wanted:
            errors.append(f'GAME.md: покрытие ID неполное: отсутствуют {sorted(found - wanted)}, лишние {sorted(wanted - found)}')
        for entry in manifest.get('entries', []):
            n = entry['start']
            if n < 1 or n > len(source_lines) or source_lines[n-1].lstrip('# ') != entry['heading']:
                errors.append(f'GAME.md: неверный локатор {entry["id"]}')
    summary = {'этапов': len(stages), 'задач': len(tasks),
               'статусы': dict(collections.Counter(t['status'] for t in tasks.values())),
               'записей_источника': len(manifest.get('entries', [])), 'документов': len(docs)}
    return errors, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1], help='Корень репозитория')
    parser.add_argument('--source', type=Path, help='Локальный неизменённый снимок GAME.md для проверки хеша/ID')
    args = parser.parse_args()
    try:
        errors, summary = validate(args.root.resolve(), args.source)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'ОШИБКА входных данных: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if errors:
        for error in errors:
            print('ОШИБКА: ' + error, file=sys.stderr)
        return 1
    print('OK: ссылки, ID, статусы, зависимости, DAG и зеркала согласованы.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
