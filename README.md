# GNIZA - Linux Backup Manager

A complete Linux backup solution that works as a **stand-alone backup tool** or a **centralized backup server**. Pull files from local directories, remote SSH servers, S3 buckets, Google Drive, or Google Photos, and push them to any combination of SSH, local, S3, Google Drive, or Google Photos destinations — all with incremental rsync snapshots, hardlink deduplication, and automatic retention.

Manage everything through a terminal UI, web dashboard, or CLI.

## Features

- **Stand-alone or backup server** — Back up the local machine, or pull from remote servers without installing anything on them
- **Remote sources** — Pull files from SSH servers, S3 buckets, Google Drive, or Google Photos before backing up
- **Multiple destination types** — Push to SSH, local drives (USB/NFS), S3 (AWS, Backblaze B2, Wasabi), Google Drive, or Google Photos
- **Auto remote configuration** — Run a setup script on the remote server and import its config via [croc](https://github.com/schollz/croc) — no manual SSH key or config entry needed
- **Incremental snapshots** — rsync `--link-dest` hardlink deduplication across snapshots
- **MySQL/MariaDB backup** — Dump all or selected databases with grants, routines, and triggers
- **PostgreSQL backup** — Dump all or selected databases with roles via pg_dump + gzip
- **Atomic snapshots** — `.partial` directory during transfer, renamed on success
- **Retention policies** — Automatic pruning per-schedule with global default and snapshot pinning
- **Disk space safety** — Abort if destination usage exceeds threshold (default 95%)
- **Pre/post hooks** — Run shell commands before and after each backup
- **Cron scheduling** — Hourly, daily, weekly, monthly, or custom cron expressions
- **Multi-channel notifications** — Email (SMTP/system mail), Telegram, Webhook (Slack/Discord/generic), ntfy, and Healthchecks.io on failure or every run
- **Stale backup alerts** — Get notified when a source hasn't been backed up within a configurable window
- **Bandwidth limiting** — Global or per-destination KB/s cap
- **Retry logic** — Automatic SSH reconnection with exponential backoff
- **Include/exclude filters** — Rsync glob patterns per source
- **Terminal UI** — Full-featured TUI powered by [Textual](https://textual.textualize.io/)
- **Web dashboard** — Browser-based dashboard with system stats (CPU, Memory, multi-partition Disks, IO Wait, Network), plus full backup management. Source list shows disk usage per source (local, SSH, and rclone)
- **CLI** — Scriptable commands for automation and cron
- **Root and user mode** — System-wide (`/etc/gniza`) or per-user (`~/.config/gniza`)

## Use Cases

**Stand-alone backup** — Install gniza on any Linux server or workstation. Define local folders as sources and back them up to an SSH server, USB drive, S3, Google Drive, or Google Photos.

**Backup server** — Install gniza on a central server. Define remote SSH sources pointing to your production servers. gniza pulls their files and stores snapshots on local drives or cloud storage — no agent needed on the source machines.

**Hybrid** — Mix local and remote sources in the same installation. Back up local configs alongside files pulled from multiple remote servers, all managed from one place.

## Installation

### One-liner (root)

```bash
curl -sSL https://git.linux-hosting.co.il/shukivaknin/gniza4linux/raw/branch/main/scripts/install.sh | sudo bash
```

### One-liner (user mode)

```bash
curl -sSL https://git.linux-hosting.co.il/shukivaknin/gniza4linux/raw/branch/main/scripts/install.sh | bash
```

### From source

```bash
git clone https://git.linux-hosting.co.il/shukivaknin/gniza4linux.git
cd gniza4linux
sudo bash scripts/install.sh    # root mode
# or
bash scripts/install.sh          # user mode
```

Root mode installs to `/usr/local/gniza`. User mode installs to `~/.local/share/gniza`.

The installer detects dependencies, sets up config directories, and optionally launches a setup wizard.

### Uninstall

```bash
gniza uninstall
```

### Dependencies

- **Required**: bash 4+, rsync
- **Optional**: ssh, curl (SMTP/Telegram/Webhook/ntfy/Healthchecks notifications), sshpass (password auth), rclone (S3/Google Drive/Google Photos), croc (auto remote configuration)
- **TUI/Web**: python3, textual, textual-serve (installed automatically)

## Quick Start

```bash
# Launch the TUI
gniza

# Start the web dashboard
gniza web install-service
gniza web start
# Access at http://<server-ip>:2323

# Or use the CLI to add a source and destination
gniza --cli sources add --name=mysite --folders=/var/www,/etc/nginx
gniza --cli destinations add --name=backup-server

# Run a backup
gniza --cli backup --source=mysite
gniza --cli backup --all
```

## Terminal UI

Launch with `gniza` (no arguments). The TUI provides:

- **Sources** — Create, edit, delete backup sources with folder browser (local, SSH, and rclone) and Test & Save connection validation
- **Destinations** — Configure SSH, local, S3, Google Drive, or Google Photos destinations with Test & Save connection validation
- **Backup** — Run backups with source/destination selection
- **Restore** — Browse snapshots and restore to original location or custom directory
- **Running Tasks** — Monitor active backup/restore jobs with live log output. Jobs show "Skipped" when all targets are disabled
- **Schedules** — Manage cron schedules with time/day pickers and toggle switches
- **Snapshots** — Browse and manage stored snapshots
- **Logs** — View backup history with pagination and status detection (success/error/skipped)
- **Settings** — Configure global options
- **Setup Wizard** — Guided first-run configuration

The TUI adapts to terminal width, with an inline documentation panel on wide screens and a help modal on narrow ones.

## Web Dashboard

A full-featured web dashboard built with Flask, DaisyUI, and HTMX. All three interfaces (TUI, Web, CLI) maintain full feature parity.

```bash
gniza web install-service   # Install systemd service (port 2323)
gniza web start             # Start the service
gniza web status            # Check status
```

Access at `http://<server-ip>:2323`. Credentials are stored in `gniza.conf` as `WEB_USER` and `WEB_API_KEY` (password).

Supports both root (system service) and user (user service) modes.

## Background Daemon

The gniza daemon runs periodic health checks in the background — detecting dead jobs, dispatching queued jobs, and cleaning up old logs and registry entries.

```bash
gniza daemon install-service   # Install systemd service (auto-starts on boot)
gniza daemon start             # Start manually in foreground
gniza daemon status            # Check status
```

Supports both root (system service) and user (user service) modes. Configure the check interval in `gniza.conf`:

```ini
DAEMON_INTERVAL=10             # Health check interval in seconds (default: 10)
```

## How Incremental Backups Work

gniza uses rsync's `--link-dest` option to create space-efficient incremental backups using **hardlinks**.

**The first backup** copies every file from source to destination. This takes the most time and disk space. Depending on data size and network speed, the initial backup may take a long time — this is normal.

**Every subsequent backup** is significantly faster. Rsync compares each file against the previous snapshot. Unchanged files are not transferred — instead, rsync creates a **hardlink** to the same data block from the previous snapshot. Only new or modified files are copied.

This means:

- Each snapshot appears as a **complete directory tree** — browse or restore any snapshot independently
- Unchanged files share disk space through hardlinks, so 10 snapshots of 50 GB with minor changes might use 55 GB total instead of 500 GB
- Deleting an old snapshot only frees space for files not referenced by other snapshots
- Subsequent backups typically finish in seconds or minutes rather than hours

> **Example**: A first backup of 20 GB takes 45 minutes over SSH. The next day, only 200 MB changed — the second backup takes under 2 minutes and uses only 200 MB of additional disk space, while still appearing as a complete 20 GB snapshot.

## Remote Sources

gniza can pull files from remote machines **without installing anything on them**. This turns gniza into a centralized backup server.

### SSH Source

Back up a remote server by pulling files over SSH:

1. Create a source with `TARGET_SOURCE_TYPE="ssh"`
2. Set the SSH connection details (`TARGET_SOURCE_HOST`, etc.)
3. Set `TARGET_FOLDERS` to the remote paths you want to back up (e.g. `/var/www,/etc`)

gniza connects to the remote server, pulls the specified folders to a local staging area, then pushes the data to the configured destination using the standard snapshot pipeline.

### S3 / Google Drive / Google Photos Source

Pull files from cloud storage before backing them up:

- **S3**: Set `TARGET_SOURCE_TYPE="s3"` with bucket, region, and credentials
- **Google Drive**: Set `TARGET_SOURCE_TYPE="gdrive"` with a service account JSON file
- **Google Photos**: Set `TARGET_SOURCE_TYPE="gphotos"` with OAuth credentials

Requires `rclone` to be installed. Google OAuth (Drive and Photos) requires your own Client ID and Client Secret, as rclone's built-in defaults are blocked by Google.

## Snapshot Structure

```
<base>/<hostname>/sources/<name>/snapshots/<YYYY-MM-DDTHHMMSS>/
+-- meta.json           # Metadata (source, timestamp, duration, pinned)
+-- manifest.txt        # File listing
+-- var/www/            # Backed-up directories
+-- etc/nginx/
+-- _mysql/             # MySQL dumps (if enabled)
    +-- dbname.sql.gz
    +-- _grants.sql.gz
+-- _postgresql/        # PostgreSQL dumps (if enabled)
    +-- dbname.sql.gz
    +-- _roles.sql.gz
```

During transfer, snapshots are stored in a `.partial` directory. On success, the directory is renamed to the final timestamp. Interrupted backups leave no incomplete snapshots.

## CLI Reference

```
gniza [OPTIONS] [COMMAND]

Options:
  --cli             Force CLI mode (no TUI)
  --debug           Enable debug logging
  --config=FILE     Override config file path
  --help            Show help
  --version         Show version

Sources:
  sources list                          List all configured sources
  sources add --name=NAME --folders=PATHS
  sources delete --name=NAME
  sources show --name=NAME

Destinations:
  destinations list                          List all configured destinations
  destinations add --name=NAME
  destinations delete --name=NAME
  destinations show --name=NAME
  destinations test --name=NAME              Validate connectivity
  destinations disk-info-short --name=NAME   Show disk usage
  destinations auto-configure --name=NAME --code=CODE
                                             Auto-configure from remote setup script

Operations:
  backup [--source=NAME] [--destination=NAME] [--all]
  restore --source=NAME --snapshot=TS [--destination=NAME] [--dest=DIR] [--skip-mysql] [--skip-postgresql]
  retention [--source=NAME] [--destination=NAME] [--all]

Snapshots:
  snapshots list [--source=NAME] [--destination=NAME]
  snapshots browse --source=NAME --snapshot=TS [--destination=NAME]

Scheduling:
  schedule install | show | remove

Notifications:
  test-notification <channel>       Test a notification channel (email, telegram, webhook, ntfy, healthcheck)
  test-email                        Alias for test-notification email

Other:
  logs [--last] [--tail=N]
  web start | install-service | remove-service | status [--port=PORT]
  daemon start | install-service | remove-service | status
  uninstall
```

## Configuration

| Mode | Config | Logs | Lock |
|------|--------|------|------|
| Root | `/etc/gniza/` | `/var/log/gniza/` | `/var/run/gniza.lock` |
| User | `~/.config/gniza/` | `~/.local/state/gniza/log/` | `$XDG_RUNTIME_DIR/gniza-$UID.lock` |

Config subdirectories: `targets.d/*.conf` (sources), `remotes.d/*.conf` (destinations), `schedules.d/*.conf`

### Global Settings (`gniza.conf`)

```ini
BWLIMIT=0                      # Bandwidth limit in KB/s (0 = unlimited)
RETENTION_COUNT=30              # Default snapshots to keep
LOG_LEVEL="info"                # info or debug
LOG_RETAIN=90                   # Days to keep log files
DISK_USAGE_THRESHOLD=95         # Abort if destination >= this % (0 = disabled)
MAX_CONCURRENT_JOBS=1           # Max simultaneous jobs (0 = unlimited)
DAEMON_INTERVAL=10              # Health daemon check interval in seconds
SSH_TIMEOUT=30                  # SSH connection timeout in seconds
SSH_RETRIES=3                   # Number of retry attempts
RSYNC_COMPRESS="no"             # Compression: no, zlib, zstd
RSYNC_CHECKSUM="no"             # Detect changes by content (--checksum)
RSYNC_EXTRA_OPTS=""             # Additional rsync flags
WORK_DIR="/tmp"                 # Temp directory for staging

# Notifications
NOTIFY_ON="failure"             # never | failure | always
NOTIFY_EMAIL=""                 # Comma-separated recipients
SMTP_HOST=""
SMTP_PORT=587
SMTP_USER=""
SMTP_PASSWORD=""
SMTP_FROM=""
SMTP_SECURITY="tls"            # tls | ssl | none

# Telegram
TELEGRAM_BOT_TOKEN=""
TELEGRAM_CHAT_ID=""

# Webhook (Slack, Discord, or generic)
WEBHOOK_URL=""
WEBHOOK_TYPE=""                 # slack | discord | generic

# ntfy
NTFY_URL=""
NTFY_TOKEN=""
NTFY_PRIORITY=""

# Healthchecks.io
HEALTHCHECKS_URL=""

# Stale backup alerts
STALE_ALERT_HOURS=""            # Alert when a source hasn't backed up in X hours

# Web dashboard
WEB_USER="admin"
WEB_API_KEY=""                  # Generated during install
```

### Source Config (`targets.d/mysite.conf`)

A **source** defines what to back up: a set of folders, optional filters, hooks, and MySQL settings.

```ini
TARGET_NAME="mysite"
TARGET_FOLDERS="/var/www,/etc/nginx"
TARGET_EXCLUDE="*.log,*.tmp,.cache"
TARGET_INCLUDE=""
TARGET_REMOTE=""                # Pin to a specific destination
TARGET_PRE_HOOK=""              # Shell command before backup
TARGET_POST_HOOK=""             # Shell command after backup
TARGET_ENABLED="yes"

# Remote source (pull from another machine)
TARGET_SOURCE_TYPE="local"      # local | ssh | s3 | gdrive | gphotos

# SSH source
TARGET_SOURCE_HOST=""
TARGET_SOURCE_PORT="22"
TARGET_SOURCE_USER="root"
TARGET_SOURCE_AUTH_METHOD="key" # key | password
TARGET_SOURCE_KEY=""
TARGET_SOURCE_PASSWORD=""
TARGET_SOURCE_SUDO="no"             # Use sudo rsync on source (yes | no)

# S3 source
TARGET_SOURCE_S3_PROVIDER="AWS"  # AWS | Backblaze | Wasabi | Other
TARGET_SOURCE_S3_BUCKET=""
TARGET_SOURCE_S3_REGION="us-east-1"
TARGET_SOURCE_S3_ENDPOINT=""
TARGET_SOURCE_S3_ACCESS_KEY_ID=""
TARGET_SOURCE_S3_SECRET_ACCESS_KEY=""

# Google Drive source
TARGET_SOURCE_GDRIVE_SERVICE_ACCOUNT_FILE=""
TARGET_SOURCE_GDRIVE_ROOT_FOLDER_ID=""

# MySQL backup
TARGET_MYSQL_ENABLED="no"
TARGET_MYSQL_MODE="all"         # all | selected
TARGET_MYSQL_DATABASES=""       # Comma-separated (when mode=selected)
TARGET_MYSQL_EXCLUDE=""         # Databases to skip
TARGET_MYSQL_USER=""
TARGET_MYSQL_PASSWORD=""
TARGET_MYSQL_HOST="localhost"
TARGET_MYSQL_PORT="3306"
TARGET_MYSQL_EXTRA_OPTS="--single-transaction --routines --triggers"

# PostgreSQL backup (local and SSH sources only)
TARGET_POSTGRESQL_ENABLED="no"
TARGET_POSTGRESQL_MODE="all"    # all | specific
TARGET_POSTGRESQL_DATABASES=""  # Comma-separated (when mode=specific)
TARGET_POSTGRESQL_EXCLUDE=""    # Databases to skip
TARGET_POSTGRESQL_USER=""       # Leave empty for peer auth
TARGET_POSTGRESQL_PASSWORD=""   # Leave empty for peer auth
TARGET_POSTGRESQL_HOST="localhost"
TARGET_POSTGRESQL_PORT="5432"
TARGET_POSTGRESQL_EXTRA_OPTS="--no-owner --no-privileges"
```

**Include vs Exclude**: Set `TARGET_INCLUDE` to back up only matching files (e.g. `*.conf,*.sh`). When include is set, everything else is excluded. If only `TARGET_EXCLUDE` is set, matching files are skipped. Patterns use rsync glob syntax.

### Destination Config (`remotes.d/backup-server.conf`)

A **destination** defines where snapshots are stored.

```ini
REMOTE_TYPE="ssh"               # ssh | local | s3 | gdrive
REMOTE_HOST="backup.example.com"
REMOTE_PORT=22
REMOTE_USER="root"
REMOTE_AUTH_METHOD="key"        # key | password
REMOTE_KEY="/root/.ssh/backup_key"  # Defaults to ~/.ssh/id_rsa
REMOTE_PASSWORD=""
REMOTE_SUDO="no"                    # Use sudo rsync on destination (yes | no)
REMOTE_BASE="/backups"
BWLIMIT=0                      # Override global bandwidth limit
```

**Local destination** (USB drive, NFS mount):

```ini
REMOTE_TYPE="local"
REMOTE_BASE="/mnt/backup-drive"
```

**S3 destination** (AWS, Backblaze B2, Wasabi, or any S3-compatible):

```ini
REMOTE_TYPE="s3"
S3_PROVIDER="AWS"               # AWS | Backblaze | Wasabi | Other
S3_BUCKET="my-backups"
S3_ACCESS_KEY_ID="AKIA..."
S3_SECRET_ACCESS_KEY="..."
S3_REGION="us-east-1"
S3_ENDPOINT=""                  # Auto-set for Backblaze/Wasabi, manual for Other
```

**Backblaze B2 example**:

```ini
REMOTE_TYPE="s3"
S3_PROVIDER="Backblaze"
S3_BUCKET="my-b2-bucket"
S3_ACCESS_KEY_ID="your-key-id"
S3_SECRET_ACCESS_KEY="your-app-key"
S3_REGION="us-west-004"
S3_ENDPOINT="https://s3.us-west-004.backblazeb2.com"
```

**Wasabi example**:

```ini
REMOTE_TYPE="s3"
S3_PROVIDER="Wasabi"
S3_BUCKET="my-wasabi-bucket"
S3_ACCESS_KEY_ID="your-key"
S3_SECRET_ACCESS_KEY="your-secret"
S3_REGION="us-east-1"
S3_ENDPOINT="https://s3.wasabisys.com"
```

**Google Drive destination**:

```ini
REMOTE_TYPE="gdrive"
GDRIVE_SERVICE_ACCOUNT_FILE="/path/to/service-account.json"
GDRIVE_ROOT_FOLDER_ID=""       # Optional folder ID
```

### Schedule Config (`schedules.d/nightly.conf`)

```ini
SCHEDULE="daily"                # hourly | daily | weekly | monthly | custom
SCHEDULE_TIME="02:00"           # HH:MM
SCHEDULE_DAY=""                 # Day of week (0-6) or day of month (1-28)
SCHEDULE_CRON=""                # Full cron expression (when SCHEDULE=custom)
SCHEDULE_ACTIVE="yes"
TARGETS=""                      # Comma-separated source names (empty = all)
REMOTES=""                      # Comma-separated destination names (empty = all)
RETENTION_COUNT=""              # Override global retention (empty = use global default)
```

## Retention

Retention policies control how many snapshots to keep per source per destination.

- **Global default**: `RETENTION_COUNT` in `gniza.conf` (default: 30)
- **Per-schedule override**: `RETENTION_COUNT` in the schedule config
- **Snapshot pinning**: Pin individual snapshots in `meta.json` to preserve them indefinitely

Retention runs automatically after each successful backup. Run it manually with:

```bash
gniza --cli retention --all
```

## MySQL Backup

gniza can dump MySQL/MariaDB databases alongside file backups.

- **All databases**: Set `TARGET_MYSQL_MODE="all"` to dump every user database
- **Selected databases**: Set `TARGET_MYSQL_MODE="selected"` and list them in `TARGET_MYSQL_DATABASES`
- **Exclude databases**: Use `TARGET_MYSQL_EXCLUDE` to skip specific databases
- **Grants**: User grants are automatically dumped to `_grants.sql.gz`
- **Compression**: All dumps are gzip-compressed
- **Restore**: MySQL dumps are automatically restored unless `--skip-mysql` is passed

Auto-detects `mysqldump` or `mariadb-dump`.

## PostgreSQL Backup

gniza can dump PostgreSQL databases alongside file backups. Available for local and SSH sources only (not S3/Google Drive/Google Photos).

- **All databases**: Set `TARGET_POSTGRESQL_MODE="all"` to dump every user database
- **Specific databases**: Set `TARGET_POSTGRESQL_MODE="specific"` and list them in `TARGET_POSTGRESQL_DATABASES`
- **Exclude databases**: Use `TARGET_POSTGRESQL_EXCLUDE` to skip specific databases
- **Roles**: Roles are automatically dumped via `pg_dumpall --roles-only` to `_roles.sql.gz`
- **Compression**: All dumps are gzip-compressed (pg_dump plain format + gzip)
- **Restore**: PostgreSQL dumps are automatically restored unless `--skip-postgresql` is passed
- **Authentication**: Leave `TARGET_POSTGRESQL_USER` and `TARGET_POSTGRESQL_PASSWORD` empty for peer auth

Dumps are stored in the `_postgresql/` subdirectory within each snapshot.

## Scheduling

gniza manages cron entries for automated backups.

```bash
gniza --cli schedule install     # Install all schedules to crontab
gniza --cli schedule show        # Show current cron entries
gniza --cli schedule remove      # Remove gniza cron entries
```

Cron entries are tagged for clean install/removal. Each schedule can be scoped to specific sources and destinations. Last run time is tracked per schedule and only updated on successful completion.

## Notifications

Multi-channel notifications on backup success or failure.

**Email (SMTP)**: Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, and `SMTP_SECURITY` in `gniza.conf`. Supports TLS, SSL, and plaintext. Falls back to system `mail` or `sendmail` if SMTP is not configured.

**Telegram**: Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to receive notifications via Telegram bot.

**Webhook**: Set `WEBHOOK_URL` and `WEBHOOK_TYPE` (`slack`, `discord`, or `generic`) to post notifications to Slack, Discord, or any webhook endpoint.

**ntfy**: Set `NTFY_URL` (and optionally `NTFY_TOKEN` and `NTFY_PRIORITY`) to push notifications via [ntfy](https://ntfy.sh/).

**Healthchecks.io**: Set `HEALTHCHECKS_URL` to ping a [Healthchecks.io](https://healthchecks.io/) check on backup success/failure.

**Stale backup alerts**: Set `STALE_ALERT_HOURS` to get notified when a source hasn't been backed up within the specified number of hours.

**Report includes**: Status, source count (total/succeeded/failed), duration, failed source list, log file path, hostname, and timestamp.

**Notification log**: All notifications are logged to `notification.log` (replaces the old `email.log`). The notification log viewer also reads historical entries from `email.log`.

## Disk Space Safety

gniza checks destination disk usage before and during backups. If usage reaches the configured threshold (default 95%), the backup aborts to prevent filling the disk.

```ini
DISK_USAGE_THRESHOLD=95    # Set to 0 to disable
```

Works with SSH and local destinations.

## Pre/Post Hooks

Run shell commands before and after each backup:

```ini
TARGET_PRE_HOOK="systemctl stop myapp"
TARGET_POST_HOOK="systemctl start myapp"
```

- **Pre-hook failure** aborts the backup
- **Post-hook failure** is logged as a warning

## License

MIT License - see [LICENSE](LICENSE) for details.
