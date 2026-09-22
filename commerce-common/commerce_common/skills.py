"""技能加载。一个技能是一个包含 ``SKILL.md`` 的目录：YAML frontmatter 带
``name`` 和 ``description``，后面跟技能正文。静态提示词带索引目录，
``load_skill`` 按需返回正文。
"""
# 项目中对应 commerce-common/commerce_common/skills.py

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str


class SkillLoadError(ValueError):
    pass


def parse_skill_md(text: str, path: Path | None = None) -> Skill:
    if not text.startswith("---"):
        raise SkillLoadError(f"{path or 'SKILL.md'}：缺少 YAML frontmatter")
    try:
        _, frontmatter, body = text.split("---", 2)
    except ValueError as exc:
        raise SkillLoadError(f"{path or 'SKILL.md'}：frontmatter 的分隔线格式不对") from exc
    meta = yaml.safe_load(frontmatter) or {}
    name = meta.get("name")
    description = meta.get("description")
    if not name or not description:
        raise SkillLoadError(f"{path or 'SKILL.md'}：frontmatter 需要 name 和 description 两项")
    return Skill(name=str(name), description=str(description).strip(), body=body.strip())


def load_skill_dir(skill_dir: Path) -> Skill:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise SkillLoadError(f"{skill_dir}：没有找到 SKILL.md")
    return parse_skill_md(skill_md.read_text(encoding="utf-8"), path=skill_md)


def load_skills(skills_root: Path) -> list[Skill]:
    """``skills_root`` 下的所有技能目录；名称不能重复。"""
    skills = [
        load_skill_dir(child)
        for child in sorted(skills_root.iterdir())
        if child.is_dir() and (child / "SKILL.md").exists()
    ]
    names = [skill.name for skill in skills]
    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        raise SkillLoadError(f"技能名重复：{sorted(duplicates)}")
    return skills


class SkillRegistry:
    """加载好的技能集合，按名称排序，保证索引每次渲染出相同的字节。"""

    def __init__(self, skills: list[Skill]):
        self._skills = sorted(skills, key=lambda skill: skill.name)
        self._by_name = {skill.name: skill for skill in self._skills}

    @classmethod
    def from_dir(cls, skills_root: Path) -> SkillRegistry:
        return cls(load_skills(skills_root))

    @property
    def names(self) -> list[str]:
        return [skill.name for skill in self._skills]

    def index_block(self) -> str:
        if not self._skills:
            return "（未安装任何技能）"
        return "\n".join(f"- `{skill.name}` — {skill.description}" for skill in self._skills)

    def get_instructions(self, name: str) -> str | None:
        skill = self._by_name.get(name)
        return None if skill is None else skill.body
