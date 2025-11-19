# Deployment Checklist

Use this checklist when deploying Buoy Tracker to a new environment.

## What to Send to Deployer

- [ ] **GitHub QUICKSTART link**: https://github.com/guthip/buoy-tracker/blob/main/QUICKSTART.md
- [ ] **tracker.config** - Your configured MQTT broker, special nodes, etc. (actual file)
- [ ] **secret.config** - Your configured email/SMTP credentials (actual file, keep secure)
- [ ] **special_nodes.json** - Historic node position and packet data (if continuing from existing deployment)
- [ ] **special_channels.json** - Historic channel information (if continuing from existing deployment)

Note: Templates (tracker.config.template, secret.config.template) are already in the GitHub repo, so don't need to be distributed.

## Deployment Steps (for Recipient)

1. **Follow QUICKSTART.md**
   ```bash
   git clone https://github.com/guthip/buoy-tracker.git
   cd buoy-tracker
   ```

2. **Set up configuration files** (from files you provided)
   - Place `tracker.config` in repo root (your configured MQTT, special nodes, etc.)
   - Place `secret.config` in repo root if provided (your email credentials)
   - Place `special_nodes.json` and `special_channels.json` in `data/` directory (if provided)

3. **Deploy**
   ```bash
   mkdir -p data logs
   docker compose up -d
   ```

4. **Verify**
   - Access http://localhost:5102
   - Check logs: `docker compose logs -f`

## Post-Deployment

- [ ] Confirm nodes are appearing on the map
- [ ] Verify MQTT connection in logs
- [ ] Test movement alerts (if configured)
- [ ] Test email alerts (if configured) using `/api/test-alert` endpoints
- [ ] Set up log rotation for `logs/` directory
- [ ] Configure regular backups of `data/` directory

## Support Resources

- **Quick Help**: QUICKSTART.md
- **Detailed Docker Guide**: DOCKER.md
- **Full Documentation**: README.md
- **Issue Tracker**: https://github.com/guthip/buoy-tracker/issues

## Questions?

If deployment issues arise:
1. Check logs: `docker compose logs -f`
2. Check MQTT connectivity: `curl http://localhost:5102/api/status`
3. Verify config files are in correct location
4. See DOCKER.md troubleshooting section
