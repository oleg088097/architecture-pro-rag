# База знаний (задание 2)

## Исходная вселенная

Тексты загружены из англоязычной вики [Pokémon Wiki на Fandom](https://pokemon.fandom.com) (в т.ч. статья [Pikachu](https://pokemon.fandom.com/wiki/Pikachu) как точка входа). Используется **MediaWiki API** (`api.php?action=parse&redirects=1`), чтобы обойти HTML-страницу за Cloudflare и получить разобранный вики-текст. При извлечении текста **не включаются** содержимое `<table>…</table>`, блоки `<aside>` (в т.ч. инфобокс с «Information») и дерево `div.portable-infobox` — остаётся основной связный текст статьи. Дополнительно вырезаются оглавление (`div#toc` / `div#fandom-toc`), списки ссылок (`ol.references`, `div.reflist`), сноски `<sup class="reference">`, блоки `[edit]`, а после разбора HTML — остаток блока «Contents», секции Quick Answers, «By series» (список серий), **«Other appearances»** (до следующего крупного заголовка: Quotes, Sprites, Vesperkin и т.д.), затем типичный «хвост» статьи о персонаже: **список команды** (`On hand` / `In rotation` / `Traveling with` → до `Achievements`), **Achievements**, **Voice actors**, **Gallery**, **Trivia** (до следующего крупного заголовка или конца текста); References / Sources / See also; пустые `[]`, `[edit]`, `[n]` и строки цитат `^ …`.

## Выдуманная вселенная

После очистки HTML применяются словари **Aetherium / Vesperkin**: франшизные термины, локации и имена людей — в `terms_map.json`; **все английские виды из национального дексa** (1025 имён) — в `species_map.json` (детерминированные вымышленные имена + фиксированные «геройские» подстановки вроде Zepkiru для Pikachu). Отдельно обрабатываются остаточные `Poké…` (Skyrift Rally, Aether-префикс, отдельное слово «Poké») и вхождения `pokemon` без ударения.

## Логика подмены (порядок в `build_kb.py`)

1. **`terms_map.json`** — подстановка **с учётом регистра**, ключи **по убыванию длины** (фразы вроде «Pokémon Trainer», «Poké-Showdown», затем короткие вроде «Kanto»).
2. **`species_map.json`** — подстановка **без учёта регистра** для имён видов (таблицы, ALL CAPS, смешанный регистр).
3. Остатки **`Poké` + латиница**, **`Poké-`**, отдельное **`Poké`** как слово.
4. Слово **`pokemon`** → `vesperkin` (регистр игнорируется).
5. Одиночное **`Ash`** → `Ralen` (остатки имени тренера).
6. Удаление **URL** (`https?://…`).

Пересборка видов: `python3 generate_species_map.py` (нужен интернет один раз; результат — `species_map.json`). Пересборка корпуса: `python3 build_kb.py`.

## Содержимое папки `knowledge_base/`

- По одному файлу `*.md` на сущность (38 статей).
- `manifest.jsonl` — по строке JSON на документ: идентификатор, исходный заголовок вики, путь к файлу, размер текста.

Словари: **`terms_map.json`** (франшиза, локации, `Poké*`-составные), **`species_map.json`** (виды).
