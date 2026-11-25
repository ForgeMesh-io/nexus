"""TUF-based official registry of swarms.

Roles
    root       offline, threshold 2-of-3 in production; delegates the other roles
    targets    offline (founder); delegates one role per swarm
    snapshot   online (CI) — short expiry
    timestamp  online (CI) — very short expiry
    <swarm>    delegated role, may only sign files under ``swarms/<swarm>/``

Bootstrap: the participant's prompt contains the SHA-256 of ``1.root.json``. The
client checks that hash before giving the file to python-tuf, which then handles
root rotation, rollback/freeze protection, expiry and delegations.

``init_dev`` creates a DEVELOPMENT repository with throw-away keys. Production keys
are created by the founder following docs/KEY_CEREMONY.md, never by an agent.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from securesystemslib.signer import CryptoSigner
from tuf.api.metadata import (DelegatedRole, Delegations, Metadata, MetaFile, Root, Snapshot, TargetFile, Targets,
                              Timestamp)
from tuf.api.serialization.json import JSONSerializer

SER = JSONSerializer(compact=False)
EXPIRY = {"root": 365, "targets": 180, "snapshot": 7, "timestamp": 2, "swarm": 90}


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _exp(role: str, now=None):
    return (now or _now()) + timedelta(days=EXPIRY.get(role, EXPIRY["swarm"]))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Keyring:
    """Private keys for development. Stored outside the repository, never committed."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)

    def new(self, name: str) -> CryptoSigner:
        signer = CryptoSigner.generate_ed25519()
        f = self.path / f"{name}.pem"
        f.write_bytes(signer.private_bytes)
        f.chmod(0o600)
        return signer

    def get(self, name: str) -> CryptoSigner:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        return CryptoSigner(load_pem_private_key((self.path / f"{name}.pem").read_bytes(), None))


class Repo:
    """Filesystem TUF repository: ``metadata/`` and ``targets/`` (consistent snapshots)."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.meta = self.root / "metadata"
        self.targets_dir = self.root / "targets"

    def load(self, role: str) -> Metadata:
        return Metadata.from_file(str(self.meta / f"{role}.json"))

    def save(self, md: Metadata, role: str, versioned: bool = True) -> None:
        self.meta.mkdir(parents=True, exist_ok=True)
        data = md.to_bytes(SER)
        (self.meta / f"{role}.json").write_bytes(data)
        if versioned:
            (self.meta / f"{md.signed.version}.{role}.json").write_bytes(data)

    @staticmethod
    def sign(md: Metadata, signers) -> None:
        md.signatures.clear()
        for s in signers:
            md.sign(s, append=True)

    # -- online roles (CI) ------------------------------------------------
    def refresh(self, snapshot_signer, timestamp_signer) -> None:
        snap = self.load("snapshot")
        snap.signed.meta["targets.json"] = MetaFile(self.load("targets").signed.version)
        for role in self.load("targets").signed.delegations.roles:
            p = self.meta / f"{role}.json"
            if p.exists():
                snap.signed.meta[f"{role}.json"] = MetaFile(self.load(role).signed.version)
        # Unix-time versions stay monotonic even when CI re-signs without committing the previous output.
        stamp = int(_now().timestamp())
        snap.signed.version = max(snap.signed.version + 1, stamp)
        snap.signed.expires = _exp("snapshot")
        self.sign(snap, [snapshot_signer])
        self.save(snap, "snapshot")
        ts = self.load("timestamp")
        ts.signed.snapshot_meta = MetaFile(snap.signed.version)
        ts.signed.version = max(ts.signed.version + 1, stamp)
        ts.signed.expires = _exp("timestamp")
        self.sign(ts, [timestamp_signer])
        self.save(ts, "timestamp", versioned=False)

    # -- swarm role -------------------------------------------------------
    def add_target(self, swarm: str, name: str, data: bytes, signers) -> None:
        if "/" in name or name.startswith("."):
            raise ValueError("target name must be a plain file name")
        path = f"swarms/{swarm}/{name}"
        md = self.load(swarm)
        tf = TargetFile.from_data(path, data, ["sha256"])
        md.signed.targets[path] = tf
        md.signed.version += 1
        md.signed.expires = _exp("swarm")
        self.sign(md, signers)
        self.save(md, swarm)
        out = self.targets_dir / "swarms" / swarm
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{tf.hashes['sha256']}.{name}").write_bytes(data)  # consistent snapshot naming

    # -- founder operations (offline keys) ---------------------------------
    def delegate_swarm(self, swarm: str, swarm_keys, threshold: int, targets_signers) -> None:
        md = self.load("targets")
        d = md.signed.delegations or Delegations(keys={}, roles={})
        for k in swarm_keys:
            d.keys[k.keyid] = k
        d.roles[swarm] = DelegatedRole(name=swarm, keyids=[k.keyid for k in swarm_keys], threshold=threshold,
                                       terminating=True, paths=[f"swarms/{swarm}/*"])
        md.signed.delegations = d
        md.signed.version += 1
        md.signed.expires = _exp("targets")
        self.sign(md, targets_signers)
        self.save(md, "targets")

    def revoke_swarm(self, swarm: str, targets_signers) -> None:
        md = self.load("targets")
        role = md.signed.delegations.roles.pop(swarm)
        still_used = {k for r in md.signed.delegations.roles.values() for k in r.keyids}
        for k in role.keyids:
            if k not in still_used:
                md.signed.delegations.keys.pop(k, None)
        md.signed.version += 1
        md.signed.expires = _exp("targets")
        self.sign(md, targets_signers)
        self.save(md, "targets")


def init_dev(repo_dir: Path, keys_dir: Path, swarms: list[str]) -> str:
    """Create a development registry. Returns the SHA-256 of 1.root.json (the trust anchor)."""
    repo, kr = Repo(repo_dir), Keyring(keys_dir)
    if repo.meta.exists():
        shutil.rmtree(repo.meta)
    roots = [kr.new(f"DEV-root-{i}") for i in range(3)]
    online = {r: kr.new(f"DEV-{r}") for r in ("targets", "snapshot", "timestamp")}
    root = Root(expires=_exp("root"), consistent_snapshot=True)
    for s in roots:
        root.add_key(s.public_key, "root")
    root.roles["root"].threshold = 2
    for r, s in online.items():
        root.add_key(s.public_key, r)
    root.unrecognized_fields["x-forgemesh"] = {"environment": "development", "warning": "DEVELOPMENT KEYS - NOT TRUSTED IN PRODUCTION"}
    md = Metadata(root)
    Repo.sign(md, roots[:2])
    repo.save(md, "root")
    t = Metadata(Targets(expires=_exp("targets")))
    Repo.sign(t, [online["targets"]])
    repo.save(t, "targets")
    snap = Metadata(Snapshot(expires=_exp("snapshot")))
    repo.save(snap, "snapshot", versioned=False)  # unsigned placeholder, signed by refresh() below
    ts = Metadata(Timestamp(expires=_exp("timestamp")))
    repo.save(ts, "timestamp", versioned=False)
    for sw in swarms:
        k = kr.new(f"DEV-swarm-{sw}")
        repo.delegate_swarm(sw, [k.public_key], 1, [online["targets"]])
        md = Metadata(Targets(expires=_exp("swarm")))
        Repo.sign(md, [k])
        repo.save(md, sw)
    repo.refresh(online["snapshot"], online["timestamp"])
    return sha256_file(repo.meta / "1.root.json")


# ---- client side --------------------------------------------------------

class TrustError(Exception):
    pass


def verify_anchor(root_bytes: bytes, expected_sha256: str) -> None:
    got = hashlib.sha256(root_bytes).hexdigest()
    if got != expected_sha256.lower():
        raise TrustError(f"trust anchor mismatch: expected {expected_sha256}, got {got}. STOP: do not continue.")


def fetch_verified(metadata_url: str, targets_url: str, anchor_sha256: str, swarm: str, name: str,
                   cache: Path, fetcher=None, root_bytes: bytes | None = None) -> bytes:
    """Download ``swarms/<swarm>/<name>`` and return its bytes only if fully verified by TUF."""
    from tuf.ngclient import Updater
    cache = Path(cache)
    meta_dir = cache / "metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)
    trusted = meta_dir / "root.json"
    if not trusted.exists():
        if root_bytes is None:
            import urllib.request
            try:
                with urllib.request.urlopen(f"{metadata_url.rstrip('/')}/1.root.json", timeout=60) as r:
                    root_bytes = r.read()
            except OSError as e:  # URLError/HTTPError are OSError subclasses
                raise TrustError(f"cannot download 1.root.json: {e}") from None
        verify_anchor(root_bytes, anchor_sha256)
        trusted.write_bytes(root_bytes)
    up = Updater(metadata_dir=str(meta_dir), metadata_base_url=metadata_url, target_dir=str(cache / "targets"),
                 target_base_url=targets_url, fetcher=fetcher, bootstrap=None)
    try:
        up.refresh()
        info = up.get_targetinfo(f"swarms/{swarm}/{name}")
        if info is None:
            raise TrustError(f"swarms/{swarm}/{name} is not signed by the official registry")
        (cache / "targets").mkdir(parents=True, exist_ok=True)
        path = up.find_cached_target(info) or up.download_target(info)
    except TrustError:
        raise
    except Exception as e:  # any TUF failure is a trust failure
        raise TrustError(f"{type(e).__name__}: {e}") from None
    return Path(path).read_bytes()


def dumps_manifest(manifest: dict) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
