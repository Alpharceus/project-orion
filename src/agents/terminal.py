"""Terminal access with guardrails.

Three tiers: read-only commands on the allowlist run immediately, commands
matching the blocklist are denied outright, and everything else requires a
y/N confirmation typed at Orion's console (the model cannot answer that
prompt itself).
"""

import subprocess

from . import tool

SAFE_PREFIXES = (
    "dir", "echo", "type ", "where ", "whoami", "hostname", "systeminfo",
    "tasklist", "ipconfig", "ping ", "ver", "tree", "nvidia-smi",
    "git status", "git log", "python --version",
)

BLOCKED_FRAGMENTS = (
    "format ", "diskpart", "shutdown", "del /s", "del /f", "rd /s", "rmdir /s",
    "reg delete", "bcdedit", "cipher /w", "remove-item -recurse", "rm -rf",
)


@tool(
    "run_terminal_command",
    "Execute a Windows shell command on the user's PC and return its output. "
    "Read-only commands run immediately; anything that changes state will ask "
    "the user for confirmation first.",
    {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to run."}
        },
        "required": ["command"],
    },
)
def run_terminal_command(command: str) -> str:
    lowered = command.strip().lower()
    if any(fragment in lowered for fragment in BLOCKED_FRAGMENTS):
        return "Denied: that command is blocked by Orion's safety policy."
    if not lowered.startswith(SAFE_PREFIXES):
        # plain ASCII: this prompt must survive consoles that aren't UTF-8
        print(f"\n[!] Orion wants to run: {command}")
        if input("Allow? [y/N]: ").strip().lower() != "y":
            return "The user declined to run this command."
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
        return result.stdout if result.stdout else f"Success (No output). Error if any: {result.stderr}"
    except Exception as e:
        return f"Failed to execute command: {str(e)}"
