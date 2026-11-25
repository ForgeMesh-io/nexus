# Production key ceremony

Creates the production TUF root (2-of-3), the offline `targets` key and the online `snapshot`/`timestamp` keys. Performed by humans. **No AI agent generates, sees or handles production private keys.**

## Prerequisites

- Three root key holders (the founder plus two trusted people). Until two other people are available, the founder may hold all three keys on three separate devices, and must document that in `SECURITY.md`.
- Hardware: three hardware security keys supporting Ed25519 or ECDSA P-256 (e.g. YubiKey 5 with PIV), or three offline encrypted USB drives.
- An air-gapped computer booted from a live Linux image whose checksum was verified, with Python 3.12, `tuf` and `securesystemslib` installed from `docker/requirements.lock` (copied on read-only media).

## Steps

1. **Prepare**: boot the air-gapped machine. Copy a clone of `nexus` at a reviewed commit and of `registry`. Record both commit SHAs in the ceremony log.
2. **Generate root keys**: each holder generates their key on their own device (`ykman piv keys generate` or `CryptoSigner.generate_ed25519()` saved encrypted with a passphrase only that holder knows). Export the **public** keys only.
3. **Generate `targets`** (founder, offline) and **`snapshot`/`timestamp`** (online) keys the same way. The online keys will be stored as secrets of the `registry` repository's `online-keys` environment (restricted to `main`).
4. **Write `1.root.json`**: root threshold 2, three root keys; one key each for targets, snapshot, timestamp; expiry 1 year; `consistent_snapshot: true`; no `x-forgemesh.environment` field (production).
5. **Sign**: at least two holders sign `1.root.json` on the air-gapped machine.
6. **Delegate swarms**: the founder signs `targets.json` delegating `swarms/<name>/*` to each swarm key (public keys provided by the swarm key holders).
7. **Compute the anchor**: `sha256sum metadata/1.root.json`. Two people read it aloud and compare.
8. **Publish**: copy the metadata (never keys) out on read-only media, commit to `registry`, sign the commit. Update the anchor in: `registry/README.md`, `nexus/SECURITY.md`, the portal data. Announce in a pinned issue.
9. **Log**: date, participants, device serial numbers (kept private), commit SHAs, anchor. Store the signed log with the root keys.
10. **Destroy development keys** (`~/.forgemesh-dev-keys`) and the development registry history if desired: production clients will only ever see the new anchor.

## Rotation

Any root change produces `N+1.root.json` signed by the threshold of **both** the old and the new root keys. Clients that already trust version N follow the chain automatically; the anchor in prompts stays the hash of `1.root.json`.

Rotate immediately if a key is lost or suspected compromised. Rotate `timestamp`/`snapshot` keys at least yearly.

## Recovery

Losing one root key: rotate it out with the two remaining keys. Losing two: the registry must be re-founded with a new anchor and announced through every channel; old clients will refuse the new root (by design).
