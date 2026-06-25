"""批量管理服务单测。"""
from __future__ import annotations

import pytest

from weldai.domain.enums import ProcedureType
from weldai.services import BatchService
from weldai.persistence import ProcedureRepository, get_session, init_db
from weldai.standards import get_default_standard


@pytest.fixture
def batch():
    init_db(":memory:")
    repo = ProcedureRepository(get_session(), get_default_standard())
    return BatchService(repo, get_default_standard()), repo


def test_clone_creates_new_doc(batch):
    """克隆应生成新编号的副本。"""
    from weldai.tests_demo import build_demo_pqr
    svc, repo = batch
    repo.save(build_demo_pqr())
    new = svc.clone("PQR-001", "PQR-002")
    assert new is not None
    assert new.doc_no == "PQR-002"
    assert repo.get("PQR-002") is not None
    # 源文件仍在
    assert repo.get("PQR-001") is not None


def test_clone_with_new_type(batch):
    """克隆时可改变类型。"""
    from weldai.tests_demo import build_demo_pqr
    svc, repo = batch
    repo.save(build_demo_pqr())
    new = svc.clone("PQR-001", "WPS-cloned", ProcedureType.WPS)
    assert new.type == ProcedureType.WPS


def test_clone_nonexistent_returns_none(batch):
    svc, _ = batch
    assert svc.clone("不存在", "X") is None


def test_find_wps_by_pqr(batch):
    """按PQR查找关联WPS。"""
    from weldai.tests_demo import build_demo_pqr, build_demo_wps
    svc, repo = batch
    repo.save(build_demo_pqr())
    wps = build_demo_wps()
    repo.save(wps)
    related = svc.find_wps_by_pqr("PQR-001")
    assert len(related) == 1
    assert related[0].doc_no == "WPS-001"


def test_verify_all_wps_success(batch):
    """WPS与PQR一致时应全部合格。"""
    from weldai.tests_demo import build_demo_pqr, build_demo_wps
    svc, repo = batch
    repo.save(build_demo_pqr())
    repo.save(build_demo_wps())
    results = svc.verify_all_wps()
    assert len(results) == 1
    assert results[0].wps_no == "WPS-001"
    assert results[0].success


def test_verify_wps_without_pqr(batch):
    """WPS未关联PQR时应标记错误。"""
    from weldai.tests_demo import build_demo_wps
    svc, repo = batch
    wps = build_demo_wps()
    wps.supporting_pqr_no = ""
    repo.save(wps)
    results = svc.verify_all_wps()
    assert not results[0].success
    assert "未关联PQR" in results[0].verdict or "未填写" in results[0].error


def test_export_to_excel_or_csv(tmp_path, batch):
    """应导出Excel或CSV文件。"""
    from weldai.tests_demo import build_demo_pqr
    svc, repo = batch
    repo.save(build_demo_pqr())
    out = svc.export_to_excel(str(tmp_path / "清单.xlsx"))
    from pathlib import Path
    assert Path(out).exists()
    assert Path(out).stat().st_size > 0


# ---------------------------------------------------------------------------
# 焊缝匹配可用工艺文件
# ---------------------------------------------------------------------------

def test_find_usable_for_seam(batch):
    """焊缝需求应能找出覆盖它的 PQR 及关联 WPS。"""
    from weldai.tests_demo import build_demo_pqr, build_demo_wps
    from weldai.domain.enums import Position, WeldingProcess
    from weldai.engine import WeldRequirement
    svc, repo = batch
    repo.save(build_demo_pqr())   # PQR-001: Q345R/16mm
    repo.save(build_demo_wps())   # WPS-001 依据 PQR-001

    req = WeldRequirement(
        process=WeldingProcess.SMAW, material_grade="Q345R",
        thickness=16.0, position=Position.PLATE_1G,
    )
    usable = svc.find_usable_for_seam(req)
    assert len(usable) == 1
    pqr, wpss = usable[0]
    assert pqr.doc_no == "PQR-001"
    assert len(wpss) == 1
    assert wpss[0].doc_no == "WPS-001"


def test_find_usable_no_match_for_thick_seam(batch):
    """超厚焊缝(40mm)不应匹配到16mm评定的PQR。"""
    from weldai.tests_demo import build_demo_pqr
    from weldai.domain.enums import Position, WeldingProcess
    from weldai.engine import WeldRequirement
    svc, repo = batch
    repo.save(build_demo_pqr())  # 覆盖上限32mm

    req = WeldRequirement(
        process=WeldingProcess.SMAW, material_grade="Q345R",
        thickness=40.0, position=Position.PLATE_1G,
    )
    usable = svc.find_usable_for_seam(req)
    assert usable == []  # 无匹配


def test_find_usable_pqr_without_wps(batch):
    """PQR能覆盖但无关联WPS时，应返回PQR和空WPS列表。"""
    from weldai.tests_demo import build_demo_pqr
    from weldai.domain.enums import Position, WeldingProcess
    from weldai.engine import WeldRequirement
    svc, repo = batch
    repo.save(build_demo_pqr())  # 只有PQR，无WPS

    req = WeldRequirement(
        process=WeldingProcess.SMAW, material_grade="Q345R",
        thickness=16.0, position=Position.PLATE_1G,
    )
    usable = svc.find_usable_for_seam(req)
    assert len(usable) == 1
    pqr, wpss = usable[0]
    assert wpss == []  # 无关联WPS
