"""Prepare pinned upstream code and weights locally; never push upstream."""

import json
import hashlib
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def lock():
    return json.loads((ROOT / "config/kronos.lock.json").read_text(encoding="utf-8"))


def weight_hashes():
    return {f"{name}/{file}": hashlib.sha256((ROOT / "models" / name / file).read_bytes()).hexdigest()
            for name in ("model", "tokenizer") for file in ("config.json", "model.safetensors")}


def verify_source(source: Path, revision: str):
    head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    changes = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True).strip()
    if head != revision or changes:
        raise ValueError("Kronos source must match the pinned revision with a clean working tree")


def main():
    from huggingface_hub import snapshot_download
    pins = lock()
    source = ROOT / ".vendor/Kronos"
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--no-checkout", pins["source_url"], str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "checkout", "--detach", pins["source_revision"]], check=True)
    verify_source(source, pins["source_revision"])
    for name in ("model", "tokenizer"):
        snapshot_download(repo_id=pins[f"{name}_id"], revision=pins[f"{name}_revision"],
                          local_dir=ROOT / "models" / name,
                          allow_patterns=["config.json", "model.safetensors", "README.md", "LICENSE*"],
                          token=False)
    (ROOT / "models/prepared.json").write_text(json.dumps({"pins": pins, "sha256": weight_hashes()}, indent=2), encoding="utf-8")
    print("Pinned Kronos source and weights prepared locally. Upstream unchanged.")


if __name__ == "__main__":
    main()
