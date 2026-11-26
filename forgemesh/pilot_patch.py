"""Check an untrusted unified diff against the pinned commit inside Bubblewrap; nothing is executed from it."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .pilot import PilotError, valid_paths

# Only plain text edits of regular files: no mode, symlink, submodule, rename, copy or binary change.
FORBIDDEN = re.compile(r"^(old mode|new mode|rename |copy |similarity index|dissimilarity index|GIT binary patch"
                       r"|Binary files |(new file|deleted file) mode (?!100644$))", re.MULTILINE)


def sandboxed(command, *, binds=(), chdir="/tmp", timeout=120):
    """Run a trusted tool (git, tar) with no network, no home and a private /tmp; untrusted data is input only."""
    if not shutil.which("bwrap"):
        raise PilotError("sandbox_unavailable")
    args = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
            "--setenv", "PATH", "/usr/bin", "--setenv", "HOME", "/tmp", "--setenv", "GIT_CONFIG_NOSYSTEM", "1",
            "--setenv", "GIT_CEILING_DIRECTORIES", "/", "--setenv", "LC_ALL", "C",
            "--ro-bind", "/usr", "/usr", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for path in ("/lib", "/lib64", "/bin"):
        if os.path.islink(path):
            args += ["--symlink", os.readlink(path), path]
        elif os.path.isdir(path):
            args += ["--ro-bind", path, path]
    for source, target, writable in binds:
        args += ["--bind" if writable else "--ro-bind", str(source), target]
    try:
        return subprocess.run(args + ["--chdir", chdir, "--", *command], capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise PilotError("sandbox_unavailable") from None


def _covered(path, scopes):
    return any(path == scope or (scope.endswith("/") and path.startswith(scope)) for scope in scopes)


def check_patch(repository, base, paths, patch):
    """`repository` is an operator-owned local clone containing `base`; it is mounted read-only."""
    if not re.fullmatch(r"[0-9a-f]{40}", base) or not valid_paths(paths, 16) or not paths:
        raise PilotError("invalid_input")
    if FORBIDDEN.search(patch):
        return {"ok": False, "reason": "forbidden_change"}
    with tempfile.TemporaryDirectory(prefix="nexus-check-") as scratch:
        scratch = Path(scratch)
        (scratch / "work").mkdir()
        (scratch / "patch").write_text(patch, encoding="utf-8")
        binds = [(Path(repository).resolve(), "/repo", False), (scratch, "/scratch", True)]
        # The exact pinned tree, without .git, so the patch cannot reach repository metadata.
        extract = sandboxed(["sh", "-c", 'git -C /repo archive --format=tar -o /scratch/base.tar "$1" '
                             "&& tar -xf /scratch/base.tar -C /scratch/work && rm /scratch/base.tar", "sh", base],
                            binds=binds)
        if extract.returncode:
            raise PilotError("base_unavailable")
        listed = sandboxed(["git", "apply", "--numstat", "-z", "/scratch/patch"], binds=binds, chdir="/scratch/work")
        fields = listed.stdout.decode("utf-8", "replace").split("\0")[:-1] if not listed.returncode else []
        files = [field.split("\t", 2)[2] for field in fields if field.count("\t") >= 2]
        if not files or len(files) != len(fields):
            return {"ok": False, "reason": "does_not_apply"}
        if not valid_paths(files, 64) or any(".git" in file.split("/") for file in files):
            return {"ok": False, "reason": "forbidden_change"}
        if not all(_covered(file, paths) for file in files):
            return {"ok": False, "reason": "out_of_scope"}
        applies = sandboxed(["git", "apply", "--check", "/scratch/patch"], binds=binds, chdir="/scratch/work")
        if applies.returncode:
            return {"ok": False, "reason": "does_not_apply"}
        return {"ok": True, "files": sorted(set(files))}
