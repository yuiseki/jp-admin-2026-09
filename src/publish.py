#!/usr/bin/env python3
"""Push the fused table and its card to the Hugging Face Hub.

    python3 src/publish.py             # dry run
    python3 src/publish.py --push
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "yuiseki/jp-admin-2026-09"

CONFIGS = {
    "prefectures": "prefectures.parquet",
    "municipalities": "municipalities.parquet",
}
EXTRA = ["README.md", "LICENSE", "provenance.yaml"]


def md5(path):
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()

    card = (ROOT / "data" / "README.md").read_text(encoding="utf-8")
    for name, path in CONFIGS.items():
        if not re.search(r"^- config_name: %s$" % re.escape(name), card, re.M):
            raise SystemExit(f"the card declares no config named {name}")
        if not re.search(r"^  data_files: %s$" % re.escape(path), card, re.M):
            raise SystemExit(f"the card's data_files do not point at {path}")

    # The population total is the claim this dataset rests on, so the card has
    # to carry it and the files have to agree with it.
    import pyarrow.parquet as pq
    total = sum(
        r["population"] or 0
        for r in pq.read_table(ROOT / "data" / "municipalities.parquet",
                               columns=["population", "ward"]).to_pylist()
        if r["ward"] is None)
    if f"{total:,}" not in card:
        raise SystemExit(f"the card does not quote the population {total:,}")
    print(f"population {total:,} quoted on the card")

    files = list(CONFIGS.values()) + EXTRA
    size = 0
    for f in files:
        p = ROOT / "data" / f
        if not p.exists():
            raise SystemExit(f"missing {f}")
        size += p.stat().st_size
        if p.suffix == ".parquet":
            print(f"  {f:28} {p.stat().st_size:>12,}  {md5(p)}")
    print(f"{a.repo}\n  {len(files)} files, {size / 1e6:.1f} MB")

    if not a.push:
        print("\ndry run. pass --push to upload")
        return 0

    from huggingface_hub import HfApi
    api = HfApi()
    api.create_repo(a.repo, repo_type="dataset", exist_ok=True, private=False)
    api.upload_folder(folder_path=str(ROOT / "data"), repo_id=a.repo,
                      repo_type="dataset")
    print(f"\npushed to https://huggingface.co/datasets/{a.repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
