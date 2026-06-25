"""Procedure 仓储层单测：验证 ORM↔领域实体往返转换无损 + CRUD。"""
from __future__ import annotations

import pytest

from weldai.domain.enums import ProcedureType, WeldingProcess
from weldai.persistence import ProcedureRepository, get_session, init_db
from weldai.standards import get_default_standard


@pytest.fixture
def repo():
    """内存 SQLite + 默认标准的仓储。"""
    init_db(":memory:")
    session = get_session()
    return ProcedureRepository(session, get_default_standard())


def _sample_pqr():
    """构造一个含多种字段的 PQR 用于往返测试。"""
    from weldai.tests_demo import build_demo_pqr

    pqr = build_demo_pqr()
    pqr.remark = "测试备注"
    return pqr


def test_save_and_get_roundtrip(repo):
    """保存后取回，关键字段应无损。"""
    original = _sample_pqr()
    repo.save(original)

    loaded = repo.get("PQR-001")
    assert loaded is not None
    assert loaded.doc_no == "PQR-001"
    assert loaded.process == WeldingProcess.SMAW
    assert loaded.base_metals[0].metal.grade == "Q345R"
    assert loaded.base_metals[0].metal.group.group == "Fe-1-2"  # 从标准库重建
    assert loaded.base_metals[0].thickness == 16.0
    assert loaded.consumables[0].brand == "J507"
    assert loaded.consumables[0].classification_slot == "表2-E50"
    assert loaded.passes[0].layer_role == "打底"
    assert loaded.passes[0].current_type.value == "DCEP"
    assert loaded.joints[0].groove.type == "V"
    assert loaded.remark == "测试备注"


def test_update_existing(repo):
    """重复保存同一 doc_no 应更新而非重复插入。"""
    pqr = _sample_pqr()
    repo.save(pqr)
    pqr.impact_required = True
    pqr.remark = "已更新"
    repo.save(pqr)

    all_docs = repo.list_all()
    assert len(all_docs) == 1  # 未重复
    loaded = repo.get("PQR-001")
    assert loaded.impact_required is True
    assert loaded.remark == "已更新"


def test_list_filter_by_type(repo):
    """list_all 可按类型过滤。"""
    from weldai.tests_demo import build_demo_wps

    repo.save(_sample_pqr())  # PQR
    wps = build_demo_wps()
    repo.save(wps)

    pqrs = repo.list_all(ProcedureType.PQR)
    wps_list = repo.list_all(ProcedureType.WPS)
    assert len(pqrs) == 1
    assert pqrs[0].doc_no == "PQR-001"
    assert len(wps_list) == 1
    assert wps_list[0].doc_no == "WPS-001"


def test_delete(repo):
    repo.save(_sample_pqr())
    assert repo.delete("PQR-001") is True
    assert repo.get("PQR-001") is None
    assert repo.delete("PQR-001") is False  # 已删除


def test_unknown_grade_fallback(repo):
    """母材牌号不在标准库时，应保留牌号不报错（类组号未知）。"""
    from weldai.tests_demo import make_q345r
    from weldai.domain.base_metal import BaseMetalThicknessPair

    pqr = _sample_pqr()
    pqr.doc_no = "PQR-X"
    # 强制一个不在库的牌号
    metal = make_q345r()
    metal.grade = "UNKNOWN-GRADE"
    pqr.base_metals = [BaseMetalThicknessPair(metal, 12.0)]
    repo.save(pqr)

    loaded = repo.get("PQR-X")
    assert loaded.base_metals[0].metal.grade == "UNKNOWN-GRADE"
    assert loaded.base_metals[0].thickness == 12.0
