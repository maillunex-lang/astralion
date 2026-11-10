# astralion

## Создание навыков для ИИ-агентов

В `.agents/skills/skill-creator/` установлен официальный **Skill Creator** из
[openai/skills](https://github.com/openai/skills/tree/49f948faa9258a0c61caceaf225e179651397431/skills/.system/skill-creator).
Исходная версия: `49f948faa9258a0c61caceaf225e179651397431`; файлы скопированы без изменений,
лицензия Apache-2.0 сохранена в `LICENSE.txt` внутри навыка.

Откройте этот репозиторий в Codex и начните новую сессию. Пример запроса:

> Используй $skill-creator: создай навык для ИИ-агента, который проверяет документацию проекта. Сохрани его в .agents/skills/.

Навык содержит инструкции, генератор структуры нового навыка, генератор
`agents/openai.yaml` и проверку `SKILL.md`. Формат `SKILL.md` можно использовать
в других агентах, поддерживающих Agent Skills; обнаружение навыков зависит от агента.

Для запуска Python-скриптов нужны Python 3 и PyYAML (`python -m pip install pyyaml`).
Проверить созданный навык:

```sh
python .agents/skills/skill-creator/scripts/quick_validate.py .agents/skills/имя-навыка
```
