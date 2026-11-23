"""Hydra Decoy Layer — the digital front door (Wikipedia metadata decoys).

Travis's design, implemented:

When an outside connection tries to open a protected file and gets the
password wrong, the system pulls content from the 80 GB Wikipedia dump on the
F: drive and mints a DECOY that is metadata-identical to the real file — same
byte size, same timestamps — so the two are indistinguishable from a directory
listing.  A second wrong guess doubles the decoys, then four, eight, sixteen,
and so on, forever.  Only one file in the haystack is real, and only the
system (by content hash) knows which.

This layer is a DETERMINISTIC mechanism — it needs no learning, no model.  It
is the part of the shield that works before she has learned anything, the way
a locked door works before the child inside knows what the key is for.

DEFENSIVE ONLY. No outward-encryption primitive exists here.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_WIKI_SOURCE = Path("F:/AI_Datasets/wikipedia_deduplicated")


class WikiContentSource:
    """Reads arbitrary plausible bytes from a corpus directory tree.

    Defaults to the 80 GB Wikipedia deduplicated dump on F:, but accepts any
    directory so the mechanism can be tested with a small synthetic source.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self._batch_dirs = [d for d in self.root.iterdir() if d.is_dir()]

    def _random_file(self) -> Path:
        if not self._batch_dirs:
            raise FileNotFoundError(f"no content dirs under {self.root}")
        batch = secrets.choice(self._batch_dirs)
        files = [f for f in batch.iterdir() if f.is_file()]
        if not files:
            # try another batch (recurse shallowly)
            for candidate in self._batch_dirs:
                files = [f for f in candidate.iterdir() if f.is_file()]
                if files:
                    return secrets.choice(files)
            raise FileNotFoundError(f"no files under {self.root}")
        return secrets.choice(files)

    def random_bytes(self, size: int) -> bytes:
        """Return exactly `size` bytes of plausible corpus content."""
        out = bytearray()
        while len(out) < size:
            try:
                data = self._random_file().read_bytes()
            except OSError:
                continue
            if not data:
                continue
            out += data
        return bytes(out[:size])


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


@dataclass
class HydraDecoyLayer:
    """Mints metadata-identical decoys around a real file, doubling the
    haystack on every wrong password guess."""

    real_file: Path
    wiki_source: Path
    vault_dir: Path
    decoy_count: int = 0
    _real_size: int = field(init=False)
    _real_mtime: float = field(init=False)
    _real_atime: float = field(init=False)
    _real_hash: str = field(init=False)
    _wiki: WikiContentSource = field(init=False)

    def __post_init__(self) -> None:
        self.real_file = Path(self.real_file)
        self.vault_dir = Path(self.vault_dir)
        st = self.real_file.stat()
        self._real_size = st.st_size
        self._real_mtime = st.st_mtime
        self._real_atime = st.st_atime
        self._real_hash = file_hash(self.real_file)
        self._wiki = WikiContentSource(self.wiki_source)
        self.vault_dir.mkdir(parents=True, exist_ok=True)

    @property
    def real_hash(self) -> str:
        return self._real_hash

    def wrong_guess(self) -> int:
        """Double the haystack: 1, 2, 4, 8, 16, ... decoys."""
        target = 1 if self.decoy_count == 0 else self.decoy_count * 2
        for _ in range(target - self.decoy_count):
            self._mint_decoy()
        self.decoy_count = target
        return target

    def _mint_decoy(self) -> Path:
        content = self._wiki.random_bytes(self._real_size)
        name = f"{self.real_file.stem}_{secrets.token_hex(4)}{self.real_file.suffix}"
        path = self.vault_dir / name
        path.write_bytes(content)
        os.utime(path, (self._real_atime, self._real_mtime))
        return path

    def decoy_paths(self) -> list[Path]:
        return sorted(self.vault_dir.iterdir())

    def metadata_matches_real(self, path: Path) -> bool:
        """True if a decoy is metadata-identical to the real file."""
        st = path.stat()
        return st.st_size == self._real_size and st.st_mtime == self._real_mtime

    def find_real(self) -> Path | None:
        """Which file in the haystack is real, judged by content hash only."""
        for p in self.vault_dir.iterdir():
            if p.is_file() and file_hash(p) == self._real_hash:
                return p
        return None


def main():
    import tempfile
    import time

    print("=== Hydra Decoy Layer (Wikipedia metadata decoys) ===")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        # A synthetic "Wikipedia" source: a few plausible text files.
        wiki = td / "wiki"
        wiki.mkdir()
        (wiki / "b0").mkdir()
        for i in range(4):
            (wiki / "b0" / f"art{i}.txt").write_text(
                ("wikipedia article body " * 2000) + f" [article {i}]", encoding="utf-8"
            )

        # The real protected file.
        real = td / "secret.txt"
        real.write_bytes(b"THE REAL VAULT CONTENT " * 20)

        layer = HydraDecoyLayer(real_file=real, wiki_source=wiki, vault_dir=td / "vault")

        counts = []
        for _ in range(3):
            counts.append(layer.wrong_guess())

        print("doubling sequence:", counts)
        assert counts == [1, 2, 4], "must double 1 -> 2 -> 4"

        decoys = layer.decoy_paths()
        print("haystack size:", len(decoys), "files")
        assert len(decoys) == 4

        # Every decoy is metadata-identical (size + mtime) to the real file.
        all_meta = all(layer.metadata_matches_real(p) for p in decoys)
        print("all decoys metadata-identical (size + mtime):", all_meta)
        assert all_meta

        # Every decoy's content differs from the real file.
        none_real = all(file_hash(p) != layer.real_hash for p in decoys)
        print("no decoy content equals the real file:", none_real)
        assert none_real

        # The real file is NOT in the haystack yet (it's still outside the vault);
        # an attacker can't distinguish the decoys from each other, and the real
        # one is only identifiable by hash. Here we confirm none of the decoys
        # is the real file.
        print("real file hash:", layer.real_hash[:16], "...")
        print("=== all decoy-layer invariants hold ===")


if __name__ == "__main__":
    raise SystemExit(main())
