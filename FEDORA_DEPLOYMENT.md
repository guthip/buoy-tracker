# Fedora Linux Deployment Notes for Buoy Tracker

The docker-group GID mismatch this guide used to work around (Fedora's
docker group isn't GID 999, which Fedora reserves for `input`) is solved
natively as of v2.1: the container takes `PUID`/`PGID` environment
variables (linuxserver.io convention) and re-numbers its internal user to
match, so no group-membership tricks or custom entrypoints are needed on
any distribution. See **PUID / PGID** in [DOCKER.md](DOCKER.md).

```yaml
services:
  buoy-tracker:
    image: dokwerker8891/buoy-tracker:latest
    environment:
      PUID: "1000"   # your host user's uid (`id -u`)
      PGID: "1000"   # your host user's gid (`id -g`)
```

What's left is genuinely Fedora-specific: SELinux and firewalld.

## SELinux

Fedora runs SELinux in enforcing mode by default, which can block a
container from writing to bind-mounted volumes.

```bash
# Check for denials
sudo ausearch -m avc -ts recent | grep buoy
```

Fix with either:

```bash
# Option A: relabel the host directories once
sudo chcon -R -t container_file_t ~/docker/buoy-tracker/{config,data,logs}

# Option B: let the container relabel on mount (docker-compose.yml)
volumes:
  - ./config:/app/config:z
  - ./data:/app/data:z
  - ./logs:/app/logs:z
```

## Firewalld

Fedora's firewalld is more restrictive than Ubuntu's ufw — open the port
explicitly:

```bash
sudo firewall-cmd --permanent --add-port=5103/tcp
sudo firewall-cmd --reload
sudo firewall-cmd --list-ports | grep 5103
```

## Support

If something doesn't work: check `docker logs buoy-tracker`, confirm
`sestatus`, and open a GitHub issue with your Fedora version
(`cat /etc/fedora-release`) and the container logs.
