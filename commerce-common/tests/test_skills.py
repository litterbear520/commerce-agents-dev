# 项目中对应 commerce-common/tests/test_skills.py

import pytest

from commerce_common.skills import (
    Skill,
    SkillLoadError,
    SkillRegistry,
    load_skill_dir,
    parse_skill_md,
)


@pytest.fixture
def skills() -> SkillRegistry:
    return SkillRegistry(
        [
            Skill(name="search-discovery", description="搜索与发现", body="# 搜索与发现\n测试正文"),
            Skill(name="planning-goals", description="目标规划", body="# 目标规划\n测试正文"),
        ]
    )


SKILL_MD = """---
name: search-discovery
description: 多约束搜索、短名单、比较流程。
---

# 搜索与发现

每个推荐都要有搜索结果支撑。
"""


def test_parse_skill_md_extracts_frontmatter_and_body():
    skill = parse_skill_md(SKILL_MD)
    assert skill.name == "search-discovery"
    assert skill.description.startswith("多约束搜索")
    assert skill.body.startswith("# 搜索与发现")


def test_parse_skill_md_requires_frontmatter():
    with pytest.raises(SkillLoadError):
        parse_skill_md("# no frontmatter here")
    with pytest.raises(SkillLoadError):
        parse_skill_md("---\nname: only-name\n---\nbody")


def test_load_skill_dir_serves_the_body_through_the_registry(tmp_path):
    skill_dir = tmp_path / "gift-finding"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: gift-finding\ndescription: 帮对方挑礼物。\n---\n这里是正文。"
    )
    registry = SkillRegistry([load_skill_dir(skill_dir)])
    assert registry.get_instructions("gift-finding") == "这里是正文。"


def test_registry_index_is_sorted_and_stable(skills):
    index_a = skills.index_block()
    index_b = skills.index_block()
    assert index_a == index_b
    assert index_a.index("planning-goals") < index_a.index("search-discovery")
    assert skills.get_instructions("nope") is None
