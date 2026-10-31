"""Fetch raw datasets into data/raw and record checksums in data/MANIFEST.json."""
import hashlib
import json
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    "maven": ("https://maven-datasets.s3.amazonaws.com/CRM+Sales+Opportunities/CRM+Sales+Opportunities.zip", "crm.zip"),
    "enron": ("https://www.cs.cmu.edu/~enron/enron_mail_20150507.tar.gz", "enron.tar.gz"),
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def main():
    manifest = {}
    for name, (url, filename) in SOURCES.items():
        path = ROOT / "data/raw" / name / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            print("downloading", name)
            part = path.with_suffix(".part")
            req = urllib.request.Request(url, headers={"User-Agent": "pipeline-pulse"})
            with urllib.request.urlopen(req) as r, open(part, "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            part.rename(path)
        if path.suffix == ".zip":
            zipfile.ZipFile(path).extractall(path.parent)
        manifest[name] = {"url": url, "file": filename, "sha256": sha256(path), "bytes": path.stat().st_size,
                          "downloaded": date.fromtimestamp(path.stat().st_mtime).isoformat()}
    (ROOT / "data/MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
