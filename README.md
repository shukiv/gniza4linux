# gniza - Linux Backup Manager

A generic Linux backup tool with a Gum TUI and CLI interface. Define named backup targets (sets of directories), configure remote destinations (SSH, local, S3, Google Drive), and run incremental backups with rsync `--link-dest` deduplication.

```
  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓          ▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓

  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓          ▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓

  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓          ▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
               ▓▓▓▓▓▓▓
                ▓▓▓▓▓
                  ▓▓
```

## Features

- **Target-based backups** - Define named profiles with sets of directories to back up
- **Multiple remote types** - SSH, local (USB/NFS), S3, Google Drive
- **Incremental snapshots** - rsync `--link-dest` for space-efficient deduplication
- **Gum TUI** - Beautiful terminal UI powered by [gum](https://github.com/charmbracelet/gum)
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
- **Optional**: ssh, [gum](https://github.com/charmbracelet/gum) (TUI), curl (SMTP notifications), rclone (S3/GDrive)

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
  remotes           list|add|delete|show|test [--name=NAME]
  snapshots         list [--target=NAME] [--remote=NAME]
  verify            [--target=NAME] [--remote=NAME] [--all]
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
TARGET_EXCLUDE="*.log,*.tmp"
TARGET_REMOTE=""
TARGET_RETENTION=""
TARGET_PRE_HOOK=""
TARGET_POST_HOOK=""
TARGET_ENABLED="yes"
```

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

## Snapshot Structure

```
$BASE/<hostname>/targets/<target>/snapshots/<YYYY-MM-DDTHHMMSS>/
├── meta.json
├── manifest.txt
├── var/www/
└── etc/nginx/
```

## Testing

```bash
bash tests/test_utils.sh
bash tests/test_config.sh
bash tests/test_targets.sh
```

## License

MIT License - see [LICENSE](LICENSE) for details.
