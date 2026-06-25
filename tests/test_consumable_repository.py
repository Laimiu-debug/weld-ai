"""ConsumableRepository 与焊材库查询单测。

验证：CRUD 往返、price/processes 字段持久化、consumables_for_process 过滤、
Consumable.applicable_processes 回退推断。
"""
from __future__ import annotations

import pytest

from weldai.domain.consumable import Consumable, ConsumableType
from weldai.domain.enums import WeldingProcess
from weldai.persistence import ConsumableRepository, get_session, init_db
from weldai.standards import get_default_standard


@pytest.fixture
def repo():
    init_db(":memory:")
    return ConsumableRepository(get_session())


def _wire():
    return Consumable(
        brand="TEST-ER50", model="ER50-6", type=ConsumableType.WIRE,
        classification_slot="表3-ER50-6", standard="GB/T 8110",
        diameter=1.2, price=7.5, processes=["GTAW", "GMAW"],
        applicable_groups=["Fe-1-1"],
    )


# ---------------------------------------------------------------------------
# CRUD 往返
# ---------------------------------------------------------------------------

def test_save_and_get_roundtrip(repo):
    c = _wire()
    repo.save(c)
    got = repo.get("TEST-ER50")
    assert got is not None
    assert got.model == "ER50-6"
    assert got.type == ConsumableType.WIRE
    assert got.price == 7.5
    assert got.processes == ["GTAW", "GMAW"]
    assert got.diameter == 1.2


def test_list_all(repo):
    repo.save(_wire())
    repo.save(Consumable(brand="TEST-J507", model="E5015",
                         type=ConsumableType.ELECTRODE, classification_slot="表2-E50",
                         price=12.0, processes=["SMAW"]))
    all_cons = repo.list_all()
    brands = {c.brand for c in all_cons}
    assert "TEST-ER50" in brands
    assert "TEST-J507" in brands


def test_delete(repo):
    repo.save(_wire())
    assert repo.delete("TEST-ER50") is True
    assert repo.get("TEST-ER50") is None
    # 再次删除返回 False
    assert repo.delete("TEST-ER50") is False


def test_save_overwrites_same_brand(repo):
    repo.save(Consumable(brand="DUP", model="M1", type=ConsumableType.WIRE,
                         classification_slot="表3", price=5.0))
    repo.save(Consumable(brand="DUP", model="M2", type=ConsumableType.WIRE,
                         classification_slot="表3", price=9.0))
    got = repo.get("DUP")
    assert got.model == "M2"
    assert got.price == 9.0
    assert len([c for c in repo.list_all() if c.brand == "DUP"]) == 1


# ---------------------------------------------------------------------------
# 适用方法回退推断
# ---------------------------------------------------------------------------

def test_applicable_processes_explicit():
    c = Consumable(brand="X", model="M", type=ConsumableType.WIRE,
                   classification_slot="表3", processes=["GTAW"])
    assert c.applicable_processes() == ["GTAW"]


def test_applicable_processes_fallback_by_type():
    """processes 为空时按 type 回退：electrode→SMAW、wire→GTAW/GMAW/FCAW。"""
    electrode = Consumable(brand="E", model="M", type=ConsumableType.ELECTRODE,
                           classification_slot="表2")
    wire = Consumable(brand="W", model="M", type=ConsumableType.WIRE,
                      classification_slot="表3")
    assert electrode.applicable_processes() == ["SMAW"]
    assert set(wire.applicable_processes()) == {"GTAW", "GMAW", "FCAW"}


# ---------------------------------------------------------------------------
# consumables_for_process 过滤（合并内置+用户自定义）
# ---------------------------------------------------------------------------

def test_consumables_for_process_filters_correctly():
    """内置焊材应按焊接方法正确过滤：焊条→SMAW、焊丝→GTAW/GMAW。"""
    init_db(":memory:")
    std = get_default_standard()
    smaw = std.consumables_for_process(WeldingProcess.SMAW)
    gtaw = std.consumables_for_process(WeldingProcess.GTAW)
    # SMAW 应全是焊条类型
    assert all(c.type == ConsumableType.ELECTRODE for c in smaw), "SMAW焊材应全为焊条"
    # GTAW 应含焊丝类型
    assert any(c.type == ConsumableType.WIRE for c in gtaw), "GTAW焊材应含焊丝"
    # 接受字符串形式
    smaw_str = std.consumables_for_process("SMAW")
    assert len(smaw_str) == len(smaw)


def test_custom_consumable_visible_after_add():
    """用户添加的自定义焊材应在 profile 查询中立即可见。"""
    init_db(":memory:")
    repo = ConsumableRepository(get_session())
    repo.save(Consumable(brand="UNIQUE-CUSTOM", model="M", type=ConsumableType.WIRE,
                         classification_slot="表3", price=6.0, processes=["GMAW"]))
    std = get_default_standard()
    # all_consumables 应含自定义
    assert std.get_consumable("UNIQUE-CUSTOM") is not None
    # consumables_for_process("GMAW") 应含它
    gmaw = [c.brand for c in std.consumables_for_process("GMAW")]
    assert "UNIQUE-CUSTOM" in gmaw
