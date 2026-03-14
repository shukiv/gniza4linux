# GNIZA Documentation

Complete reference for GNIZA, a Linux backup manager that works as a stand-alone backup solution or a centralized backup server.

---

## Table of Contents

- [Getting Started](#getting-started)
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
- [PostgreSQL Backup](#postgresql-backup)
- [Notifications](#notifications)
- [Web Dashboard](#web-dashboard)
- [Background Daemon](#background-daemon)
- [Terminal UI](#terminal-ui)
- [CLI Reference](#cli-reference)
- [Global Settings](#global-settings)
- [Security](#security)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

---

## Getting Started

This step-by-step guide walks you through setting up GNIZA from scratch — from installation to your first automated backup.

### What is GNIZA?

GNIZA is a complete Linux backup solution that can run as a **stand-alone backup tool** or as a **centralized backup server** managing multiple machines. It is built on top of rsync with `--link-dest` for incremental hardlink deduplication — each snapshot looks like a full backup but only changed files consume extra disk space.

Key features:

- **Agentless** — no software needed on source machines (SSH pull)
- **Incremental snapshots** with hardlink deduplication
- **Atomic snapshots** — `.partial` directory renamed on success
- **Built-in MySQL/MariaDB** dump support
- **Built-in PostgreSQL** dump support
- **Multiple source types**: local, SSH, S3, Google Drive
- **Multiple destination types**: local, SSH, S3, Google Drive
- **Automatic retention** and pruning
- **Multi-channel notifications** (Email, Telegram, Webhook, ntfy, Healthchecks.io) on success/failure
- **Three interfaces**: Web Dashboard, Terminal UI (TUI), and CLI

### Why GNIZA?

If you have ever set up backups with raw rsync, tar, or tools like Dirvish, you know how much manual plumbing is involved — writing wrapper scripts, managing retention, setting up cron jobs, handling MySQL dumps separately, and hoping nothing silently breaks.

| Manual Approach | GNIZA |
|---|---|
| Write rsync wrapper scripts | Declarative INI config files |
| DIY hardlink rotation | Automatic `--link-dest` dedup |
| Separate mysqldump/pg_dump cron | Built-in MySQL + PostgreSQL dump before file sync |
| Manual crontab entries | Schedule management via UI |
| Custom log parsing | Structured job logs with status |
| No visibility into progress | Real-time Running Tasks view |
| Manual cleanup of old backups | Automatic retention with pruning |
| Hope it works | Multi-channel alerts on success/failure |

### Step 1: Installation

GNIZA can be installed with a single command. The installer detects whether you are running as root or a regular user.

**As root (system-wide):**

```
curl -sL https://git.linux-hosting.co.il/shukivaknin/gniza4linux/raw/branch/main/scripts/install.sh | sudo bash
```

Installs to: `/usr/local/gniza` (app), `/etc/gniza/` (config), `/var/log/gniza/` (logs)

**As regular user:**

```
curl -sL https://git.linux-hosting.co.il/shukivaknin/gniza4linux/raw/branch/main/scripts/install.sh | bash
```

Installs to: `~/.local/share/gniza` (app), `~/.config/gniza/` (config), `~/.local/state/gniza/log/` (logs)

**Prerequisites** (installer handles most automatically): rsync, ssh, python3 + pip, curl or wget.

> **Tip:** After installation, access the web dashboard at `http://your-server:2323`. Log in with the password shown during installation (or set `WEB_API_KEY` in `gniza.conf`).

### Step 2: Setting up SSH Keys

For backing up remote machines or storing backups on a remote server, you need passwordless SSH access.

```
# Generate a key pair (no passphrase for automated backups)
ssh-keygen -t ed25519 -C "gniza-backup"

# Copy public key to the remote machine
ssh-copy-id user@remote-server

# Test — should connect without password prompt
ssh user@remote-server
```

> **Tip:** GNIZA also supports password-based SSH via sshpass. Set `SOURCE_AUTH_METHOD=password` in the source config. SSH keys are recommended.

### Step 3: Configure a Source (What to Back Up)

A **source** defines what data GNIZA should back up. Configure via web (Sources > Add), TUI, or config file.

**Local source** — back up folders on the same machine:

```ini
[target]
NAME=home
SOURCE_TYPE=local
FOLDERS=/home/user
ENABLED=yes
```

**Remote SSH source** — pull from a remote server (agentless):

```ini
[target]
NAME=webserver
SOURCE_TYPE=ssh
SOURCE_HOST=192.168.1.100
SOURCE_USER=backup
SOURCE_PORT=22
SOURCE_AUTH_METHOD=key
FOLDERS=/var/www,/etc
ENABLED=yes
```

### Step 4: Configure a Destination (Where to Store Backups)

A **destination** defines where GNIZA stores snapshots. Configure via web (Destinations > Add), TUI, or config file.

**SSH destination:**

```ini
[remote]
NAME=backup-server
TYPE=ssh
HOST=backup.example.com
USER=backup
PORT=22
AUTH_METHOD=key
BASE=/home/backup/gniza
```

**Local destination** (USB drive, NFS mount):

```ini
[remote]
NAME=usb-drive
TYPE=local
BASE=/mnt/backup-drive/gniza
```

S3 and Google Drive destinations are also supported — configure through the web dashboard.

### Step 5: Run Your First Backup

With a source and destination configured:

- **Web:** Backup page > select source > Run Backup
- **TUI:** `gniza --tui` > Backup screen
- **CLI:** `gniza --cli --backup home`

What happens during a backup:

1. GNIZA creates a `.partial` snapshot directory on the destination
2. rsync transfers files using `--link-dest` to hardlink unchanged files from the previous snapshot
3. If MySQL is enabled, databases are dumped before file transfer
4. On success, `.partial` is renamed to the final timestamped name (atomic)
5. A job log entry is recorded

> **Note:** The first backup transfers all files (no previous snapshot to link against). Subsequent runs are incremental — only changed files are transferred.

### Step 6: MySQL / MariaDB Backup

Enable MySQL backup in your source config:

```ini
[target]
NAME=webserver
SOURCE_TYPE=ssh
SOURCE_HOST=192.168.1.100
SOURCE_USER=backup
FOLDERS=/var/www,/etc
MYSQL_ENABLED=yes
MYSQL_USER=backup
MYSQL_PASS=secretpassword
MYSQL_DATABASES=all
MYSQL_GRANTS=yes
ENABLED=yes
```

For SSH sources, `mysqldump` runs on the **remote machine**. Dumps are stored alongside file snapshots.

> **Tip:** Create a dedicated MySQL user with read-only privileges and `LOCK TABLES` permission.

### Step 7: Schedule Automatic Backups

```ini
[schedule]
NAME=nightly
SCHEDULE=daily
TIME=02:00
TARGETS=home,webserver
ACTIVE=yes
```

Frequencies: `daily`, `weekly`, `monthly`. Each schedule can have its own `RETENTION_COUNT`.

### Step 8: Retention and Cleanup

GNIZA automatically prunes old snapshots:

- **Global default:** Set `RETENTION_COUNT=7` in `gniza.conf`
- **Per-schedule override:** Add `RETENTION_COUNT` to any schedule config
- **Snapshot pinning:** Pin important snapshots to protect them from pruning

### Step 9: Browsing and Restoring

- **Web:** Snapshots page > select source > browse files > download or restore
- **CLI:** `gniza --cli --restore home --snapshot 2026-03-10_020000 --target /home/user`
- **Manual:** Snapshots are regular directories — `cp` or `rsync` directly

```
# Copy a single file from backup
cp /path/to/backup/home/2026-03-10_020000/home/user/document.txt ~/document.txt

# Restore a full directory
rsync -avP /path/to/backup/home/2026-03-10_020000/var/www/ /var/www/
```

### Step 10: Monitoring

- **Logs** — view all job logs with status (success/failure/running)
- **Notifications** — configure email, Telegram, webhook, ntfy, and Healthchecks.io in Settings
- **Running Tasks** — real-time progress of active jobs
- **Health checks** — system state monitoring in Settings

### Best Practices

- **Exclude unnecessary files**: `.cache`, `node_modules`, `__pycache__`, `/proc`
- **Use SSH keys** over passwords for automated backups
- **Test restores regularly** — a backup you cannot restore from is not a backup
- **Monitor disk space** on destinations
- **Set sensible retention** — daily with 7-day retention, weekly with 4-week retention
- **Pin important snapshots** before major upgrades

---

## Overview

GNIZA backs up files and MySQL databases from **sources** to **destinations** using incremental rsync snapshots with hardlink deduplication.

**Stand-alone mode**: Install gniza on any Linux machine. Define local folders as sources and back them up to an SSH server, USB drive, S3 bucket, or Google Drive.

**Backup server mode**: Install gniza on a central server. Define remote SSH servers, S3 buckets, or Google Drive accounts as sources. gniza pulls files from them and stores snapshots locally or on another destination — no agent needed on the source machines.

**Hybrid**: Mix local and remote sources freely. Back up local configs alongside files pulled from multiple remote servers.

### Interfaces

GNIZA provides three interfaces:

| Interface | Launch | Best for |
|-----------|--------|----------|
| **TUI** | `gniza` | Interactive management |
| **Web** | `gniza web start` | Remote browser access |
| **CLI** | `gniza --cli <command>` | Scripting and cron |

All three interfaces provide the same capabilities. When adding a new feature, implement it across CLI, TUI, and Web to maintain parity.

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
| curl | No | Notifications (SMTP, Telegram, Webhook, ntfy, Healthchecks) |
| rclone | No | S3 and Google Drive support |
| python3 | No | TUI and web dashboard |
| textual | No | Terminal UI framework |
| flask | No | Web dashboard framework |

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

#### Test & Save (Sources)

When creating or editing a source in the TUI or web dashboard, the **Test & Save** button validates the connection before saving.

| Type | What is tested |
|------|---------------|
| **Local** | Folders exist (warning if missing, still saves) |
| **SSH** | SSH connection succeeds, first folder is accessible (warning if not) |
| **S3** | Credentials are present, bucket is accessible via `rclone lsd` |
| **Google Drive** | Service account file exists, access is verified via `rclone lsd` |

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

To use sudo for rsync on the source (when the SSH user is not root but needs elevated privileges to read files):
```ini
TARGET_SOURCE_SUDO="yes"
```

When enabled, gniza runs rsync via `sudo` on the remote source, allowing a non-root SSH user to back up files that require root access (e.g., `/etc`, `/var`).

##### S3 Source

Pull files from an S3 or S3-compatible bucket (AWS, Backblaze B2, Wasabi, MinIO, DigitalOcean Spaces).

```ini
TARGET_SOURCE_TYPE="s3"
TARGET_SOURCE_S3_PROVIDER="AWS"
TARGET_SOURCE_S3_BUCKET="my-app-data"
TARGET_SOURCE_S3_REGION="us-east-1"
TARGET_SOURCE_S3_ACCESS_KEY_ID="AKIA..."
TARGET_SOURCE_S3_SECRET_ACCESS_KEY="..."
TARGET_SOURCE_S3_ENDPOINT=""
TARGET_FOLDERS="/uploads,/media"
```

**S3 Provider** (`TARGET_SOURCE_S3_PROVIDER`): Controls the rclone provider setting for correct authentication and signing. Valid values:

| Value | Provider | Default Endpoint |
|---|---|---|
| `AWS` | Amazon S3 (default) | Uses AWS default |
| `Backblaze` | Backblaze B2 | `https://s3.us-west-004.backblazeb2.com` |
| `Wasabi` | Wasabi | `https://s3.wasabisys.com` |
| `Other` | Any S3-compatible | User-provided endpoint |

The web UI and TUI auto-fill the endpoint when selecting Backblaze or Wasabi. Adjust the region in the endpoint URL to match your bucket's region.

For other S3-compatible providers, set `S3_PROVIDER="Other"` and provide the endpoint:
```ini
TARGET_SOURCE_S3_PROVIDER="Other"
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

Shows all configured fields including source type details, MySQL settings, and PostgreSQL settings.

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
```

If `REMOTE_KEY` is not specified, it defaults to `~/.ssh/id_rsa`.

For password authentication:
```ini
REMOTE_AUTH_METHOD="password"
REMOTE_PASSWORD="your-password"
```

To use sudo for rsync on the destination (when the SSH user is not root but needs elevated privileges to write files):
```ini
REMOTE_SUDO="yes"
```

When enabled, gniza runs rsync via `sudo` on the remote destination, allowing a non-root SSH user to write backups to directories that require root access.

#### Local Destination

Store snapshots on a local drive (USB, NFS mount, second disk).

```ini
REMOTE_TYPE="local"
REMOTE_BASE="/mnt/backup-drive"
```

#### S3 Destination

Store snapshots in an S3 or S3-compatible bucket (AWS, Backblaze B2, Wasabi, or others).

```ini
REMOTE_TYPE="s3"
S3_PROVIDER="AWS"
S3_BUCKET="my-backups"
S3_ACCESS_KEY_ID="AKIA..."
S3_SECRET_ACCESS_KEY="..."
S3_REGION="us-east-1"
S3_ENDPOINT=""
REMOTE_BASE="/backups"
```

**S3 Provider** (`S3_PROVIDER`): Controls the rclone provider setting for correct authentication and signing. Valid values:

| Value | Provider | Default Endpoint |
|---|---|---|
| `AWS` | Amazon S3 (default) | Uses AWS default |
| `Backblaze` | Backblaze B2 | `https://s3.us-west-004.backblazeb2.com` |
| `Wasabi` | Wasabi | `https://s3.wasabisys.com` |
| `Other` | Any S3-compatible | User-provided endpoint |

The web UI and TUI auto-fill the endpoint when selecting Backblaze or Wasabi. Adjust the region in the endpoint URL to match your bucket's region.

**Backblaze B2 example**:

```ini
REMOTE_TYPE="s3"
S3_PROVIDER="Backblaze"
S3_BUCKET="my-b2-bucket"
S3_ACCESS_KEY_ID="your-key-id"
S3_SECRET_ACCESS_KEY="your-application-key"
S3_REGION="us-west-004"
S3_ENDPOINT="https://s3.us-west-004.backblazeb2.com"
REMOTE_BASE="/backups"
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
REMOTE_BASE="/backups"
```

Requires `rclone`.

#### Google Drive Destination

Store snapshots in Google Drive using a service account.

```ini
REMOTE_TYPE="gdrive"
GDRIVE_SERVICE_ACCOUNT_FILE="/path/to/service-account.json"
GDRIVE_ROOT_FOLDER_ID=""
REMOTE_BASE="/backups"
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
| `REMOTE_SUDO` | `no` | Use sudo rsync on destination (`yes` or `no`) |
| `REMOTE_BASE` | `/backups` | Base directory for snapshots |
| `BWLIMIT` | `0` | Bandwidth limit in KB/s (0 = unlimited) |

### Testing a Destination

```bash
gniza --cli destinations test --name=backup-server
```

Validates connectivity and configuration. For SSH destinations, tests the SSH connection. For S3/GDrive, verifies credentials and access.

### Test & Save

When creating or editing a destination in the TUI or web dashboard, the **Test & Save** button validates the connection before writing the config file. If the test fails, the config is not saved and an error message is shown.

| Type | What is tested |
|------|---------------|
| **Local** | Base directory can be accessed or created |
| **SSH** | SSH connection, create base directory, upload a validation file |
| **S3** | Credentials are present, bucket is accessible via `rclone lsd` |
| **Google Drive** | Service account file exists on disk, access is verified via `rclone lsd` |

### Checking Disk Usage

```bash
gniza --cli destinations disk-info-short --name=backup-server
```

Shows used/total space, free space, and usage percentage. Works with SSH and local destinations.

### Rclone Remotes Management

The web dashboard includes a Rclone Remotes page (`/rclone-config/`) for managing rclone remote configurations directly from the browser:

- **List** all configured rclone remotes
- **Create** new remotes (Google Drive with OAuth, S3, and other rclone-supported providers)
- **Edit** existing remote configurations
- **Delete** remotes
- **Test** remote connectivity

#### Google Drive OAuth (Remote Access)

When accessing the web dashboard from a non-localhost IP, Google Drive OAuth uses a "paste redirect URL" approach. Google blocks non-localhost redirect URIs for installed app client IDs, so the flow works as follows:

1. The user initiates Google Drive authentication from the web dashboard
2. Google's consent screen opens in a new tab
3. After authorizing, Google redirects to `127.0.0.1:53682` which shows an error page (since the dashboard is on a remote server)
4. The user copies the full URL from the browser's address bar
5. The user pastes the URL back into the gniza web dashboard to complete authentication

When accessing from localhost, OAuth works seamlessly with a direct redirect.

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

GNIZA uses rsync's `--link-dest` to create space-efficient incremental backups.

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

### Rsync Options

```ini
# Compression: no, zlib, zstd (rsync 3.2.3+ for zstd)
RSYNC_COMPRESS="zstd"

# Detect changes by content instead of mtime+size
RSYNC_CHECKSUM="no"
```

**Compression** reduces bandwidth but adds CPU overhead. zstd is ~3x faster than zlib at similar compression ratios. Most effective for text-heavy data (code, logs, SQL dumps) — has little effect on already-compressed files (images, videos, archives). Only applies to remote transfers — local transfers skip compression automatically.

**Checksum** uses file content checksums instead of modification time and size to detect changes. Slower but more accurate — useful after clock skew, filesystem migration, or when files are touched without content changes.

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

# Skip PostgreSQL restore
gniza --cli restore --source=mysite --destination=backup-server --skip-postgresql

# Skip both
gniza --cli restore --source=mysite --destination=backup-server --skip-mysql --skip-postgresql
```

### Restore Behavior

- **In-place restore**: Files are restored to their original locations, overwriting current files.
- **Custom directory restore**: Files are restored under the specified directory, preserving the original path structure.
- **MySQL restore**: If the snapshot contains MySQL dumps (`_mysql/` directory), they are automatically restored unless `--skip-mysql` is passed.
- **PostgreSQL restore**: If the snapshot contains PostgreSQL dumps (`_postgresql/` directory), they are automatically restored unless `--skip-postgresql` is passed.
- **Single folder restore**: Only the specified folder is restored from the snapshot.

### Restoring from TUI

Navigate to Restore, select a source, destination, and snapshot, choose in-place or custom directory, and optionally toggle MySQL and/or PostgreSQL restore on/off.

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
├── _mysql/                 # MySQL dumps (if enabled)
│   ├── dbname.sql.gz       # Gzip-compressed database dump
│   └── _grants.sql.gz      # User grants and privileges
└── _postgresql/            # PostgreSQL dumps (if enabled)
    ├── dbname.sql.gz       # Gzip-compressed database dump (pg_dump plain format)
    └── _roles.sql.gz       # Roles (pg_dumpall --roles-only)
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

Retention controls how many snapshots are kept per source per destination. When the number of snapshots exceeds the retention count, the oldest unpinned snapshots are automatically deleted.

### Configuration

Retention count is configured at two levels:

| Level | Location | Description |
|-------|----------|-------------|
| **Global default** | `gniza.conf` → `RETENTION_COUNT=30` | Applies to all backups unless overridden |
| **Per-schedule** | `schedules.d/<name>.conf` → `RETENTION_COUNT=N` | Overrides global for backups triggered by this schedule |

An empty or missing `RETENTION_COUNT` in a schedule means "use global default."

**Example — different retention per schedule:**

```ini
# schedules.d/hourly.conf — keep many recent snapshots
SCHEDULE="hourly"
TARGETS="web"
RETENTION_COUNT="168"    # 7 days × 24 hours

# schedules.d/daily.conf — keep fewer, longer-term snapshots
SCHEDULE="daily"
TARGETS="web"
RETENTION_COUNT="30"     # 30 days
```

The global default is set in `gniza.conf` or via the TUI/web Settings screen:

```ini
# gniza.conf
RETENTION_COUNT=30
```

### Automatic Enforcement

Retention runs automatically after each successful backup. The schedule's `RETENTION_COUNT` is used if set, otherwise the global default applies. Only unpinned snapshots are counted and deleted.

### Manual Enforcement

```bash
# Enforce retention for all sources on all destinations (uses global default)
gniza --cli retention --all

# Enforce for a specific source
gniza --cli retention --source=mysite

# Enforce on a specific destination
gniza --cli retention --destination=backup-server

# Override the retention count for this run
gniza --cli retention --source=mysite --count=10
```

### Snapshot Pinning

Pinned snapshots are never deleted by retention enforcement. Pin a snapshot by setting `"pinned": true` in its `meta.json` file. Pinned snapshots do not count toward the retention limit.

---

## Scheduling

GNIZA manages cron entries for automated backups.

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
RETENTION_COUNT=""              # Override global retention count (empty = use global default)
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

GNIZA can dump MySQL/MariaDB databases alongside file backups. Auto-detects `mysqldump` or `mariadb-dump`.

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

## PostgreSQL Backup

GNIZA can dump PostgreSQL databases alongside file backups using `pg_dump` (plain format) + gzip. Available for **local and SSH sources only** (not S3 or Google Drive).

### Enabling PostgreSQL Backup

In the source config:

```ini
TARGET_POSTGRESQL_ENABLED="yes"
TARGET_POSTGRESQL_USER="postgres"
TARGET_POSTGRESQL_PASSWORD="secret"
TARGET_POSTGRESQL_HOST="localhost"
TARGET_POSTGRESQL_PORT="5432"
```

Leave `TARGET_POSTGRESQL_USER` and `TARGET_POSTGRESQL_PASSWORD` empty to use peer authentication.

### Dump Modes

**All databases** (default):
```ini
TARGET_POSTGRESQL_MODE="all"
TARGET_POSTGRESQL_EXCLUDE="test_db,staging_db"
```

Dumps every user database except system databases (`template0`, `template1`, `postgres`) and any in the exclude list.

**Specific databases**:
```ini
TARGET_POSTGRESQL_MODE="specific"
TARGET_POSTGRESQL_DATABASES="app_db,user_db,analytics"
```

### Dump Options

```ini
TARGET_POSTGRESQL_EXTRA_OPTS="--no-owner --no-privileges"
```

Default options omit ownership and privilege statements for portable restores.

### What Gets Dumped

- Each database is dumped as `<dbname>.sql.gz` (pg_dump plain format, gzip compressed)
- Roles are dumped via `pg_dumpall --roles-only` as `_roles.sql.gz`
- All dumps are stored in the `_postgresql/` directory within the snapshot

### PostgreSQL Restore

During restore, PostgreSQL dumps from `_postgresql/` are automatically restored. Use `--skip-postgresql` to skip:

```bash
gniza --cli restore --source=mysite --destination=backup-server --skip-postgresql
```

In the TUI, toggle the "Restore PostgreSQL databases" switch.

---

## Notifications

GNIZA supports multi-channel notifications on backup completion. Configure one or more channels to receive alerts.

### Notification Channels

#### Email

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

If SMTP is not configured, gniza falls back to the system `mail` or `sendmail` command.

#### Telegram

```ini
TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
TELEGRAM_CHAT_ID="-1001234567890"
```

Create a bot via [@BotFather](https://t.me/BotFather), add it to your group, and set the chat ID.

#### Webhook (Slack / Discord / Generic)

```ini
WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../..."
WEBHOOK_TYPE="slack"            # slack | discord | generic
```

For Slack or Discord, use the incoming webhook URL. For generic webhooks, gniza sends a JSON POST with the notification payload.

#### ntfy

```ini
NTFY_URL="https://ntfy.sh/my-backup-alerts"
NTFY_TOKEN=""                   # Optional auth token
NTFY_PRIORITY=""                # Optional priority (1-5)
```

See [ntfy.sh](https://ntfy.sh/) for self-hosted or public usage.

#### Healthchecks.io

```ini
HEALTHCHECKS_URL="https://hc-ping.com/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

Pings the check URL on backup success, and signals failure on errors. See [healthchecks.io](https://healthchecks.io/).

### Stale Backup Alerts

```ini
STALE_ALERT_HOURS="48"          # Alert when a source hasn't backed up in 48 hours
```

When configured, gniza sends a notification if any source has not been backed up within the specified number of hours.

### Notification Modes

| Mode | When notifications are sent |
|------|---------------------|
| `never` | No notifications |
| `failure` | Only when a backup fails (default) |
| `always` | After every backup run |

### Notification Content

Notifications include:
- Status: SUCCESS, PARTIAL FAILURE, or FAILURE
- Source count: total, succeeded, failed
- Duration
- List of failed sources (if any)
- Log file path
- Hostname and timestamp

### Notification Log

All sent notifications are recorded in `notification.log` (5-column format). This replaces the old `email.log` file. The notification log viewer (`/notification-log/`) reads both `notification.log` and historical `email.log` entries.

### Test Notifications

Verify your notification settings by sending a test message to any configured channel:

**TUI**: Settings > Send Test Email (automatically saves settings first).

**CLI**:
```bash
gniza --cli test-notification email
gniza --cli test-notification telegram
gniza --cli test-notification webhook
gniza --cli test-notification ntfy
gniza --cli test-notification healthcheck
gniza --cli test-email                          # Alias for test-notification email
```

Each channel requires its corresponding settings to be configured (e.g., `SMTP_HOST` for email, `TELEGRAM_BOT_TOKEN` for Telegram).

---

## Web Dashboard

A full-featured web application for managing gniza from any browser. Built with Flask, Tailwind CSS, DaisyUI, and HTMX — all frontend assets loaded via CDN (no build step required).

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
WEB_USER="admin"                       # Login username
WEB_API_KEY="generated-during-install" # Login password
```

The password is generated automatically during installation if you enable the web dashboard. You can change it in Settings or directly in `gniza.conf`.

After changing web settings, restart the service:
```bash
systemctl --user restart gniza-web.service   # user mode
sudo systemctl restart gniza-web.service     # root mode
```

### Web Screens

All three interfaces (TUI, Web, CLI) maintain full feature parity:

| Screen | Description |
|--------|-------------|
| **Dashboard** | System stats (CPU, IO Wait, Memory, Swap, multi-partition Disks, Network bandwidth) with progress bars, plus sources, destinations, schedules tables, and last backup log with status |
| **Sources** | Create, edit, delete sources with toggle enable/disable (shows "Enabled"/"Disabled" text next to the toggle). Supports all source types (local, SSH, S3, Google Drive), MySQL backup, hooks, include/exclude filters |
| **Destinations** | Create, edit, delete destinations. Test connection (result shown as toast notification), view disk usage inline. Supports SSH, local, S3, Google Drive |
| **Schedules** | Create, edit, delete schedules with toggle active/inactive. Supports hourly, daily (multi-day), weekly, monthly, and custom cron |
| **Backup** | Select source and destination, or back up all. Starts a background job and redirects to Running Tasks |
| **Restore** | Select source, destination, and snapshot. Options for custom restore path, specific folder, and skip MySQL |
| **Running Tasks** | Live job list with status updates every 2 seconds. View log output, kill running jobs, clear finished jobs. Shows "Skipped" (yellow/warning) when all targets in a backup are disabled |
| **Snapshots** | Browse snapshots by source and destination. View file tree with HTMX-loaded directory expansion |
| **Retention** | Run retention cleanup per source or all. Edit default retention count |
| **Logs** | Paginated log viewer with status detection (success/error/skipped). View full log content |
| **Rclone Remotes** | Manage rclone remote configurations: list, create, edit, delete, and test remotes. Supports Google Drive OAuth and S3 providers |
| **Notification Log** | View all sent notifications from `notification.log` and historical `email.log` entries |
| **Settings** | Edit all global settings organized in sections: General, Notifications, SSH, Web. Send test notifications |

### Authentication

The web dashboard uses session-based authentication. Login with the username and password configured in `gniza.conf`. Sessions are secured with:

- Derived secret key (never stores password directly in session)
- Secure cookie flags (HttpOnly, SameSite=Lax)
- Session fixation protection on login

### Theme

The web dashboard supports dark and light themes. Toggle between them using the sun/moon icon in the top-right header. Theme preference is saved in the browser's local storage.

### Live Job Monitoring

Running tasks are polled every 2 seconds via HTMX. When a backup or restore process finishes, the status automatically updates to Success, Failed, Skipped, or Unknown. Finished processes are properly detected via zombie reaping before status checks. A backup is marked as "Skipped" when all its targets are disabled. Log files with content but no error markers are detected as successful. Job logs can be viewed inline with a single click.

### Folder Browser

The source and destination edit forms include a **Browse** button for selecting folders visually:

- **Local sources/destinations**: Browses the server's local filesystem
- **SSH sources**: Browses the remote server's filesystem over SSH (reads connection details from the form fields)

The browser uses a DaisyUI file tree with collapsible folders. Subdirectories are lazy-loaded via HTMX when you expand a folder. Click "Select" to pick the current path.

For SSH browsing, fill in the host, port, user, and key/password fields before clicking Browse. The browser connects to the remote server to list directories in real time.

### Mobile Access

The web dashboard is responsive and works on mobile browsers:
- Sidebar collapses into a hamburger menu on small screens
- Tables scroll horizontally on narrow viewports
- All forms and controls are touch-friendly

### Root vs User Mode

- **Root**: Installs as a system service (`/etc/systemd/system/gniza-web.service`)
- **User**: Installs as a user service (`~/.config/systemd/user/gniza-web.service`)

### Tech Stack

| Component | Purpose |
|-----------|---------|
| **Flask** | Python web framework, blueprint-based architecture |
| **Tailwind CSS** | Utility CSS framework (CDN) |
| **DaisyUI** | Tailwind component library with theme support (CDN) |
| **HTMX** | Dynamic HTML interactions, SSE log streaming (CDN) |
| **Alpine.js** | Lightweight JS for conditional form fields and state (CDN) |

---

## Background Daemon

The gniza daemon is a lightweight Python process that runs periodic health checks independently of the TUI and web dashboard.

### What It Does

| Task | Frequency | Description |
|------|-----------|-------------|
| **Dead job detection** | Every cycle | Detects running jobs whose process has died, updates status to success/failed/skipped/unknown |
| **Queue dispatch** | Every cycle | Starts queued jobs when slots are available (respects `MAX_CONCURRENT_JOBS`) |
| **Registry cleanup** | Every ~10 min | Removes finished job entries older than `LOG_RETAIN` days |
| **Log cleanup** | Every ~10 min | Deletes backup log files older than `LOG_RETAIN` days |
| **Orphan cleanup** | Every ~10 min | Removes unreferenced job log files older than 1 hour |

### Setup

```bash
# Install as a systemd service (recommended)
gniza daemon install-service

# Or start manually in foreground
gniza daemon start

# Custom check interval
gniza daemon start --interval=5
```

### Service Management

```bash
gniza daemon install-service       # Install and start systemd service
gniza daemon remove-service        # Stop and remove service
gniza daemon status                # Check service status
```

Supports both root (system service at `/etc/systemd/system/gniza-daemon.service`) and user (user service at `~/.config/systemd/user/gniza-daemon.service`) modes.

### Configuration

In `gniza.conf`:

```ini
DAEMON_INTERVAL=10             # Health check interval in seconds (default: 10, minimum: 1)
```

The daemon also uses these existing settings:
- `MAX_CONCURRENT_JOBS` — concurrency limit for queue dispatch
- `LOG_RETAIN` — days to keep log files and finished job entries

### Daemon Log

The daemon logs to `<log_dir>/gniza-daemon.log` with automatic rotation (5 MB max, 3 backups). In foreground mode (`--foreground`), logs go to the console instead.

### How It Works

The daemon shares the same job registry (`gniza-jobs.json`) as the TUI and web dashboard. All three use file locking to prevent concurrent write corruption. The daemon:

1. Reads the registry every cycle
2. For each "running" job, checks if the PID is still alive
3. If the process is dead, determines the exit code (via waitpid or log analysis) and updates the status
4. Starts queued jobs if under the concurrency limit
5. Periodically cleans up expired entries and old log files

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
| **Running Tasks** | Monitor active jobs with live log output and progress. Shows "skip" status when all targets are disabled |
| **Schedules** | Create and manage cron schedules, view last run time |
| **Snapshots** | Browse stored snapshots |
| **Logs** | View backup history with pagination. Shows "Skipped" status when all targets were disabled |
| **Settings** | Configure global options in organized sections |

### Navigation

Every screen has a **← Back** button in the top-left corner next to the screen title. Press `Escape` or click the button to return to the previous screen.

### Settings Screen

The Settings screen organizes options into four bordered sections:

| Section | Contents |
|---------|----------|
| **General** | Log level, log retention, retention count, bandwidth limit, disk threshold, rsync compression, rsync options |
| **Notifications** | Email (address, notify mode, SMTP settings), Telegram (bot token, chat ID), Webhook (URL, type), ntfy (URL, token, priority), Healthchecks.io (URL), stale alert hours, Send Test buttons |
| **SSH** | SSH timeout, SSH retries |
| **Web Dashboard** | Port, host, password |

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
gniza --cli restore --source=NAME --destination=NAME --skip-postgresql
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

### Background Daemon

```bash
gniza daemon start                                    # Start in foreground
gniza daemon start --interval=5                       # Custom interval
gniza daemon install-service                          # Install systemd service
gniza daemon remove-service                           # Remove service
gniza daemon status                                   # Check status
```

### Notifications

```bash
gniza --cli test-notification email                   # Test email notification
gniza --cli test-notification telegram                # Test Telegram notification
gniza --cli test-notification webhook                 # Test webhook notification
gniza --cli test-notification ntfy                    # Test ntfy notification
gniza --cli test-notification healthcheck             # Test Healthchecks.io ping
gniza --cli test-email                                # Alias for test-notification email
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
| `MAX_CONCURRENT_JOBS` | `1` | Max simultaneous jobs (0 = unlimited) |
| `DAEMON_INTERVAL` | `10` | Health daemon check interval in seconds |
| `RSYNC_COMPRESS` | `no` | Compression algorithm: no, zlib, zstd |
| `RSYNC_CHECKSUM` | `no` | Detect changes by content (--checksum) |
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
| `LOG_RETAIN` | `90` | Days to keep log files and completed job entries |

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
| `TELEGRAM_BOT_TOKEN` | (empty) | Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | (empty) | Telegram chat/group ID |
| `WEBHOOK_URL` | (empty) | Webhook endpoint URL |
| `WEBHOOK_TYPE` | (empty) | `slack`, `discord`, or `generic` |
| `NTFY_URL` | (empty) | ntfy topic URL |
| `NTFY_TOKEN` | (empty) | ntfy auth token (optional) |
| `NTFY_PRIORITY` | (empty) | ntfy priority 1-5 (optional) |
| `HEALTHCHECKS_URL` | (empty) | Healthchecks.io ping URL |
| `STALE_ALERT_HOURS` | (empty) | Alert when source not backed up in X hours |

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

### Feature Parity

GNIZA provides three interfaces: CLI, TUI, and Web. All three must offer the same capabilities. When adding or modifying a feature, update all three interfaces to keep them in sync.

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
- Check credentials in `gniza.conf` (`WEB_USER` and `WEB_API_KEY` / password)
