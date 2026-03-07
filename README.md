# gniza - Linux Backup Manager

A generic Linux backup tool with a Python Textual TUI, web GUI, and CLI interface. Define named backup targets (sets of directories), configure remote destinations (SSH, local, S3, Google Drive), and run incremental backups with rsync `--link-dest` deduplication.

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

- **Target-based backups** - Define named profiles with sets of directories to back up
- **Include/exclude filters** - Rsync include or exclude patterns per target (comma-separated)
- **MySQL backup** - Dump all or selected databases alongside directory backups
- **Multiple remote types** - SSH, local (USB/NFS), S3, Google Drive
- **Incremental snapshots** - rsync `--link-dest` for space-efficient deduplication
- **Disk space safety** - Abort backup if remote disk usage exceeds configurable threshold (default 95%)
- **Textual TUI** - Beautiful terminal UI powered by [Textual](https://textual.textualize.io/)
- **Web dashboard** - Access the full TUI from any browser with HTTP Basic Auth
- **CLI interface** - Scriptable commands for automation and cron
- **Atomic snapshots** - `.partial` directory during backup, renamed on success
- **Retention policies** - Automatic pruning of old snapshots
- **Pre/post hooks** - Run custom commands before/after backups
- **Email notifications** - SMTP or system mail on success/failure
- **Root and user mode** - Works as root (system-wide) or regular user (per-user)
- **Cron scheduling** - Manage cron jobs through TUI or CLI

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

### Dependencies

- **Required**: bash 4+, rsync
- **Optional**: ssh, curl (SMTP notifications), rclone (S3/GDrive)
- **TUI/Web**: python3, textual, textual-serve (installed automatically)

## Quick Start

```bash
# Launch TUI
gniza

# Or use CLI
gniza targets add --name=mysite --folders=/var/www,/etc/nginx
gniza remotes add --name=backup-server    # (edit config manually)
gniza --cli backup --target=mysite
gniza --cli backup --all
```

## Usage

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
  restore           --target=NAME [--snapshot=TS] [--remote=NAME] [--dest=DIR]
  targets           list|add|delete|show [--name=NAME] [--folders=PATHS]
  remotes           list|add|delete|show|test|disk-info-short [--name=NAME]
  snapshots         list [--target=NAME] [--remote=NAME]
  retention         [--target=NAME] [--remote=NAME] [--all]
  schedule          install|show|remove
  logs              [--last] [--tail=N]
```

## Configuration

| Mode | Config | Logs | Lock |
|------|--------|------|------|
| Root | `/etc/gniza/` | `/var/log/gniza/` | `/var/run/gniza.lock` |
| User | `~/.config/gniza/` | `~/.local/state/gniza/log/` | `$XDG_RUNTIME_DIR/gniza-$UID.lock` |

Config subdirectories: `targets.d/*.conf`, `remotes.d/*.conf`, `schedules.d/*.conf`

### Target Config (`targets.d/mysite.conf`)

```ini
TARGET_NAME="mysite"
TARGET_FOLDERS="/var/www,/etc/nginx"
TARGET_EXCLUDE="*.log,*.tmp,.cache"
TARGET_INCLUDE=""
TARGET_REMOTE=""
TARGET_RETENTION=""
TARGET_PRE_HOOK=""
TARGET_POST_HOOK=""
TARGET_ENABLED="yes"

# MySQL backup (optional)
TARGET_MYSQL_ENABLED="no"
TARGET_MYSQL_MODE="all"
TARGET_MYSQL_DATABASES=""
TARGET_MYSQL_EXCLUDE=""
TARGET_MYSQL_USER=""
TARGET_MYSQL_PASSWORD=""
TARGET_MYSQL_HOST="localhost"
TARGET_MYSQL_PORT="3306"
TARGET_MYSQL_EXTRA_OPTS="--single-transaction --routines --triggers"
```

**Include vs Exclude**: Set `TARGET_INCLUDE` to back up only matching files (e.g. `*.conf,*.sh`). When include is set, everything else is excluded. If only `TARGET_EXCLUDE` is set, matching files are skipped. Patterns are comma-separated and support rsync glob syntax.

### Remote Config (`remotes.d/backup-server.conf`)

```ini
REMOTE_TYPE="ssh"
REMOTE_HOST="backup.example.com"
REMOTE_PORT=22
REMOTE_USER="root"
REMOTE_AUTH_METHOD="key"
REMOTE_KEY="/root/.ssh/backup_key"
REMOTE_BASE="/backups"
BWLIMIT=0
RETENTION_COUNT=30
```

For local remotes (USB/NFS):

```ini
REMOTE_TYPE="local"
REMOTE_BASE="/mnt/backup-drive"
```

## How Incremental Backups Work

GNIZA uses rsync's `--link-dest` option to create space-efficient incremental backups using **hardlinks**.

**The first backup** copies every file from source to destination. This takes the most time and disk space, since every file must be transferred in full. Depending on the size of your data and network speed, this initial backup may take a long time — this is normal.

**Every backup after the first** is significantly faster. Rsync compares each file against the previous snapshot. Files that haven't changed are not transferred again — instead, rsync creates a **hardlink** to the same data block on disk from the previous snapshot. Only new or modified files are actually copied.

This means:

- Each snapshot appears as a full, complete directory tree — you can browse or restore any snapshot independently.
- Unchanged files share disk space between snapshots through hardlinks, so 10 snapshots of 50 GB with only minor changes might use 55 GB total instead of 500 GB.
- Deleting an old snapshot only frees space for files that are not referenced by any other snapshot.
- Subsequent backups typically finish in seconds or minutes rather than hours, since only the differences are transferred.

> **Example**: A first backup of 20 GB takes 45 minutes over SSH. The next day, only 200 MB of files changed — the second backup takes under 2 minutes and uses only 200 MB of additional disk space, while still appearing as a complete 20 GB snapshot.

## Snapshot Structure

```
$BASE/<hostname>/targets/<target>/snapshots/<YYYY-MM-DDTHHMMSS>/
├── meta.json
├── manifest.txt
├── var/www/
├── etc/nginx/
└── _mysql/              # MySQL dumps (if enabled)
    ├── dbname.sql.gz
    └── _grants.sql.gz
```

## Web Dashboard

The TUI can be served in a browser via textual-serve with HTTP Basic Auth:

```bash
# Enable during install (generates admin password)
curl -sSL .../install.sh | sudo bash
# Answer "y" to "Enable web dashboard?"

# Or manually
gniza web install-service   # Install systemd service (port 2323)
gniza web start             # Start the service
gniza web stop              # Stop the service
```

Access at `http://<server-ip>:2323`. Credentials are stored in `gniza.conf` as `WEB_USER` and `WEB_API_KEY`.

## Testing

```bash
bash tests/test_utils.sh
bash tests/test_config.sh
bash tests/test_targets.sh
```

## License

MIT License - see [LICENSE](LICENSE) for details.
