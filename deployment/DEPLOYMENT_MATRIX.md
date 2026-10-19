# Deployment matrix

| Target | Django | PostgreSQL | Redis | Celery | Built-in scheduler | Config file | Status |
|---|---|---|---|---|---|---|---|
| Local | yes | optional (SQLite ok) | no | no | optional | `.env` | tested (SQLite) |
| Docker lite | yes | yes | no | no | yes | `docker-compose.lite.yml` | **not runtime-tested** |
| Docker full | yes | yes | yes | worker+beat | no | `docker-compose.yml` | **not runtime-tested** |
| Render free | yes | yes (30-day) | no | no | yes + pinger | `render-free.yaml` | **not runtime-tested** |
| Render full | yes | yes | yes | worker(+beat) | no | `render.yaml` | **not runtime-tested** (paid worker) |
| Railway | yes | yes | optional | optional | yes | `railway.toml`, `Procfile` | **not runtime-tested** |
| VPS | yes | yes | optional | optional | yes | `deployment/systemd/*`, `nginx-vps.conf` | **not runtime-tested** |
| Vercel | no (Django) | external | external | external | n/a | — | only for a future React/Next frontend |
| GitHub Pages | no | no | no | no | n/a | — | documentation only |

"Code support" is not "runtime verification": nothing above marked untested should be called production-ready until run against the real service.
