import json
import re
import subprocess
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "enterprise-attack.json"
DOCS_PATH = ROOT / "data" / "documents.json"
SIGMA_DIR = ROOT / "data" / "sigma"
SIGMA_URL = "https://github.com/SigmaHQ/sigma"
SOURCE_NAME = "SigmaHQ Sigma"
DOC_TYPE = "detection_rule"
SKIP_DIRS = {"deprecated", "unsupported", "ecs"}

_TECHNIQUE_TAG_RE = re.compile(r"^t\d{4}(\.\d{3})?$", re.IGNORECASE)


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


def extract_attack_mappings(tags):
    """Split a Sigma rule's `tags` into ATT&CK technique IDs (e.g. "attack.t1003.006"
    -> "T1003.006") and tactic slugs (e.g. "attack.credential-access"). Tags that
    aren't an "attack.*" mapping (CVEs, detection.* etc.) are left out of both --
    the full original list is kept separately in metadata for reference.
    """
    techniques = set()
    tactics = set()
    for tag in tags or []:
        if not isinstance(tag, str) or not tag.startswith("attack."):
            continue
        remainder = tag[len("attack.") :]
        if _TECHNIQUE_TAG_RE.match(remainder):
            techniques.add(remainder.upper())
        else:
            tactics.add(remainder)
    return sorted(techniques), sorted(tactics)


def build_content(rule, tags):
    parts = [rule["title"]]
    if rule.get("description"):
        parts.append(rule["description"])
    if tags:
        parts.append("Tags: " + ", ".join(tags))
    return "\n".join(parts)


def build_document(rule, path, raw):
    rule_id = rule.get("id") or f"sigma-{path.stem}"
    tags = rule.get("tags") if isinstance(rule.get("tags"), list) else []
    attack_techniques, attack_tactics = extract_attack_mappings(tags)

    return {
        "document_id": f"sigma:{rule_id}",
        "doc_type": DOC_TYPE,
        "source": {
            "name": SOURCE_NAME,
            "repo": SIGMA_URL,
            "path": str(path.relative_to(SIGMA_DIR)),
        },
        "title": rule["title"],
        "content": build_content(rule, tags),
        "metadata": {
            "rule_id": rule_id,
            "status": rule.get("status"),
            "level": rule.get("level"),
            "logsource": rule.get("logsource") or {},
            "attack_techniques": attack_techniques,
            "attack_tactics": attack_tactics,
            "tags": tags,
            "references": rule.get("references") or [],
            "author": rule.get("author"),
            "raw": raw,
        },
    }


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
        documents.append(build_document(rule, path, raw))
    return documents


def merge_documents():
    other_docs = []
    if DOCS_PATH.exists():
        existing = json.loads(DOCS_PATH.read_text(encoding="utf-8"))
        other_docs = [d for d in existing if d.get("doc_type") != DOC_TYPE]

    sigma_docs = parse_rules()
    documents = other_docs + sigma_docs
    documents.sort(key=lambda d: (d["doc_type"], d["document_id"]))

    with open(DOCS_PATH, "w", encoding="utf-8") as f:
        json.dump(documents, f, indent=2, ensure_ascii=False)
    return other_docs, sigma_docs


def main():
    ensure_sigma_rules()
    other_docs, sigma_docs = merge_documents()
    print(f"other docs: {len(other_docs)} | sigma docs: {len(sigma_docs)} | total: {len(other_docs) + len(sigma_docs)}")


if __name__ == "__main__":
    main()
