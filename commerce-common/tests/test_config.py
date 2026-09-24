# 项目中对应 commerce-common/tests/test_config.py

import pytest
from pydantic import ValidationError

from commerce_common.config import BaseAgentConfig


class RoleConfig(BaseAgentConfig):
    """按各包继承基类的方式写的角色配置：指定了 model，加了字段，没有别的配置。"""

    model: str = "test-model"
    role_only: int = 1


@pytest.mark.parametrize("config_class", [BaseAgentConfig, RoleConfig])
def test_an_unknown_field_name_fails_at_construction(config_class):
    with pytest.raises(ValidationError, match="no_such_setting"):
        config_class(model="test-model", no_such_setting="x")


def test_a_subclass_accepts_the_fields_it_adds():
    assert RoleConfig(brand_name="ACME", role_only=2).role_only == 2
