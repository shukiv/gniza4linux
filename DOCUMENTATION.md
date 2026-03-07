# gniza Documentation

Complete reference for gniza, a Linux backup manager that works as a stand-alone backup solution or a centralized backup server.

---

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
- [Concepts](#concepts)
- [Sources](#sources)
- [Destinations](#destinations)
- [Backup](#backup)
- [Restore](#restore)
- [Snapshots](#snapshots)
- [Retention](#retention)
- [Scheduling](#scheduling)
- [MySQL Backup](#mysql-backup)
- [Notifications](#notifications)
- [Web Dashboard](#web-dashboard)
- [Terminal UI](#terminal-ui)
- [CLI Reference](#cli-reference)
- [Global Settings](#global-settings)
- [Security](#security)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

---

## Overview

gniza backs up files and MySQL databases from **sources** to **destinations** using incremental rsync snapshots with hardlink deduplication.

**Stand-alone mode**: Install gniza on any Linux machine. Define local folders as sources and back them up to an SSH server, USB drive, S3 bucket, or Google Drive.

**Backup server mode**: Install gniza on a central server. Define remote SSH servers, S3 buckets, or Google Drive accounts as sources. gniza pulls files from them and stores snapshots locally or on another destination — no agent needed on the source machines.

**Hybrid**: Mix local and remote sources freely. Back up local configs alongside files pulled from multiple remote servers.

### Interfaces

gniza provides three interfaces:

| Interface | Launch | Best for |
|-----------|--------|----------|
| **TUI** | `gniza` | Interactive management |
| **Web** | `gniza web start` | Remote browser access |
| **CLI** | `gniza --cli <command>` | Scripting and cron |

---

## Installation

### Quick Install

```bash
# Root mode (system-wide)
curl -sSL https://git.linux-hosting.co.il/shukivaknin/gniza4linux/raw/branch/main/scripts/install.sh | sudo bash

# User mode (per-user)
curl -sSL https://git.linux-hosting.co.il/shukivaknin/gniza4linux/raw/branch/main/scripts/install.sh | bash
```

### From Source

```bash
git clone https://git.linux-hosting.co.il/shukivaknin/gniza4linux.git
cd gniza4linux
sudo bash scripts/install.sh    # root mode
bash scripts/install.sh          # user mode
```

### Install Paths

| Mode | Application | Config | Logs |
|------|-------------|--------|------|
| Root | `/usr/local/gniza` | `/etc/gniza/` | `/var/log/gniza/` |
| User | `~/.local/share/gniza` | `~/.config/gniza/` | `~/.local/state/gniza/log/` |

### Dependencies

| Package | Required | Purpose |
|---------|----------|---------|
| bash 4+ | Yes | Core scripting |
| rsync | Yes | File transfer and deduplication |
| ssh | No | SSH sources and destinations |
| sshpass | No | Password-based SSH authentication |
| curl | No | SMTP email notifications |
| rclone | No | S3 and Google Drive support |
| python3 | No | TUI and web dashboard |
| textual | No | Terminal UI framework |
| textual-serve | No | Web dashboard |

The installer detects available dependencies and warns about missing optional ones.

### Post-Install

After installation, run `gniza` to launch the TUI. On first run, the setup wizard guides you through creating your first source and destination.

---

## Concepts

### Sources

A **source** defines *what* to back up: a set of folders, optional filters, hooks, and MySQL database settings. Sources can pull data from local directories, remote SSH servers, S3 buckets, or Google Drive.

Config location: `<config_dir>/targets.d/<name>.conf`

### Destinations

A **destination** defines *where* to store backup snapshots. Destinations can be SSH servers, local drives (USB/NFS), S3 buckets, or Google Drive.

Config location: `<config_dir>/remotes.d/<name>.conf`

### Snapshots

Each backup creates a **snapshot** — a timestamped directory containing a full copy of the backed-up files. Unchanged files are hardlinked to the previous snapshot, saving disk space while keeping each snapshot independently browseable and restorable.

### Retention

**Retention** controls how many snapshots to keep. Old snapshots are automatically pruned after each backup. Individual snapshots can be **pinned** to prevent deletion.

---

## Sources

### Creating a Source

**TUI**: Navigate to Sources > Add.

**CLI**:
```bash
gniza --cli sources add --name=mysite --folders=/var/www,/etc/nginx
```

**Manual**: Create `<config_dir>/targets.d/mysite.conf`.

### Source Configuration

#### Basic Fields

| Field | Default | Description |
|-------|---------|-------------|
| `TARGET_NAME` | (required) | Unique name for this source |
| `TARGET_FOLDERS` | (required) | Comma-separated absolute paths to back up |
| `TARGET_EXCLUDE` | (empty) | Comma-separated rsync exclude patterns |
| `TARGET_INCLUDE` | (empty) | Comma-separated rsync include patterns |
| `TARGET_REMOTE` | (empty) | Pin to a specific destination (empty = all) |
| `TARGET_RETENTION` | (empty) | Override retention count (empty = use destination default) |
| `TARGET_PRE_HOOK` | (empty) | Shell command to run before backup |
| `TARGET_POST_HOOK` | (empty) | Shell command to run after backup |
| `TARGET_ENABLED` | `yes` | Set to `no` to skip this source during backups |

#### Include and Exclude Filters

Filters use rsync glob syntax and are comma-separated.

**Exclude mode**: Skip files matching the patterns.
```ini
TARGET_EXCLUDE="*.log,*.tmp,.cache,node_modules"
```

**Include mode**: Only back up files matching the patterns. Everything else is excluded.
```ini
TARGET_INCLUDE="*.conf,*.sh,*.py"
```

If both are set, include takes precedence.

#### Source Types

By default, sources back up local directories. Set `TARGET_SOURCE_TYPE` to pull from remote locations instead.

##### Local Source (default)

```ini
TARGET_SOURCE_TYPE="local"
TARGET_FOLDERS="/var/www,/etc/nginx"
```

Folders must exist on the local machine.

##### SSH Source

Pull files from a remote server over SSH. No agent needed on the remote machine.

```ini
TARGET_SOURCE_TYPE="ssh"
TARGET_SOURCE_HOST="web-server.example.com"
TARGET_SOURCE_PORT="22"
TARGET_SOURCE_USER="root"
TARGET_SOURCE_AUTH_METHOD="key"
TARGET_SOURCE_KEY="/root/.ssh/id_rsa"
TARGET_FOLDERS="/var/www,/etc/nginx,/etc/mysql"
```

For password authentication:
```ini
TARGET_SOURCE_AUTH_METHOD="password"
TARGET_SOURCE_PASSWORD="your-password"
```

Requires `sshpass` for password auth.

##### S3 Source

Pull files from an S3 or S3-compatible bucket (MinIO, DigitalOcean Spaces, Backblaze B2).

```ini
TARGET_SOURCE_TYPE="s3"
TARGET_SOURCE_S3_BUCKET="my-app-data"
TARGET_SOURCE_S3_REGION="us-east-1"
TARGET_SOURCE_S3_ACCESS_KEY_ID="AKIA..."
TARGET_SOURCE_S3_SECRET_ACCESS_KEY="..."
TARGET_SOURCE_S3_ENDPOINT=""
TARGET_FOLDERS="/uploads,/media"
```

Set `TARGET_SOURCE_S3_ENDPOINT` for S3-compatible providers:
```ini
TARGET_SOURCE_S3_ENDPOINT="https://nyc3.digitaloceanspaces.com"
```

Requires `rclone`.

##### Google Drive Source

Pull files from Google Drive using a service account.

```ini
TARGET_SOURCE_TYPE="gdrive"
TARGET_SOURCE_GDRIVE_SERVICE_ACCOUNT_FILE="/path/to/service-account.json"
TARGET_SOURCE_GDRIVE_ROOT_FOLDER_ID="1abc..."
TARGET_FOLDERS="/shared-docs,/reports"
```

Requires `rclone`.

#### Pre/Post Hooks

Run shell commands before and after backup:

```ini
TARGET_PRE_HOOK="systemctl stop myapp"
TARGET_POST_HOOK="systemctl start myapp"
```

- **Pre-hook failure** aborts the backup
- **Post-hook failure** is logged as a warning but does not mark the backup as failed

Common uses:
- Stop/start services for consistent snapshots
- Flush caches or application buffers
- Trigger database snapshots
- Send custom notifications

### Viewing a Source

```bash
gniza --cli sources show --name=mysite
```

Shows all configured fields including source type details and MySQL settings.

### Deleting a Source

```bash
gniza --cli sources delete --name=mysite
```

This removes the config file only. Existing snapshots on destinations are not affected.

---

## Destinations

### Creating a Destination

**TUI**: Navigate to Destinations > Add.

**CLI**:
```bash
gniza --cli destinations add --name=backup-server
```

This creates a config template. Edit it manually or use the TUI to configure.

### Destination Types

#### SSH Destination

Store snapshots on a remote server via SSH.

```ini
REMOTE_TYPE="ssh"
REMOTE_HOST="backup.example.com"
REMOTE_PORT="22"
REMOTE_USER="root"
REMOTE_AUTH_METHOD="key"
REMOTE_KEY="/root/.ssh/id_rsa"
REMOTE_BASE="/backups"
BWLIMIT="0"
RETENTION_COUNT="30"
```

If `REMOTE_KEY` is not specified, it defaults to `~/.ssh/id_rsa`.

For password authentication:
```ini
REMOTE_AUTH_METHOD="password"
REMOTE_PASSWORD="your-password"
```

#### Local Destination

Store snapshots on a local drive (USB, NFS mount, second disk).

```ini
REMOTE_TYPE="local"
REMOTE_BASE="/mnt/backup-drive"
RETENTION_COUNT="30"
```

#### S3 Destination

Store snapshots in an S3 or S3-compatible bucket.

```ini
REMOTE_TYPE="s3"
S3_BUCKET="my-backups"
S3_ACCESS_KEY_ID="AKIA..."
S3_SECRET_ACCESS_KEY="..."
S3_REGION="us-east-1"
S3_ENDPOINT=""
REMOTE_BASE="/backups"
RETENTION_COUNT="30"
```

Requires `rclone`.

#### Google Drive Destination

Store snapshots in Google Drive using a service account.

```ini
REMOTE_TYPE="gdrive"
GDRIVE_SERVICE_ACCOUNT_FILE="/path/to/service-account.json"
GDRIVE_ROOT_FOLDER_ID=""
REMOTE_BASE="/backups"
RETENTION_COUNT="30"
```

Requires `rclone`.

### Destination Fields

| Field | Default | Description |
|-------|---------|-------------|
| `REMOTE_TYPE` | `ssh` | `ssh`, `local`, `s3`, or `gdrive` |
| `REMOTE_HOST` | (required for SSH) | Hostname or IP |
| `REMOTE_PORT` | `22` | SSH port |
| `REMOTE_USER` | `root` | SSH username |
| `REMOTE_AUTH_METHOD` | `key` | `key` or `password` |
| `REMOTE_KEY` | `~/.ssh/id_rsa` | Path to SSH private key |
| `REMOTE_PASSWORD` | (empty) | SSH password (requires sshpass) |
| `REMOTE_BASE` | `/backups` | Base directory for snapshots |
| `BWLIMIT` | `0` | Bandwidth limit in KB/s (0 = unlimited) |
| `RETENTION_COUNT` | `30` | Number of snapshots to keep per source |

### Testing a Destination

```bash
gniza --cli destinations test --name=backup-server
```

Validates connectivity and configuration. For SSH destinations, tests the SSH connection. For S3/GDrive, verifies credentials and access.

### Checking Disk Usage

```bash
gniza --cli destinations disk-info-short --name=backup-server
```

Shows used/total space, free space, and usage percentage. Works with SSH and local destinations.

---

## Backup

### Running a Backup

```bash
# Back up all sources to all destinations
gniza --cli backup --all

# Back up a specific source
gniza --cli backup --source=mysite

# Back up a specific source to a specific destination
gniza --cli backup --source=mysite --destination=backup-server

# Back up multiple sources
gniza --cli backup --source=mysite,databases
```

### How Backup Works

1. **Pre-hook** runs (if configured). Failure aborts the backup.
2. **Disk space check** on the destination. If usage exceeds the threshold (default 95%), the backup aborts.
3. **Source pull** (for remote sources): Files are pulled from the remote source to a local staging area.
4. **Transfer**: rsync transfers files to the destination using `--link-dest` to hardlink unchanged files from the previous snapshot. The snapshot is stored in a `.partial` directory during transfer.
5. **MySQL dump** (if enabled): Databases are dumped and included in the snapshot.
6. **Atomic rename**: The `.partial` directory is renamed to the final timestamp on success.
7. **Post-hook** runs (if configured).
8. **Retention** enforcement: Old snapshots beyond the retention count are deleted.
9. **Notification** sent (if configured).

### Incremental Deduplication

gniza uses rsync's `--link-dest` to create space-efficient incremental backups.

- **First backup**: All files are transferred in full. This is the slowest backup.
- **Subsequent backups**: Only changed files are transferred. Unchanged files are hardlinked to the previous snapshot, sharing disk blocks.
- Each snapshot appears as a **complete directory tree** — fully browseable and restorable on its own.
- 10 snapshots of 50 GB with minor daily changes might use 55 GB total instead of 500 GB.
- Deleting a snapshot only frees space for files not referenced by other snapshots.

### Atomic Snapshots

During transfer, data is stored in a `.partial` directory. Only when the transfer completes successfully is it renamed to the final timestamp. If a backup is interrupted, no incomplete snapshot is left behind.

### Disk Space Safety

Before each backup, gniza checks the destination disk usage. If it equals or exceeds the configured threshold, the backup aborts.

```ini
# In gniza.conf
DISK_USAGE_THRESHOLD=95    # Abort if destination >= 95% full (0 = disabled)
```

### Bandwidth Limiting

Limit transfer speed globally or per destination:

```ini
# Global (gniza.conf)
BWLIMIT=10000              # 10 MB/s

# Per destination (remotes.d/<name>.conf)
BWLIMIT=5000               # 5 MB/s — overrides global
```

Value is in KB/s. Set to `0` for unlimited.

### Retry Logic

SSH connections are automatically retried on failure with exponential backoff:

```ini
# In gniza.conf
SSH_TIMEOUT=30             # Connection timeout in seconds
SSH_RETRIES=3              # Number of retry attempts (waits 10s, 20s, 30s)
```

Rsync partial transfers (exit codes 23/24) are also handled gracefully.

### Concurrency

Each source uses `flock`-based locking to prevent overlapping backups of the same source. Multiple different sources can run in parallel.

---

## Restore

### Restoring from CLI

```bash
# Restore latest snapshot in-place
gniza --cli restore --source=mysite --destination=backup-server

# Restore a specific snapshot
gniza --cli restore --source=mysite --destination=backup-server --snapshot=2026-03-07T020000

# Restore to a custom directory
gniza --cli restore --source=mysite --destination=backup-server --dest=/tmp/restore

# Restore a single folder from a snapshot
gniza --cli restore --source=mysite --destination=backup-server --snapshot=2026-03-07T020000 --folder=/var/www

# Skip MySQL restore
gniza --cli restore --source=mysite --destination=backup-server --skip-mysql
```

### Restore Behavior

- **In-place restore**: Files are restored to their original locations, overwriting current files.
- **Custom directory restore**: Files are restored under the specified directory, preserving the original path structure.
- **MySQL restore**: If the snapshot contains MySQL dumps (`_mysql/` directory), they are automatically restored unless `--skip-mysql` is passed.
- **Single folder restore**: Only the specified folder is restored from the snapshot.

### Restoring from TUI

Navigate to Restore, select a source, destination, and snapshot, choose in-place or custom directory, and optionally toggle MySQL restore on/off.

---

## Snapshots

### Listing Snapshots

```bash
# List all snapshots for all sources on the first destination
gniza --cli snapshots list

# List snapshots for a specific source
gniza --cli snapshots list --source=mysite

# List snapshots on a specific destination
gniza --cli snapshots list --destination=backup-server

# Both
gniza --cli snapshots list --source=mysite --destination=backup-server
```

### Browsing Snapshot Contents

```bash
gniza --cli snapshots browse --source=mysite --snapshot=2026-03-07T020000
```

Lists all files in the snapshot.

### Snapshot Structure

```
<base>/<hostname>/targets/<source>/snapshots/<YYYY-MM-DDTHHMMSS>/
├── meta.json               # Metadata: source, timestamp, duration, pinned flag
├── manifest.txt            # File listing
├── summary                 # Backup summary
├── var/www/                # Backed-up directories (original structure)
├── etc/nginx/
└── _mysql/                 # MySQL dumps (if enabled)
    ├── dbname.sql.gz       # Gzip-compressed database dump
    └── _grants.sql.gz      # User grants and privileges
```

### Snapshot Metadata (meta.json)

```json
{
  "target": "mysite",
  "timestamp": "2026-03-07T020000",
  "duration_seconds": 45,
  "pinned": false
}
```

---

## Retention

Retention controls how many snapshots are kept per source per destination.

### Configuration Priority

1. **Per-source** `TARGET_RETENTION` (highest priority)
2. **Per-destination** `RETENTION_COUNT`
3. **Global** `RETENTION_COUNT` in `gniza.conf` (default: 30)

### Automatic Enforcement

Retention runs automatically after each successful backup. The oldest snapshots beyond the retention count are deleted.

### Manual Enforcement

```bash
# Enforce retention for all sources on all destinations
gniza --cli retention --all

# Enforce for a specific source
gniza --cli retention --source=mysite

# Enforce on a specific destination
gniza --cli retention --destination=backup-server
```

### Snapshot Pinning

Pinned snapshots are never deleted by retention enforcement. Pin a snapshot by setting `"pinned": true` in its `meta.json` file.

---

## Scheduling

gniza manages cron entries for automated backups.

### Creating a Schedule

**TUI**: Navigate to Schedules > Add.

**Manual**: Create `<config_dir>/schedules.d/<name>.conf`:

```ini
SCHEDULE="daily"                # hourly | daily | weekly | monthly | custom
SCHEDULE_TIME="02:00"           # HH:MM
SCHEDULE_DAY=""                 # Day of week (0=Sun..6=Sat) or day of month (1-28)
SCHEDULE_CRON=""                # Full cron expression (when SCHEDULE=custom)
SCHEDULE_ACTIVE="yes"           # yes | no
TARGETS=""                      # Comma-separated source names (empty = all)
REMOTES=""                      # Comma-separated destination names (empty = all)
```

### Schedule Types

| Type | SCHEDULE_TIME | SCHEDULE_DAY | Example |
|------|---------------|--------------|---------|
| `hourly` | `:MM` | - | Every hour at :30 |
| `daily` | `HH:MM` | - | Every day at 02:00 |
| `weekly` | `HH:MM` | `0`-`6` | Every Sunday at 03:00 |
| `monthly` | `HH:MM` | `1`-`28` | 1st of each month at 04:00 |
| `custom` | - | - | Full cron: `*/15 * * * *` |

### Filtering

Limit which sources and destinations a schedule applies to:

```ini
TARGETS="mysite,databases"      # Only back up these sources
REMOTES="backup-server"         # Only to this destination
```

Leave empty to include all.

### Managing Cron Entries

```bash
# Install all active schedules into crontab
gniza --cli schedule install

# View current gniza cron entries
gniza --cli schedule show

# Remove all gniza cron entries
gniza --cli schedule remove
```

Cron entries are tagged with `# gniza4linux:<name>` for clean management. Running `schedule install` replaces existing entries cleanly.

### How Scheduled Backups Run

Each cron entry calls `gniza scheduled-run --schedule=<name>`. This internal command:

1. Reads the schedule config to determine which sources and destinations to back up.
2. Runs the backup (same as `gniza --cli backup`).
3. On success, stamps `LAST_RUN="YYYY-MM-DD HH:MM"` in the schedule config file.

The `LAST_RUN` timestamp is displayed in the Schedules screen of the TUI.

### Cron Logs

Scheduled backups log output to `<log_dir>/cron.log`. Each run also creates a timestamped log file in the log directory (using local time).

---

## MySQL Backup

gniza can dump MySQL/MariaDB databases alongside file backups. Auto-detects `mysqldump` or `mariadb-dump`.

### Enabling MySQL Backup

In the source config:

```ini
TARGET_MYSQL_ENABLED="yes"
TARGET_MYSQL_USER="backup_user"
TARGET_MYSQL_PASSWORD="secret"
TARGET_MYSQL_HOST="localhost"
TARGET_MYSQL_PORT="3306"
```

### Dump Modes

**All databases** (default):
```ini
TARGET_MYSQL_MODE="all"
TARGET_MYSQL_EXCLUDE="test_db,staging_db"
```

Dumps every user database except system databases (`information_schema`, `performance_schema`, `sys`, `mysql`) and any in the exclude list.

**Selected databases**:
```ini
TARGET_MYSQL_MODE="selected"
TARGET_MYSQL_DATABASES="app_db,user_db,analytics"
```

### Dump Options

```ini
TARGET_MYSQL_EXTRA_OPTS="--single-transaction --routines --triggers"
```

Default options ensure consistent dumps for InnoDB tables and include stored procedures and triggers.

### What Gets Dumped

- Each database is dumped as `<dbname>.sql.gz` (gzip compressed)
- User grants are dumped as `_grants.sql.gz`
- All dumps are stored in the `_mysql/` directory within the snapshot

### MySQL Restore

During restore, MySQL dumps from `_mysql/` are automatically restored. Use `--skip-mysql` to skip:

```bash
gniza --cli restore --source=mysite --destination=backup-server --skip-mysql
```

In the TUI, toggle the "Restore MySQL databases" switch.

---

## Notifications

gniza sends email notifications on backup completion.

### Configuration

In `gniza.conf`:

```ini
NOTIFY_ON="failure"             # never | failure | always
NOTIFY_EMAIL="admin@example.com,ops@example.com"

# SMTP settings (recommended)
SMTP_HOST="smtp.gmail.com"
SMTP_PORT="587"
SMTP_USER="alerts@example.com"
SMTP_PASSWORD="app-password"
SMTP_FROM="gniza@example.com"
SMTP_SECURITY="tls"            # tls | ssl | none
```

### Notification Modes

| Mode | When emails are sent |
|------|---------------------|
| `never` | No notifications |
| `failure` | Only when a backup fails (default) |
| `always` | After every backup run |

### Email Content

Notification emails include:
- Status: SUCCESS, PARTIAL FAILURE, or FAILURE
- Source count: total, succeeded, failed
- Duration
- List of failed sources (if any)
- Log file path
- Hostname and timestamp

### Test Email

Verify your SMTP settings by sending a test email:

**TUI**: Settings > Send Test Email (automatically saves settings first).

**CLI**:
```bash
gniza --cli test-email
```

Requires `NOTIFY_EMAIL` and `SMTP_HOST` to be configured.

### Fallback

If SMTP is not configured, gniza falls back to the system `mail` or `sendmail` command.

---

## Web Dashboard

Serve the full TUI in a browser with HTTP Basic Auth.

### Setup

```bash
# Install as a systemd service (auto-starts on boot)
gniza web install-service

# Or start manually
gniza web start
```

Access at `http://<server-ip>:2323`.

### Service Management

```bash
gniza web install-service       # Install and start systemd service
gniza web remove-service        # Stop and remove service
gniza web status                # Check service status
gniza web start                 # Start manually (foreground)
gniza web start --port=8080     # Custom port
gniza web start --host=127.0.0.1  # Bind to localhost only
```

### Configuration

Web dashboard settings are in `gniza.conf`:

```ini
WEB_PORT="2323"                        # Dashboard port
WEB_HOST="0.0.0.0"                     # Bind address (0.0.0.0 = all interfaces)
WEB_USER="admin"                       # HTTP Basic Auth username
WEB_API_KEY="generated-during-install" # HTTP Basic Auth password
```

The API key is generated automatically during installation if you enable the web dashboard. You can change it in Settings or directly in `gniza.conf`.

After changing web settings, restart the service:
```bash
systemctl --user restart gniza-web.service   # user mode
sudo systemctl restart gniza-web.service     # root mode
```

### Mobile Access

The web dashboard works on mobile browsers. On small screens:
- Font size auto-adjusts to fit approximately 50 columns
- Button rows scroll horizontally
- The documentation panel hides automatically on narrow screens
- Touch scrolling is supported in all scrollable areas

### Root vs User Mode

- **Root**: Installs as a system service (`/etc/systemd/system/gniza-web.service`)
- **User**: Installs as a user service (`~/.config/systemd/user/gniza-web.service`)

---

## Terminal UI

Launch with `gniza` (no arguments). Requires Python 3 and Textual.

### Screens

| Screen | Description |
|--------|-------------|
| **Sources** | Create, edit, delete, and view backup sources |
| **Destinations** | Configure SSH, local, S3, or Google Drive destinations |
| **Backup** | Select sources and destinations, run backups |
| **Restore** | Browse snapshots, restore to original or custom location |
| **Running Tasks** | Monitor active jobs with live log output and progress |
| **Schedules** | Create and manage cron schedules, view last run time |
| **Snapshots** | Browse stored snapshots |
| **Logs** | View backup history with pagination |
| **Settings** | Configure global options in organized sections |

### Navigation

Every screen has a **← Back** button in the top-left corner next to the screen title. Press `Escape` or click the button to return to the previous screen.

### Settings Screen

The Settings screen organizes options into four bordered sections:

| Section | Contents |
|---------|----------|
| **General** | Log level, log retention, retention count, bandwidth limit, disk threshold, rsync options |
| **Email Notifications** | Email address, notify mode, SMTP host/port/user/password/from/security, Send Test Email button |
| **SSH** | SSH timeout, SSH retries |
| **Web Dashboard** | Port, host, API key |

### Features

- **Setup Wizard**: Guided first-run configuration
- **Folder Browser**: Navigate local and remote directories when configuring sources
- **Remote Folder Browser**: Browse SSH destination directories
- **Connection Testing**: Test destination connectivity from the edit screen
- **Documentation Panel**: Inline help on wide screens, help modal on narrow ones
- **Responsive Layout**: Adapts to terminal width; button rows scroll horizontally on narrow screens
- **Job Manager**: Run backups/restores in background with live log streaming

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Escape` | Go back / Cancel |
| `F1` | Toggle help panel |
| `Enter` | Select / Confirm |

---

## CLI Reference

### Global Options

```
--cli             Force CLI mode (skip TUI)
--debug           Enable debug logging
--config=FILE     Override config file path
--help            Show help
--version         Show version
```

### Sources

```bash
gniza --cli sources list                              # List all sources
gniza --cli sources add --name=NAME --folders=PATHS   # Create a source
gniza --cli sources delete --name=NAME                # Delete a source
gniza --cli sources show --name=NAME                  # Show source details
```

### Destinations

```bash
gniza --cli destinations list                              # List all destinations
gniza --cli destinations add --name=NAME                   # Create a destination
gniza --cli destinations delete --name=NAME                # Delete a destination
gniza --cli destinations show --name=NAME                  # Show destination details
gniza --cli destinations test --name=NAME                  # Test connectivity
gniza --cli destinations disk-info-short --name=NAME       # Show disk usage
```

### Backup

```bash
gniza --cli backup --all                              # Back up everything
gniza --cli backup --source=NAME                      # Back up one source
gniza --cli backup --source=NAME --destination=NAME        # Source to specific destination
gniza --cli backup --source=a,b,c                     # Multiple sources
```

### Restore

```bash
gniza --cli restore --source=NAME --destination=NAME --snapshot=TS
gniza --cli restore --source=NAME --destination=NAME --dest=/tmp/restore
gniza --cli restore --source=NAME --destination=NAME --folder=/var/www
gniza --cli restore --source=NAME --destination=NAME --skip-mysql
```

### Snapshots

```bash
gniza --cli snapshots list                            # All snapshots
gniza --cli snapshots list --source=NAME              # For one source
gniza --cli snapshots list --destination=NAME              # On one destination
gniza --cli snapshots browse --source=NAME --snapshot=TS
```

### Retention

```bash
gniza --cli retention --all                           # Enforce everywhere
gniza --cli retention --source=NAME                   # One source
gniza --cli retention --destination=NAME                   # One destination
```

### Scheduling

```bash
gniza --cli schedule install                          # Install cron entries
gniza --cli schedule show                             # Show current entries
gniza --cli schedule remove                           # Remove all entries
gniza scheduled-run --schedule=NAME                   # Run a schedule (used by cron)
```

### Logs

```bash
gniza --cli logs                                      # List log files
gniza --cli logs --last                               # Show latest log
gniza --cli logs --last --tail=50                     # Last 50 lines
```

### Web Dashboard

```bash
gniza web start                                       # Start web server
gniza web start --port=8080 --host=0.0.0.0           # Custom port/host
gniza web install-service                             # Install systemd service
gniza web remove-service                              # Remove service
gniza web status                                      # Check status
```

### Notifications

```bash
gniza --cli test-email                                # Send a test email
```

### System

```bash
gniza --version                                       # Show version
gniza uninstall                                       # Uninstall gniza
```

---

## Global Settings

All global settings are in `gniza.conf` in the config directory.

### Backup Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `BACKUP_MODE` | `incremental` | Backup mode |
| `BWLIMIT` | `0` | Global bandwidth limit in KB/s |
| `RETENTION_COUNT` | `30` | Default snapshots to keep |
| `DISK_USAGE_THRESHOLD` | `95` | Abort if destination >= this % (0 = disabled) |
| `RSYNC_EXTRA_OPTS` | (empty) | Additional rsync flags |
| `WORK_DIR` | `/tmp` | Temp directory for staging and dumps |

### SSH Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `SSH_TIMEOUT` | `30` | Connection timeout in seconds |
| `SSH_RETRIES` | `3` | Number of retry attempts |

### Logging

| Setting | Default | Description |
|---------|---------|-------------|
| `LOG_LEVEL` | `info` | `debug`, `info`, `warn`, or `error` |
| `LOG_RETAIN` | `90` | Days to keep log files |

Log files are named using local time (e.g., `gniza-20260307-040001.log`) to match cron schedules which also run in local time.

### Notifications

| Setting | Default | Description |
|---------|---------|-------------|
| `NOTIFY_ON` | `failure` | `never`, `failure`, or `always` |
| `NOTIFY_EMAIL` | (empty) | Comma-separated recipient addresses |
| `SMTP_HOST` | (empty) | SMTP server hostname |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | (empty) | SMTP username |
| `SMTP_PASSWORD` | (empty) | SMTP password |
| `SMTP_FROM` | (empty) | Sender address |
| `SMTP_SECURITY` | `tls` | `tls`, `ssl`, or `none` |

### Web Dashboard

| Setting | Default | Description |
|---------|---------|-------------|
| `WEB_USER` | `admin` | HTTP Basic Auth username |
| `WEB_API_KEY` | (empty) | HTTP Basic Auth password |
| `WEB_PORT` | `2323` | Dashboard port |
| `WEB_HOST` | `0.0.0.0` | Dashboard bind address |

---

## Security

### File Permissions

- Config files are created with mode `600` (owner read/write only)
- Temp files (rclone configs, staging areas) use restrictive umask

### Credential Handling

- Passwords are never logged or displayed in output
- `sources show` and `destinations show` mask passwords with `****`
- MySQL passwords are passed via `MYSQL_PWD` environment variable
- SSH passwords are passed via `sshpass`, not command-line arguments

### Authentication Methods

| Destination/Source | Methods |
|-------------------|---------|
| SSH | Key-based (RSA/ECDSA/Ed25519), password (via sshpass) |
| S3 | Access Key ID + Secret Access Key |
| Google Drive | Service account JSON file |
| Web dashboard | HTTP Basic Auth |

---

## Development

### Deploy Script

For developers, `scripts/deploy.sh` automates the deploy workflow:

```bash
bash scripts/deploy.sh "commit message"
```

This script:
1. Commits and pushes all changes to git
2. Syncs updated files to the local install directory (`~/.local/share/gniza`)
3. Restarts the web dashboard service if running

---

## Troubleshooting

### Checking Logs

```bash
# View the latest backup log
gniza --cli logs --last

# View the last 100 lines
gniza --cli logs --last --tail=100

# Enable debug logging for the next run
gniza --cli --debug backup --all
```

### Common Issues

**"No destinations configured"**
Create at least one destination in `<config_dir>/remotes.d/`.

**SSH connection failures**
- Test with: `gniza --cli destinations test --name=<destination>`
- Check that the SSH key exists and has correct permissions (600)
- Verify the remote host is reachable: `ssh -p PORT user@host`
- If using password auth, ensure `sshpass` is installed

**Backup aborted due to disk space**
The destination disk usage exceeds the threshold. Free space or adjust `DISK_USAGE_THRESHOLD` in `gniza.conf`.

**Cron not running or using stale flags**
- Check that cron entries are installed: `gniza --cli schedule show`
- Verify the cron daemon is running: `systemctl status cron`
- Check cron logs: `<log_dir>/cron.log`
- Re-install entries: `gniza --cli schedule install` (this regenerates all entries with current flags)

**rclone required**
S3 and Google Drive sources/destinations require rclone. Install from https://rclone.org/install/.

**TUI not launching**
Ensure Python 3 and Textual are installed: `python3 -c "import textual"`. The installer normally handles this.

**Web dashboard not accessible**
- Check service status: `gniza web status`
- Verify the port is open: `ss -tlnp | grep 2323`
- Check credentials in `gniza.conf` (`WEB_USER` and `WEB_API_KEY`)
