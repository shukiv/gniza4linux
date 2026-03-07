# gniza - Linux Backup Manager

A complete Linux backup solution that works as a **stand-alone backup tool** or a **centralized backup server**. Pull files from local directories, remote SSH servers, S3 buckets, or Google Drive, and push them to any combination of SSH, local, S3, or Google Drive destinations — all with incremental rsync snapshots, hardlink deduplication, and automatic retention.

Manage everything through a terminal UI, web dashboard, or CLI.

```
  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓          ▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓

  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓          ▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓

  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓          ▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
              ▓▓▓▓▓▓▓▓▓▓
                ▓▓▓▓▓▓
                  ▓▓
```

## Features

- **Stand-alone or backup server** — Back up the local machine, or pull from remote servers without installing anything on them
- **Remote sources** — Pull files from SSH servers, S3 buckets, or Google Drive before backing up
- **Multiple destination types** — Push to SSH, local drives (USB/NFS), S3, or Google Drive
- **Incremental snapshots** — rsync `--link-dest` hardlink deduplication across snapshots
- **MySQL/MariaDB backup** — Dump all or selected databases with grants, routines, and triggers
- **Atomic snapshots** — `.partial` directory during transfer, renamed on success
- **Retention policies** — Automatic pruning per-destination or per-source with snapshot pinning
- **Disk space safety** — Abort if destination usage exceeds threshold (default 95%)
- **Pre/post hooks** — Run shell commands before and after each backup
- **Cron scheduling** — Hourly, daily, weekly, monthly, or custom cron expressions
- **Email notifications** — SMTP (TLS/SSL) or system mail on failure or every run
- **Bandwidth limiting** — Global or per-destination KB/s cap
- **Retry logic** — Automatic SSH reconnection with exponential backoff
- **Include/exclude filters** — Rsync glob patterns per source
- **Terminal UI** — Full-featured TUI powered by [Textual](https://textual.textualize.io/)
- **Web dashboard** — Access the TUI from any browser with HTTP Basic Auth
- **CLI** — Scriptable commands for automation and cron
- **Root and user mode** — System-wide (`/etc/gniza`) or per-user (`~/.config/gniza`)

## Use Cases

**Stand-alone backup** — Install gniza on any Linux server or workstation. Define local folders as sources and back them up to an SSH server, USB drive, S3, or Google Drive.

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

### Dependencies

- **Required**: bash 4+, rsync
- **Optional**: ssh, curl (SMTP notifications), sshpass (password auth), rclone (S3/Google Drive)
- **TUI/Web**: python3, textual, textual-serve (installed automatically)

## Quick Start

```bash
# Launch the TUI
gniza

# Or use the CLI
gniza targets add --name=mysite --folders=/var/www,/etc/nginx
gniza remotes add --name=backup-server
gniza --cli backup --target=mysite
gniza --cli backup --all
```

## CLI Reference

```
gniza [OPTIONS] [COMMAND]

Options:
  --cli             Force CLI mode (no TUI)
  --debug           Enable debug logging
  --config=FILE     Override config file path
  --help            Show help
  --version         Show version

Commands:
  backup            [--target=NAME] [--remote=NAME] [--all]
  restore           --target=NAME --snapshot=TS [--remote=NAME] [--dest=DIR] [--skip-mysql]
  targets           list | add | delete | show [--name=NAME] [--folders=PATHS]
  remotes           list | add | delete | show | test | disk-info-short [--name=NAME]
  snapshots         list [--target=NAME] [--remote=NAME]
                    browse --target=NAME --snapshot=TS [--remote=NAME]
  retention         [--target=NAME] [--remote=NAME] [--all]
  schedule          install | show | remove
  logs              [--last] [--tail=N]
  web               start | install-service | remove-service | status [--port=PORT]
  uninstall
```

## Configuration

| Mode | Config | Logs | Lock |
|------|--------|------|------|
| Root | `/etc/gniza/` | `/var/log/gniza/` | `/var/run/gniza.lock` |
| User | `~/.config/gniza/` | `~/.local/state/gniza/log/` | `$XDG_RUNTIME_DIR/gniza-$UID.lock` |

Config subdirectories: `targets.d/*.conf`, `remotes.d/*.conf`, `schedules.d/*.conf`

### Global Settings (`gniza.conf`)

```ini
BWLIMIT=0                      # Bandwidth limit in KB/s (0 = unlimited)
RETENTION_COUNT=30              # Default snapshots to keep
LOG_LEVEL="info"                # info or debug
LOG_RETAIN=90                   # Days to keep log files
DISK_USAGE_THRESHOLD=95         # Abort if destination >= this % (0 = disabled)
SSH_TIMEOUT=30                  # SSH connection timeout in seconds
SSH_RETRIES=3                   # Number of retry attempts
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
TARGET_RETENTION=""             # Override retention count
TARGET_PRE_HOOK=""              # Shell command before backup
TARGET_POST_HOOK=""             # Shell command after backup
TARGET_ENABLED="yes"

# Remote source (pull from another machine)
TARGET_SOURCE_TYPE="local"      # local | ssh | s3 | gdrive

# SSH source
TARGET_SOURCE_HOST=""
TARGET_SOURCE_PORT="22"
TARGET_SOURCE_USER="root"
TARGET_SOURCE_AUTH_METHOD="key" # key | password
TARGET_SOURCE_KEY=""
TARGET_SOURCE_PASSWORD=""

# S3 source
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
REMOTE_BASE="/backups"
BWLIMIT=0                      # Override global bandwidth limit
RETENTION_COUNT=30              # Override global retention
```

**Local destination** (USB drive, NFS mount):

```ini
REMOTE_TYPE="local"
REMOTE_BASE="/mnt/backup-drive"
```

**S3 destination**:

```ini
REMOTE_TYPE="s3"
S3_BUCKET="my-backups"
S3_ACCESS_KEY_ID="AKIA..."
S3_SECRET_ACCESS_KEY="..."
S3_REGION="us-east-1"
S3_ENDPOINT=""                  # For S3-compatible (MinIO, DigitalOcean Spaces)
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
TARGETS=""                      # Comma-separated sources (empty = all)
REMOTES=""                      # Comma-separated destinations (empty = all)
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

### S3 / Google Drive Source

Pull files from cloud storage before backing them up:

- **S3**: Set `TARGET_SOURCE_TYPE="s3"` with bucket, region, and credentials
- **Google Drive**: Set `TARGET_SOURCE_TYPE="gdrive"` with a service account JSON file

Requires `rclone` to be installed.

## Snapshot Structure

```
$BASE/<hostname>/targets/<source>/snapshots/<YYYY-MM-DDTHHMMSS>/
├── meta.json           # Metadata (source, timestamp, duration, pinned)
├── manifest.txt        # File listing
├── var/www/            # Backed-up directories
├── etc/nginx/
└── _mysql/             # MySQL dumps (if enabled)
    ├── dbname.sql.gz
    └── _grants.sql.gz
```

During transfer, snapshots are stored in a `.partial` directory. On success, the directory is renamed to the final timestamp. Interrupted backups leave no incomplete snapshots.

## Retention

Retention policies control how many snapshots to keep per source per destination.

- **Global default**: `RETENTION_COUNT` in `gniza.conf` (default: 30)
- **Per-destination override**: `RETENTION_COUNT` in the destination config
- **Per-source override**: `TARGET_RETENTION` in the source config
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

## Scheduling

gniza manages cron entries for automated backups.

```bash
# Via CLI
gniza --cli schedule install     # Install all schedules to crontab
gniza --cli schedule show        # Show current cron entries
gniza --cli schedule remove      # Remove gniza cron entries
```

Cron entries are tagged with `# gniza4linux:<name>` for clean install/removal. Each schedule can target specific sources and destinations.

## Notifications

Email notifications on backup success or failure.

**SMTP** (recommended): Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, and `SMTP_SECURITY` in `gniza.conf`. Supports TLS, SSL, and plaintext.

**System mail**: Falls back to `mail` or `sendmail` if SMTP is not configured.

**Report includes**: Status, source count (total/succeeded/failed), duration, failed source list, log file path, hostname, and timestamp.

## Web Dashboard

Serve the full TUI in a browser via textual-serve with HTTP Basic Auth.

```bash
# Enable during install (generates admin password)
# Or set up manually:
gniza web install-service   # Install systemd service (port 2323)
gniza web start             # Start the service
gniza web status            # Check status
```

Access at `http://<server-ip>:2323`. Credentials are stored in `gniza.conf` as `WEB_USER` and `WEB_API_KEY`.

Supports both root (system service) and user (user service) modes.

## Terminal UI

Launch with `gniza` (no arguments). The TUI provides:

- **Sources** — Create, edit, delete backup sources with folder browser
- **Destinations** — Configure SSH, local, S3, or Google Drive destinations with connection testing
- **Backup** — Run backups with source/destination selection
- **Restore** — Browse snapshots and restore to original location or custom directory
- **Running Tasks** — Monitor active backup/restore jobs with live log output
- **Schedules** — Manage cron schedules with time/day pickers
- **Snapshots** — Browse and manage stored snapshots
- **Logs** — View backup history with pagination
- **Settings** — Configure global options
- **Setup Wizard** — Guided first-run configuration

The TUI adapts to terminal width, with an inline documentation panel on wide screens and a help modal on narrow ones.

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

## Testing

```bash
bash tests/test_utils.sh
bash tests/test_config.sh
bash tests/test_targets.sh
```

## License

MIT License - see [LICENSE](LICENSE) for details.
