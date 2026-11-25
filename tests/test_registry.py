"""Registry trust tests against a real TUF repository on disk (no network)."""

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest
from tuf.api.exceptions import DownloadHTTPError
from tuf.ngclient import FetcherInterface

from forgemesh import registry as reg
from forgemesh.registry import Keyring, Repo, TrustError, fetch_verified, init_dev

MANIFEST = {"swarm": "nexus", "protocol": "1", "repository": "https://github.com/ForgeMesh-io/nexus"}


class FileFetcher(FetcherInterface):
    def __init__(self, root: Path):
        self.root = root

    def _fetch(self, url):
        p = self.root / urlparse(url).path.lstrip("/")
        if not p.exists():
            raise DownloadHTTPError(f"404 {url}", 404)
        yield p.read_bytes()


@pytest.fixture
def world(tmp_path):
    keys, server = tmp_path / "keys", tmp_path / "server"
    anchor = init_dev(server, keys, ["nexus", "vie", "orbis"])
    repo, kr = Repo(server), Keyring(keys)
    repo.add_target("nexus", "manifest.json", reg.dumps_manifest(MANIFEST), [kr.get("DEV-swarm-nexus")])
    repo.refresh(kr.get("DEV-snapshot"), kr.get("DEV-timestamp"))
    return {"repo": repo, "kr": kr, "anchor": anchor, "server": server, "tmp": tmp_path}


def get(w, swarm="nexus", name="manifest.json", cache="cache", anchor=None):
    fetcher = FileFetcher(w["server"])
    root_bytes = (w["server"] / "metadata" / "1.root.json").read_bytes()
    return fetch_verified("http://registry/metadata/", "http://registry/targets/", anchor or w["anchor"], swarm, name,
                          w["tmp"] / cache, fetcher=fetcher, root_bytes=root_bytes)


def test_valid_manifest_is_accepted(world):
    assert json.loads(get(world)) == MANIFEST


def test_wrong_anchor_stops_bootstrap(world):
    with pytest.raises(TrustError, match="trust anchor mismatch"):
        get(world, anchor="0" * 64)


def test_tampered_manifest_is_rejected(world):
    f = next((world["server"] / "targets" / "swarms" / "nexus").glob("*.manifest.json"))
    f.write_bytes(f.read_bytes().replace(b"ForgeMesh-io", b"evil-org"))
    with pytest.raises(TrustError):
        get(world)


def test_unsigned_target_is_rejected(world):
    with pytest.raises(TrustError, match="not signed"):
        get(world, name="other.json")


def test_swarm_cannot_sign_for_another_swarm(world):
    repo, kr = world["repo"], world["kr"]
    # The VIE key signs a file under swarms/nexus/: the delegation path restriction must reject it.
    md = repo.load("vie")
    from tuf.api.metadata import TargetFile
    md.signed.targets["swarms/nexus/evil.json"] = TargetFile.from_data("swarms/nexus/evil.json", b"{}", ["sha256"])
    md.signed.version += 1
    Repo.sign(md, [kr.get("DEV-swarm-vie")])
    repo.save(md, "vie")
    repo.refresh(kr.get("DEV-snapshot"), kr.get("DEV-timestamp"))
    with pytest.raises(TrustError, match="not signed"):
        get(world, name="evil.json")


def test_unknown_key_signature_is_rejected(world):
    repo = world["repo"]
    from securesystemslib.signer import CryptoSigner
    md = repo.load("nexus")
    md.signed.version += 1
    Repo.sign(md, [CryptoSigner.generate_ed25519()])
    repo.save(md, "nexus")
    repo.refresh(world["kr"].get("DEV-snapshot"), world["kr"].get("DEV-timestamp"))
    with pytest.raises(TrustError):
        get(world)


def test_expired_metadata_is_rejected(world):
    repo, kr = world["repo"], world["kr"]
    ts = repo.load("timestamp")
    ts.signed.expires = datetime.now(timezone.utc) - timedelta(minutes=1)
    ts.signed.version += 1
    Repo.sign(ts, [kr.get("DEV-timestamp")])
    repo.save(ts, "timestamp", versioned=False)
    with pytest.raises(TrustError, match="xpired"):
        get(world)


def test_rollback_to_old_metadata_is_rejected(world):
    old = (world["server"] / "metadata" / "timestamp.json").read_bytes()
    get(world)  # client now trusts the current timestamp
    repo, kr = world["repo"], world["kr"]
    repo.refresh(kr.get("DEV-snapshot"), kr.get("DEV-timestamp"))
    get(world)
    (world["server"] / "metadata" / "timestamp.json").write_bytes(old)  # attacker replays an older version
    with pytest.raises(TrustError):
        get(world)


def test_revoked_swarm_is_no_longer_trusted(world):
    repo, kr = world["repo"], world["kr"]
    get(world)
    repo.revoke_swarm("nexus", [kr.get("DEV-targets")])
    repo.refresh(kr.get("DEV-snapshot"), kr.get("DEV-timestamp"))
    with pytest.raises(TrustError, match="not signed"):
        get(world)


def test_root_rotation_with_threshold(world):
    repo, kr = world["repo"], world["kr"]
    root = repo.load("root")
    new_ts = kr.new("DEV-timestamp-2")
    for kid in list(root.signed.roles["timestamp"].keyids):
        root.signed.revoke_key(kid, "timestamp")
    root.signed.add_key(new_ts.public_key, "timestamp")
    root.signed.version += 1
    # One root signature is below the 2-of-3 threshold: clients must refuse the new root.
    Repo.sign(root, [kr.get("DEV-root-0")])
    for role in ("root",):
        repo.save(root, role)
    with pytest.raises(TrustError):
        get(world, cache="c1")
    # With two signatures (and the old root's threshold also met) the rotation is accepted.
    Repo.sign(root, [kr.get("DEV-root-0"), kr.get("DEV-root-2")])
    repo.save(root, "root")
    repo.refresh(kr.get("DEV-snapshot"), new_ts)
    assert json.loads(get(world, cache="c2")) == MANIFEST


def test_old_root_key_leak_cannot_forge_after_rotation(world):
    """Fixed bootstrap root still verifies the chain: a forged 2.root.json signed by one key fails."""
    repo, kr = world["repo"], world["kr"]
    from securesystemslib.signer import CryptoSigner
    evil = CryptoSigner.generate_ed25519()
    root = repo.load("root")
    root.signed.add_key(evil.public_key, "root")
    root.signed.version += 1
    Repo.sign(root, [kr.get("DEV-root-1"), evil])  # only one legitimate key
    repo.save(root, "root")
    with pytest.raises(TrustError):
        get(world, cache="c3")


def test_production_marker_absent_from_dev_root(world):
    root = json.loads((world["server"] / "metadata" / "1.root.json").read_text())
    assert root["signed"]["x-forgemesh"]["environment"] == "development"


def test_keys_are_not_written_inside_the_repository(world):
    assert not list(world["server"].rglob("*.pem"))
