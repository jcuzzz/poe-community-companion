# Contributing

Thanks for helping out.

## Dev setup

```bash
# POSIX
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cd app
export DJANGO_DEBUG=1
../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py seed_achievements
../.venv/bin/python manage.py runserver
```

```powershell
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
cd app
$env:DJANGO_DEBUG = "1"
..\.venv\Scripts\python manage.py migrate
..\.venv\Scripts\python manage.py seed_achievements
..\.venv\Scripts\python manage.py runserver
```

## Tests

```bash
# POSIX
cd app && DJANGO_DEBUG=1 ../.venv/bin/python manage.py test
```

```powershell
# Windows (PowerShell)
cd app; $env:DJANGO_DEBUG = "1"; ..\.venv\Scripts\python manage.py test
```

Add or update tests with your change; the suite must pass.

## Code style

Match the existing code: no CSS framework, no JS build step, HTMX only as progressive
enhancement. Scoring awards are derived state; never edit them by hand.

## Pull requests

- Keep PRs focused; open an issue first for large changes.
- Describe what changed, why, and how you tested it.
- Update docs (`docs/FEATURES.md`, `.env.example`) when behaviour or config changes.
- Do not commit secrets, `.env`, databases, or uploaded media.
- Do not add Grinding Gear Games artwork to the repo; hotlink from GGG's CDN instead.
