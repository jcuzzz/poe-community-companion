# Security policy

Please report vulnerabilities privately through GitHub security advisories:
<https://github.com/jcuzzz/poe-community-companion/security/advisories/new>

Do not open a public issue for security problems. Include steps to reproduce and the
affected version or commit.

Known, accepted trade-off: proof images under `/media/` are served without a login
check (unguessable random filenames). See `SERVE_MEDIA` in `.env.example`.
