# Contributing

Thanks for helping out.

## Dev setup

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv/Scripts/activate
pip install -r requirements.txt
cd app
export DJANGO_DEBUG=1
python manage.py migrate && python manage.py seed_achievements
python manage.py runserver
```

## Tests

```bash
cd app && DJANGO_DEBUG=1 python manage.py test
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
