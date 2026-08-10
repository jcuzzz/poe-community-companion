# Deploying Squad-Achieves

The app runs on the CT100 Proxmox LXC (`192.0.2.60`) behind Caddy at
https://poe.example.com, as a Docker Compose service in `/opt/poe-tracker`.

## One command

```bash
bash scripts/deploy.sh
```

This pushes local `main`, then on the server pulls, rebuilds the image, restarts,
and health-checks. Idempotent — safe to re-run. The container entrypoint runs
migrations on start, so no separate migrate step is needed.

Commit your work first; the script deploys whatever is on `origin/main`.

## The deploy key (one-time setup per machine)

The script authenticates over SSH with a dedicated deploy key. **The private key
is not in the repo.** It must exist at:

```
~/.ssh/poe_deploy_key        (i.e. C:\Users\<you>\.ssh\poe_deploy_key on Windows)
```

…or point `POE_DEPLOY_KEY` at wherever you keep it:

```bash
POE_DEPLOY_KEY=/path/to/key bash scripts/deploy.sh
```

The matching public key is already installed in `root@192.0.2.60`'s
`authorized_keys`. If the key is lost, generate a new pair and add the public
half to the server's `authorized_keys`.

## Config (env overrides)

| Var | Default | Meaning |
|-----|---------|---------|
| `POE_DEPLOY_KEY` | `~/.ssh/poe_deploy_key` | SSH private key path |
| `POE_DEPLOY_HOST` | `root@192.0.2.60` | SSH target |
| `POE_DEPLOY_APP_DIR` | `/opt/poe-tracker` | app dir on the server |
| `POE_DEPLOY_URL` | `https://poe.example.com/` | health-check URL |

## For AI agents

`bash scripts/deploy.sh` is allowlisted in `.claude/settings.json`, so agents can
run it without a permission prompt. An agent only needs the deploy key present at
`~/.ssh/poe_deploy_key` (or `POE_DEPLOY_KEY` set). Everything else — push, build,
restart, health check — is in the script.

## Manual fallback

```bash
ssh -i ~/.ssh/poe_deploy_key -o IdentitiesOnly=yes root@192.0.2.60 \
  'cd /opt/poe-tracker && git pull --ff-only && docker compose build && docker compose up -d'
```
