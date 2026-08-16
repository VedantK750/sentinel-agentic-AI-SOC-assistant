import json
import subprocess
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "enterprise-attack.json"
DOCS_PATH = ROOT / "data" / "documents.json"
SIGMA_DIR = ROOT / "data" / "sigma"
SIGMA_URL = "https://github.com/SigmaHQ/sigma"
SIGMA_SOURCE = "SigmaHQ Sigma"
SKIP_DIRS = {"deprecated", "unsupported", "ecs"}


def ensure_sigma_rules():
    if SIGMA_DIR.exists() and (SIGMA_DIR / "rules").exists():
        return
    subprocess.run(
        ["git", "clone", "--depth", "1", SIGMA_URL, str(SIGMA_DIR)],
        check=True,
    )


def iter_rule_files():
    for path in (SIGMA_DIR / "rules").rglob("*.yml"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def parse_rules():
    documents = []
    for path in iter_rule_files():
        try:
            rule = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, UnicodeDecodeError, OSError):
            continue
        if not isinstance(rule, dict) or not rule.get("title"):
            continue
        if not rule.get("detection"):
            continue
        raw = yaml.dump(rule, sort_keys=False, allow_unicode=True)
        parts = [rule["title"]]
        if rule.get("description"):
            parts.append(rule["description"])
        tags = rule.get("tags")
        if isinstance(tags, list) and tags:
            parts.append("Tags: " + ", ".join(tags))
        documents.append(
            {
                "id": rule.get("id") or f"sigma-{path.stem}",
                "title": rule["title"],
                "content": "\n".join(parts),
                "raw": raw,
                "source": SIGMA_SOURCE,
            }
        )
    return documents


def merge_documents():
    mitre_docs = []
    if DOCS_PATH.exists():
        mitre_docs = json.loads(DOCS_PATH.read_text(encoding="utf-8"))
        mitre_docs = [d for d in mitre_docs if d.get("source") != SIGMA_SOURCE]

    sigma_docs = parse_rules()
    documents = mitre_docs + sigma_docs
    documents.sort(key=lambda d: (d["source"], d["id"]))

    with open(DOCS_PATH, "w", encoding="utf-8") as f:
        json.dump(documents, f, indent=2, ensure_ascii=False)
    return mitre_docs, sigma_docs


def main():
    ensure_sigma_rules()
    mitre_docs, sigma_docs = merge_documents()
    print(f"mitre docs: {len(mitre_docs)} | sigma docs: {len(sigma_docs)} | total: {len(mitre_docs) + len(sigma_docs)}")


if __name__ == "__main__":
    main()
