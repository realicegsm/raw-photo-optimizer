# raw-photo-optimizer

Автоматизированный пайплайн для проявки RAW-снимков Sony A6100 (`.ARW`) через RawTherapee CLI с привязкой к реальной чувствительности сенсора и рассчитанными порогами PDR.

Проект сочетает:

- анализ линейных данных сенсора через `rawpy`
- оценку экспозиции и динамического диапазона сцены
- вычисление PDR-потолка сенсора по ISO
- автоматическую генерацию индивидуального профиля `.pp3`
- обработку пакета RAW-файлов с CSV-логом и сохранением профилей по необходимости

## Что умеет проект

- анализировать EXIF: ISO, модель камеры, объектив
- читать статистику сырых данных до тоновых кривых и WB
- рассчитывать `mean_green`, `dynamic_range_ev`, `under_pct`, `over_pct`, `estimated_shift_ev`
- подбирать параметры проявки на основе `headroom_ratio` и `pdr_delta_ev`
- генерировать `.pp3`-профиль для каждого файла
- запускать пакетную обработку через RawTherapee
- сохранять CSV-отчёт по результатам съемки

## Архитектура проекта

```text
raw-photo-optimizer/
├── README.md
├── README.ru.md
├── SKILL.md
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci.yml
├── docs/
│   ├── architecture.md
│   ├── architecture.ru.md
│   ├── calibration.md
│   ├── calibration.ru.md
│   ├── troubleshooting.md
│   └── troubleshooting.ru.md
├── scripts/
│   ├── analyze_raw.py
│   ├── optimize_profile.py
│   ├── pdr_curve.py
│   └── process_raw.py
├── templates/
│   ├── OpenClaw_a6100_Adobe.pp3
│   ├── OpenClaw_Base.pp3
│   ├── OpenClaw_Base_WB.pp3
│   ├── OpenClaw_a6100_ViVid.pp3
│   ├── Sony ILCE-6100A/
│   ├── Sony ILCE-6100A Adobe Standard.dcp
│   ├── TTARTISAN AF 50mm F1.8 Neo.lcp
│   ├── DSC01770.result.pp3
│   ├── DSC02142.result.pp3
│   └── *.backup.pp3
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
│           ├── Sony ILCE-6100A Adobe Standard.dcp
│           └── TTARTISAN AF 50mm F1.8 Neo.lcp
└── .
```

## Принцип работы проекта

Разработка и релиз организованы по одной модели:

- `scripts/` — рабочая разработка
- `release/raw-photo-optimizer/` — чистый релизный bundle для skill-пакета
- `templates/` — базовые профили и вспомогательные данные
- `docs/` — описание методики, логики и эксплуатации

То есть проект сохраняет рабочую среду разработки, но одновременно поддерживает минимальный экспортный пакет для публикации и использования как skill.

## Требования

Перед запуском убедитесь, что установлены:

- Python 3.8+
- `numpy`
- `rawpy`
- `exiftool` в `PATH`
- `rawtherapee-cli`

Установка зависимостей:

```bash
pip install numpy rawpy
```

## Использование

Запуск полной обработки каталога RAW:

```bash
python3 scripts/process_raw.py /path/to/raw /path/to/output
```

С сохранением `.pp3` рядом с файлом и CSV-отчётом:

```bash
python3 scripts/process_raw.py /path/to/raw /path/to/output --keep --log
```

Варианты преобразования в чёрно-белый режим (указывайте только один):

```bash
python3 scripts/process_raw.py /path/to/raw /path/to/output -BW       # микшер каналов
python3 scripts/process_raw.py /path/to/raw /path/to/output --BW_AVG  # усреднённое обесцвечивание
python3 scripts/process_raw.py /path/to/raw /path/to/output --BW_LAB  # через коррекцию цветности Luminance Curve
```

Для отдельного анализа одного файла:

```bash
python3 scripts/analyze_raw.py DSC01900.ARW
```

## Основные модули

- `scripts/analyze_raw.py` — EXIF и анализ линейных данных сенсора
- `scripts/pdr_curve.py` — кривая PDR и интерполяция по ISO
- `scripts/optimize_profile.py` — генерация параметров `.pp3` и запись итоговых значений
- `scripts/process_raw.py` — оркестратор пайплайна, пакетная обработка, логирование

## Логика принятия решений

Pipeline использует не “магические” фиксированные пороги, а измеряемые характеристики сенсора:

- `mean_green` — оценка общей экспозиции
- `dynamic_range_ev` — динамический диапазон сцены
- `headroom_ratio` — отношение DR сцены к потолку сенсора на текущем ISO
- `pdr_delta_ev` — потеря PDR относительно базового ISO

На основе этих метрик выбираются:

- экспокоррекция
- DRC Amount / Anchor / Contrast
- Highlight Recovery
- Shadow Lift
- шумоподавление
- коррекция объектива и CA

## Release bundle

Релизный bundle находится в:

```text
release/raw-photo-optimizer/
├── SKILL.md
├── scripts/
│   ├── analyze_raw.py
│   ├── optimize_profile.py
│   ├── pdr_curve.py
│   └── process_raw.py
└── templates/
    ├── OpenClaw_a6100_Adobe.pp3
    ├── Sony ILCE-6100A Adobe Standard.dcp
    └── TTARTISAN AF 50mm F1.8 Neo.lcp
```

Эта структура предназначена для публикации skill-пакета без локальных мусорных файлов, временных выходов и артефактов разработки.

## Документация

- [README.md](README.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/calibration.md](docs/calibration.md)
- [docs/troubleshooting.md](docs/troubleshooting.md)
- [docs/architecture.ru.md](docs/architecture.ru.md)
- [docs/calibration.ru.md](docs/calibration.ru.md)
- [docs/troubleshooting.ru.md](docs/troubleshooting.ru.md)

## Важно

Проект рассчитан на работу с Sony A6100 и базовыми шаблонами RawTherapee, и предназначен как инструмент для автоматизированной, но контролируемой обработки RAW. Он сохраняет рабочую разработку и одновременно поддерживает экспортный skill-вид для публикации.
