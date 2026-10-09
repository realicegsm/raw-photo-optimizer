# raw-photo-optimizer

Проект разработки и релизного skill для пакетной проявки RAW-снимков Sony A6100 через RawTherapee.

## Структура проекта

```text
raw-photo-optimizer/
├── README.md
├── SKILL.md
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci.yml
├── docs/
│   ├── calibration.md
│   ├── architecture.md
│   └── troubleshooting.md
├── scripts/
│   ├── analyze_raw.py
│   ├── optimize_profile.py
│   ├── pdr_curve.py
│   └── process_raw.py
├── templates/
│   ├── OpenClaw_a6100_Adobe.pp3
│   ├── Sony ILCE-6100A Adobe Standard.dcp
│   └── ...
├── tests/
│   ├── fixtures/
│   └── test_profile.py
├── examples/
│   ├── sample_raw/
│   └── sample_output/
├── test-output/
│   └── ...
├── release/
│   └── raw-photo-optimizer/
│       ├── SKILL.md
│       ├── scripts/
│       │   ├── analyze_raw.py
│       │   ├── optimize_profile.py
│       │   ├── pdr_curve.py
│       │   └── process_raw.py
│       └── templates/
│           ├── OpenClaw_a6100_Adobe.pp3
│           └── Sony ILCE-6100A Adobe Standard.dcp
└── .DS_Store
```

## Принцип

- Разработка хранится в рабочей структуре проекта.
- Релизный skill хранится в `release/raw-photo-optimizer/` и представляет собой чистую экспортную копию рабочей модели.
- Временные файлы, тестовые выходы и локальные артефакты не попадают в релиз.

## Зоны ответственности

- `scripts/` — рабочая логика разработки
- `templates/` — базовые .pp3 и профили
- `release/raw-photo-optimizer/` — готовый skill bundle для публикации
- `docs/` — методика, архитектура и эксплуатация
- `tests/` — автоматизированная проверка поведения

## Запуск

```bash
python3 scripts/process_raw.py /path/to/raw /path/to/output --keep --log
```

## Важно

Эта структура сохраняет текущий цикл разработки и одновременно поддерживает релизный пакет skill для публикации на GitHub.
