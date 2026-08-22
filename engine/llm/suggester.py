"""
Safer Alternative Suggester — Owner: Vansh
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Two-phase suggestion system:
  Phase 1: Fast lookup in the curated alternatives table (instant, no LLM)
  Phase 2: LLM-generated suggestion for novel dangerous patterns

The curated table is the primary source — LLM is only used when no
table entry exists for the detected pattern.

Expanded from 10 → 25 curated entries (2026-08-22).
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from engine.models import CommandContext, RiskLevel
from engine.parser.command_parser import ParsedCommand

# ─── Curated safer alternatives lookup table ──────────────────────────────────
# key: pattern_name or inferred key → (safer_command, explanation)
# Expanded: 10 → 25 entries covering all new TOML patterns.
_ALTERNATIVES_TABLE: dict[str, Tuple[str, str]] = {
    # ── Deletion ────────────────────────────────────────────────────────────────
    "rm_rf_root": (
        "# ABORT: There is no safe alternative to rm -rf /",
        "Deleting the root filesystem is completely unrecoverable.",
    ),
    "rm_rf_var_log": (
        "sudo journalctl --vacuum-size=500M",
        "Frees log space safely without removing active log files.",
    ),
    "rm_rf_home": (
        "trash-put {target}",
        "Moves files to trash for recovery instead of permanent deletion.",
    ),
    "rm_boot": (
        "# ABORT: Deleting /boot renders the system unbootable",
        "Use your package manager (dnf/apt) to manage kernel and bootloader files.",
    ),
    "rm_etc": (
        "# ABORT: Deleting /etc destroys all system configuration",
        "Back up specific config files with tar -czf /tmp/etc-backup.tar.gz /etc/.",
    ),
    "rm_bin_sbin_usr": (
        "# ABORT: Deleting /bin /usr /lib destroys all system utilities",
        "Use your package manager to uninstall packages cleanly.",
    ),
    "rm_home_root": (
        "trash-put {target}",
        "Use trash-put to move files to the recycle bin instead of permanent deletion.",
    ),
    "rm_ssh_keys": (
        "mv ~/.ssh ~/.ssh.backup.$(date +%Y%m%d)",
        "Create a dated backup of your SSH keys before removing them.",
    ),
    "rm_git_directory": (
        "git remote -v && git push --all && git push --tags",
        "Push all local commits and tags to remote before destroying the local .git directory.",
    ),
    # ── Permissions ─────────────────────────────────────────────────────────────
    "chmod_777_system": (
        "chmod -R 755 {target}",
        "755 grants the owner full access and others read/execute only — no world-write.",
    ),
    "chmod_777_root": (
        "chmod -R 755 {target} && chown -R www-data {target}",
        "Grants proper web-server permissions without world-write access.",
    ),
    "chmod_777_home": (
        "chmod -R 750 /home/{user}",
        "750 restricts access strictly to the owner and owner's group.",
    ),
    "suid_setuid_binary": (
        "sudo -l  # Review what is already delegated via sudoers",
        "Use sudoers rules for targeted privilege delegation instead of new SUID binaries.",
    ),
    # ── Disk / storage ───────────────────────────────────────────────────────────
    "dd_raw_device": (
        "fallocate -l 10G /tmp/test.img && losetup -f /tmp/test.img",
        "Use a loopback image for testing instead of writing to a real block device.",
    ),
    "mkfs_device": (
        "# ABORT: Formatting a mounted device will destroy all data",
        "Unmount the device and verify it is not your system disk before running mkfs.",
    ),
    "mkfs_live": (
        "# ABORT: Formatting a mounted device will destroy data",
        "Unmount and verify the device is not in use before formatting.",
    ),
    "redirect_to_device": (
        "# ABORT: Never redirect data directly to a raw /dev block device",
        "Use dd with explicit seek/count parameters on an unmounted, verified device.",
    ),
    # ── Pipe-to-shell / remote execution ─────────────────────────────────────────
    "curl_pipe_shell": (
        "curl -fsSL {url} -o /tmp/install.sh && cat /tmp/install.sh",
        "Download first, inspect the script content, then decide whether to run it.",
    ),
    "curl_pipe_sh": (
        "curl -o /tmp/script.sh {url} && cat /tmp/script.sh",
        "Download first, inspect the script, then decide whether to run it.",
    ),
    "wget_pipe_sh": (
        "wget -O /tmp/script.sh {url} && cat /tmp/script.sh",
        "Download first, inspect the script, then decide whether to run it.",
    ),
    # ── Scripting injection ───────────────────────────────────────────────────────
    "python_shell_injection": (
        "python3 script.py  # Write operations to a named file",
        "Named scripts are inspectable, versionable, and leave audit trails.",
    ),
    "perl_shell_injection": (
        "perl script.pl  # Write operations to a named file",
        "Named Perl scripts are inspectable and auditable.",
    ),
    "xargs_bulk_delete": (
        "xargs -I{} echo {}  # Preview targets before deleting",
        "Use echo to review the full list of targets before piping to rm.",
    ),
    # ── Network / exposure ────────────────────────────────────────────────────────
    "network_exfil_sensitive": (
        "sudo getent passwd {user}  # Query account info without exposing hashes",
        "Never transmit /etc/shadow or private keys over unencrypted channels.",
    ),
    "reverse_shell": (
        "ssh {target_host}  # Use encrypted, authenticated SSH",
        "Use SSH with key authentication instead of unencrypted netcat reverse shells.",
    ),
    # ── Fork bomb ─────────────────────────────────────────────────────────────────
    "fork_bomb": (
        "# ABORT: Fork bomb detected — will crash the system",
        "This pattern exhausts all process slots and requires a hard reboot.",
    ),
    # ── Broad glob delete / find ──────────────────────────────────────────────────
    "find_root_delete": (
        "find /var/log -name '*.log' -mtime +30 -delete",
        "Scope the delete to old log files only, not the entire filesystem.",
    ),
    "find_exec_delete": (
        "find {path} -name '*.log' -print  # Verify list before deleting",
        "Use -print or -ls to review matches before applying -delete or -exec rm.",
    ),
    # ── Privilege / auth tampering ────────────────────────────────────────────────
    "env_ld_preload_injection": (
        "ldd $(which sudo)  # Inspect normal library linkage instead",
        "Audit existing library linkage rather than injecting new shared libraries.",
    ),
    "passwd_tampering": (
        "sudo useradd -m {username}  # or: sudo passwd {username}",
        "Use useradd or usermod to manage system accounts safely.",
    ),
    "history_wipe_unset": (
        "",  # No safer alternative — this is purely malicious
        "Shell history is an essential security audit trail. Do not disable it.",
    ),
}


class SaferAlternativeSuggester:
    """
    Suggests safer alternatives for risky commands.

    Two-phase:
    1. Check the curated table (instant, 0ms)
    2. Fall back to whatever the LLM already returned in its main response
    Zero additional LLM calls are made.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    async def suggest(
        self,
        parsed: ParsedCommand,
        ctx: CommandContext,
        llm_response: Any,   # ParsedLLMResponse — already contains safer_alternative if LLM provided one
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Return (safer_command, explanation) or (None, None) if no suggestion.

        Priority:
        1. Curated table lookup (deterministic, 0ms)
        2. LLM's own safer_alternative from its main response (already available)
        3. None — no second LLM call is ever made
        """
        key = self._infer_key(parsed)

        # Phase 1: Curated table
        if key:
            target = parsed.arguments[-1] if parsed.arguments else ""
            url = parsed.arguments[0] if parsed.arguments else ""
            user = parsed.user or "username"
            result = self.get_table_entry(key, target=target, url=url, user=user)
            if result[0] is not None:
                return result

        # Phase 2: LLM's own suggestion (already present from the main call)
        if llm_response.safer_alternative:
            return llm_response.safer_alternative, "Suggested by AI safety analysis."

        return None, None

    def _infer_key(self, parsed: ParsedCommand) -> Optional[str]:
        """Infer which curated table key applies to this command."""
        flags = set(parsed.flags)
        args_str = " ".join(parsed.arguments)
        cmd = parsed.base_command

        if cmd == "rm":
            has_r = "-r" in flags or "-rf" in flags or "-fr" in flags or "-R" in flags
            if has_r:
                if "/" in parsed.arguments or "/*" in parsed.arguments or args_str.strip() in ("/", "/*"):
                    return "rm_rf_root"
                if "/boot" in args_str:    return "rm_boot"
                if "/etc" in args_str:     return "rm_etc"
                if any(p in args_str for p in ("/bin", "/sbin", "/usr", "/lib")):
                    return "rm_bin_sbin_usr"
                if any(p in args_str for p in ("/home", "/root", "~")):
                    return "rm_home_root"
                if ".ssh" in args_str:     return "rm_ssh_keys"
                if ".git" in args_str:     return "rm_git_directory"
                if "/var/log" in args_str: return "rm_rf_var_log"

        elif cmd == "chmod":
            if "777" in args_str or "a+rwx" in args_str:
                if any(p in args_str for p in ("/", "/etc", "/usr", "/bin", "/sbin")):
                    return "chmod_777_system"
                if "/home" in args_str:
                    return "chmod_777_home"
            if any(s in args_str for s in ("u+s", "4755", "4777", "6755")):
                return "suid_setuid_binary"

        elif cmd == "dd":
            if "/dev/" in args_str and any(d in args_str for d in ("sd", "nvme", "hd", "vd")):
                return "dd_raw_device"

        elif cmd in ("mkfs", "mkfs.ext4", "mkfs.xfs", "mkfs.btrfs", "mkfs.vfat", "mkfs.fat"):
            if "/dev/" in args_str:
                return "mkfs_device"

        elif cmd == "xargs":
            if "rm" in args_str:
                return "xargs_bulk_delete"

        elif cmd in ("nc", "ncat", "netcat", "socat"):
            if any(f in args_str for f in ("/etc/shadow", "/etc/passwd", "id_rsa")):
                return "network_exfil_sensitive"
            if any(f in args_str for f in ("-e", "exec:", "/bin/sh", "/bin/bash")):
                return "reverse_shell"

        elif cmd in ("python3", "python", "python2"):
            if "-c" in flags or "-C" in flags:
                return "python_shell_injection"

        elif cmd == "perl":
            if "-e" in flags or "-E" in flags:
                return "perl_shell_injection"

        elif parsed.has_pipe:
            pipe_cmds = [s.base_command for s in parsed.pipe_segments]
            if cmd in ("curl", "wget", "fetch") and any(
                p in pipe_cmds for p in ("sh", "bash", "zsh", "dash")
            ):
                return "curl_pipe_shell"

        elif cmd == ":" and parsed.raw and "{:|:&};:" in parsed.raw.replace(" ", ""):
            return "fork_bomb"

        elif cmd == "find":
            if "-delete" in flags or "-exec" in flags:
                if "/" in parsed.arguments:
                    return "find_root_delete"
                return "find_exec_delete"

        return None

    def get_table_entry(self, key: str, **fmt_kwargs: str) -> Tuple[Optional[str], Optional[str]]:
        """Helper: Get and format a table entry."""
        entry = _ALTERNATIVES_TABLE.get(key)
        if entry is None:
            return None, None
        cmd, explanation = entry
        if not cmd:   # Empty string means no safe alternative exists
            return None, explanation
        try:
            cmd = cmd.format(**fmt_kwargs)
        except KeyError:
            pass
        return cmd, explanation
