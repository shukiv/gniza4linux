"""Shared input validation for gniza."""
import re

# Entity names: targets, remotes, schedules
VALID_NAME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]{0,63}$')
