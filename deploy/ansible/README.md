# Ansible deployment kit (v2.1)

Templates for deploying Buoy Tracker with an ansible role. With the v2.1
layered config, the old approach of templating the entire tracker.config is
gone — you template only the small environment layer; the fleet layer
(`site.config`) is the club's real, current fleet data, checked into this
directory verbatim (nothing in it is secret — the live map already shows
every buoy's position to the world; only `secret.config` holds credentials).
Pull it from GitHub along with the templates instead of waiting for an
emailed copy; when a buoy gets re-moored, the fix ships as a commit here.

## Files

| file | purpose | templated? |
|---|---|---|
| `docker-compose.yml.j2` | service definition (PUID/PGID, Traefik labels) | yes |
| `environment.config.j2` | broker/smtp/ports/logging for YOUR environment | yes |
| `secret.config.j2` | api_key + smtp credentials | yes |
| `site.config` | buoys, homes, alert policy — the real fleet data | no — copy verbatim, redeploy on update |

Suggested role vars (rename freely; keep names consistent — see note below):

```yaml
buoy_role_ui_port:   5103
buoy_role_puid:      "{{ ansible_user_uid | default(1000) }}"
buoy_role_pgid:      "{{ ansible_user_gid | default(1000) }}"
buoy_role_tz:        "{{ homelab_tz }}"
buoy_role_image_tag: "2.2"          # pin; avoid :latest drift
buoy_smtp_host:      "{{ homelab_smtp_fqdn }}"
buoy_smtp_port:      "{{ homelab_smtp_port }}"
buoy_smtp_username:  "{{ homelab_smtp_username }}"
buoy_smtp_password:  "{{ homelab_smtp_password }}"
buoy_email_to:       "{{ homelab_user_admin_email }}"
buoy_api_key:        "{{ vault_buoy_api_key }}"
```

Role tasks: create `config/ data/ logs/` dirs, template the three `.j2` files
into place (`environment.config` and `secret.config` into `config/`), copy
`site.config` from this directory into `config/`, then
`community.docker.docker_compose_v2`.

**Migrating from a pre-2.1 setup:** delete your old full-file
`tracker.config.j2` from the role. If a deployed host still has
`config/tracker.config`, run once:
`docker exec <name> python3 /app/tools/split_config.py /app/config/tracker.config`

**Note on the reference role we reviewed:** its labels referenced
`docker_role_*` vars while the vars file defined `buoy_role_*` (labels never
rendered), `traefick` was misspelled in two var names, and
`buoy_smtp_passowrd` had a typo. The templates here use one consistent
`buoy_role_*` namespace.
