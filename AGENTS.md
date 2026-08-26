# AGENTS.md

PySide6 desktop app that generates karaoke/lyric videos from audio + LRC lyrics + album cover via FFmpeg.

## Setup

```
pip install -r requirements.txt
```

Requires **FFmpeg** (ffmpeg + ffprobe) on PATH or set manually in the GUI "Advanced Settings". On Windows, ffprobe must be in the same directory as ffmpeg.

Fonts: place `.ttf` / `.otf` / `.ttc` files in `font/` (gitignored).

## Run

```
python main.py
```

GUI-only app — no CLI mode, no headless mode. Cannot be run in CI or without a display.

## Architecture

Flat single-package structure (no `src/` or `__init__.py`):

| File | Role |
|---|---|
| `main.py` | Entry point — creates `QApplication`, shows `MainWindow` |
| `main_ui.py` | **Central file** — `MainWindow` class with all business logic, event handlers, settings I/O, project save/load |
| `ui_components.py` | Factory functions that build UI group boxes and attach widgets to `MainWindow` via `setattr` / direct attribute assignment |
| `video_processor.py` | Builds and executes FFmpeg commands. Defines `VideoGenParams` dataclass (the single parameter object threaded through the whole pipeline) |
| `animations.py` | FFmpeg filter-string generators for background, text, and cover animations. Defines constants `VIDEO_WIDTH=1920`, `VIDEO_HEIGHT=1080`, `VIDEO_FPS=60` |
| `lrc_parser.py` | LRC parser — returns `(lyrics: list[tuple], metadata: dict)`. Supports bilingual (dual-timestamp + slash-separated) formats |
| `workers.py` | `QThread` subclasses (`AudioInfoWorker`, `VideoWorker`, `PreviewWorker`) that run FFmpeg in background |
| `color_extractor.py` | KMeans-based color extraction from cover image (optional — requires Pillow + scikit-learn) |

## Key patterns

- **`VideoGenParams`** (`video_processor.py`) is the central data object. All generation paths (preview, full video) flow through it. Add new parameters here.
- **Animation registry**: `animations.py` exposes dicts `BACKGROUND_ANIMATIONS`, `TEXT_ANIMATIONS`, `COVER_ANIMATIONS` mapping display-name strings to filter-builder functions. Adding a new animation means adding a function + registering it in the dict.
- **`GENERATIVE_BACKGROUND_ANIMATIONS`** is a subset that don't need an input image (e.g. "gradient wave"). These skip the background image input in the FFmpeg command.
- **UI ↔ logic coupling**: `ui_components.py` creates widgets and attaches them directly as attributes on `MainWindow` (e.g. `main_window.bg_anim_combo`). When adding a new setting, create the widget in `ui_components.py`, reference it in `main_ui.py` `_gather_parameters()` / `save_project()` / `load_project()` / `save_settings()` / `load_settings()`.
- **Project files** (`.kproj`) are JSON with `version`, `file_paths`, and `settings` keys. Version 1.1 adds `background` key to `file_paths`.
- **Settings persistence**: `QSettings("SkyDream", "LRCVideoGenerator")` stores user preferences across sessions. Colors stored as hex strings under keys `color_primary`, `color_secondary`, `outline_color`.
- **Temp files**: written to `Path(tempfile.gettempdir()) / 'lrc2video'`, cleaned on app close.
- **FFmpeg filter_complex** is written to a temp `.txt` file and passed via `-filter_complex_script` (not inline) to avoid shell escaping issues.

## Testing

No tests exist. The `tests/` directory is empty. No test runner is configured.

## Conventions

- Code and UI strings are in **Chinese (Simplified)**. Variable names, function names, and comments are in **English**.
- No type checker, linter, formatter, or pre-commit hooks are configured.
- `.gitignore` excludes: `*.ttf`, `__pycache__/`, `*.mp4`, `*.kproj`
- No CI pipeline exists.

## Gotchas

- `ui_components.py` sets widget attributes on `MainWindow` as a side effect of factory functions. If you add a new widget group, follow the same pattern — the attributes are referenced by name throughout `main_ui.py`.
- `_clean_text()` in `animations.py` escapes `'`, `:`, `%`, `,` for FFmpeg `drawtext`. Any new text animation must use this or FFmpeg will silently fail.
- The vinyl record animation (`get_vinyl_record_animation_filter`) uses 8x supersampling (`ss=8`) for antialiasing — extremely high intermediate resolution (5120x5120). Performance-sensitive changes here have outsized impact.
- Preview mode filters lyrics to a window around the current timestamp (`_get_visible_lyrics`) for performance. Each text animation type has its own windowing strategy.
- Hardware accel codec params are hardcoded in `_process_media()`, not in `animations.py`. Adding a new encoder means editing that function.
- `main_ui.py:closeEvent` cleans up the temp dir with `shutil.rmtree`. Any new temp file creation must account for this.
