#!/usr/bin/env python3
"""Validate skill metadata, layout, internal references, and manifests."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REF_PATTERN = re.compile(r"`(references/[A-Za-z0-9_./-]+\.md)`")


def parse_frontmatter(lines: list[str]) -> dict[str, str] | None:
    if not lines or lines[0] != "---":
        return None
    end = None
    for i in range(1, len(lines)):
        if lines[i] == "---":
            end = i
            break
    if end is None:
        return None

    data: dict[str, str] = {}
    current_key: str | None = None
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t")) and ":" in line:
            key, value = line.split(":", 1)
            current_key = key.strip()
            value = value.strip()
            data[current_key] = "" if value in {">", ">-", "|", "|-"} else value.strip("\"'")
        elif current_key is not None:
            data[current_key] = (data[current_key] + " " + line.strip()).strip()
    return data


def validate_skill(skill_md: Path) -> list[str]:
    content = skill_md.read_text(encoding="utf-8")
    lines = content.splitlines()
    errors: list[str] = []
    skill_dir = skill_md.parent

    fm = parse_frontmatter(lines)
    if fm is None:
        return [f"{skill_md}: missing YAML frontmatter delimiters"]

    name = fm.get("name", "")
    description = fm.get("description", "")

    if not name:
        errors.append(f"{skill_md}: missing frontmatter 'name'")
    elif name != skill_dir.name:
        errors.append(
            f"{skill_md}: frontmatter name '{name}' does not match directory '{skill_dir.name}'"
        )

    if not description:
        errors.append(f"{skill_md}: missing frontmatter 'description'")
    elif description.upper() == "TODO":
        errors.append(f"{skill_md}: description still set to TODO")

    if not any(line.startswith("# ") for line in lines):
        errors.append(f"{skill_md}: missing top-level '# ' Markdown heading")

    # Check all referenced local files exist, and all reference files are reachable from SKILL.md.
    referenced_from_skill = set(REF_PATTERN.findall(content))
    for rel in sorted(referenced_from_skill):
        if not (skill_dir / rel).is_file():
            errors.append(f"{skill_md}: referenced file '{rel}' does not exist")

    refs_dir = skill_dir / "references"
    if refs_dir.is_dir():
        for ref_file in sorted(refs_dir.rglob("*.md")):
            rel = ref_file.relative_to(skill_dir).as_posix()
            if rel not in referenced_from_skill:
                errors.append(f"{ref_file}: not referenced from {skill_md.name}")
            ref_content = ref_file.read_text(encoding="utf-8")
            for nested in sorted(set(REF_PATTERN.findall(ref_content))):
                if not (skill_dir / nested).is_file():
                    errors.append(f"{ref_file}: referenced file '{nested}' does not exist")

    return errors


def validate_manifests(repo_root: Path, skill_names: set[str]) -> list[str]:
    errors: list[str] = []

    for rel in [
        "skills.sh.json",
        ".claude-plugin/plugin.json",
        ".claude-plugin/marketplace.json",
    ]:
        path = repo_root / rel
        if not path.is_file():
            errors.append(f"{rel}: missing manifest file")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{rel}: invalid JSON ({exc})")
            continue

        if rel == "skills.sh.json":
            listed = {
                skill
                for group in data.get("groupings", [])
                for skill in group.get("skills", [])
            }
            for missing in sorted(listed - skill_names):
                errors.append(f"{rel}: references unknown skill '{missing}'")
            for unlisted in sorted(skill_names - listed):
                errors.append(f"{rel}: skill '{unlisted}' is not listed in groupings")

    return errors


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    skills = sorted(repo_root.glob("*/SKILL.md"))

    if not skills:
        print("ERROR: No skills found (expected */SKILL.md)", file=sys.stderr)
        return 1

    errors: list[str] = []
    skill_names: set[str] = set()
    for skill_md in skills:
        skill_names.add(skill_md.parent.name)
        errors.extend(validate_skill(skill_md))

    errors.extend(validate_manifests(repo_root, skill_names))

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        print(
            f"Validation failed: {len(errors)} error(s) across {len(skills)} skill(s).",
            file=sys.stderr,
        )
        return 1

    print(f"Validation passed: {len(skills)} skill(s) checked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
