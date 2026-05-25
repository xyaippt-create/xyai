from dataclasses import asdict, dataclass
from pathlib import Path

from engine.rulebook import PROJECT_ROOT, load_yaml_like


RULE_DIRECTORIES = (
    "rules",
    "ai_noise_rules",
    "material_rules",
    "visual_style_rules",
)


@dataclass(frozen=True)
class RuleDocument:
    """One source rule file normalized for the strategy interpreter."""

    category: str
    path: Path
    file_type: str
    data: dict | list | str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["path"] = str(self.path)
        return payload


@dataclass(frozen=True)
class RuleSet:
    """Unified visual rule object loaded from all rule libraries."""

    root: Path
    documents: tuple[RuleDocument, ...]

    def by_category(self, category: str) -> list[RuleDocument]:
        return [doc for doc in self.documents if doc.category == category]

    def source_paths(self) -> list[str]:
        return [str(doc.path) for doc in self.documents]

    def to_dict(self) -> dict:
        return {
            "root": str(self.root),
            "documents": [doc.to_dict() for doc in self.documents],
            "source_paths": self.source_paths(),
        }


def _load_markdown(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    headings = [
        line.strip("# ").strip()
        for line in text.splitlines()
        if line.startswith("#")
    ]
    return {
        "title": headings[0] if headings else path.stem,
        "headings": headings,
        "content": text,
    }


def _load_rule_file(category: str, path: Path) -> RuleDocument | None:
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return RuleDocument(category, path, "yaml", load_yaml_like(path))
    if suffix == ".md":
        return RuleDocument(category, path, "md", _load_markdown(path))
    return None


def load_visual_rules(project_root: str | Path | None = None) -> RuleSet:
    """Load yaml and markdown rules from every VisualMasterPro rule directory."""

    root = Path(project_root) if project_root else PROJECT_ROOT
    documents: list[RuleDocument] = []

    for category in RULE_DIRECTORIES:
        directory = root / category
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            document = _load_rule_file(category, path)
            if document:
                documents.append(document)

    return RuleSet(root=root, documents=tuple(documents))
