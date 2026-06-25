"""LLM 服务单测（mock API，不实际调用）。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from weldai.services import LLMConfig, LLMService, PROMPT_TEMPLATES, SYSTEM_PROMPT


@pytest.fixture
def configured_service() -> LLMService:
    cfg = LLMConfig(
        provider="glm",
        api_key="test-key-123",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4-flash",
    )
    return LLMService(cfg)


# ---------------------------------------------------------------------------
# 配置与提示词
# ---------------------------------------------------------------------------

def test_is_configured():
    """有 key 和 url 时应判定为已配置。"""
    assert LLMService(LLMConfig(api_key="k", base_url="u")).is_configured
    assert not LLMService(LLMConfig(api_key="", base_url="u")).is_configured
    assert not LLMService(LLMConfig(api_key="k", base_url="")).is_configured


def test_system_prompt_has_domain_constraints():
    """系统提示词应包含领域约束（国内标准优先、合规提示）。"""
    assert "NB/T 47014" in SYSTEM_PROMPT
    assert "TSG Z6002" in SYSTEM_PROMPT
    assert "规则引擎" in SYSTEM_PROMPT  # 合规判定提示


def test_prompt_templates_cover_types():
    """应有5类提示词模板。"""
    for t in ("process", "defect", "factor", "rule_check", "general"):
        assert t in PROMPT_TEMPLATES


def test_build_messages_includes_system_and_user(configured_service):
    """构建的消息应含 system + user 两部分。"""
    msgs = configured_service.build_messages("如何焊接Q345R", "process")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "Q345R" in msgs[1]["content"]


def test_rule_check_template_includes_context():
    """rule_check 模板应嵌入规则引擎上下文。"""
    svc = LLMService(LLMConfig(api_key="k", base_url="u"))
    msgs = svc.build_messages(
        "为什么需要重新评定", "rule_check",
        context="重要因素变更：电源类型DCEP→DCEN",
    )
    assert "电源类型" in msgs[1]["content"]
    assert "规则引擎" in msgs[1]["content"]


# ---------------------------------------------------------------------------
# 未配置时的行为
# ---------------------------------------------------------------------------

def test_ask_when_not_configured():
    """未配置时应返回友好错误而非崩溃。"""
    svc = LLMService(LLMConfig(api_key="", base_url=""))
    resp = svc.ask("测试问题")
    assert not resp.success
    assert "未配置" in resp.error


# ---------------------------------------------------------------------------
# mock API 调用
# ---------------------------------------------------------------------------

def _mock_response(content="这是测试回复", status=200):
    """构造 mock requests.Response。"""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    resp.raise_for_status = MagicMock()
    if status >= 400:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=resp
        )
    return resp


@patch("weldai.services.llm_service.requests.post")
def test_ask_success(mock_post, configured_service):
    """成功调用应返回 LLM 内容 + 免责声明。"""
    mock_post.return_value = _mock_response("Q345R 推荐用 J507 焊条")
    resp = configured_service.ask("Q345R用什么焊条", "process")
    assert resp.success
    assert "J507" in resp.answer
    assert "仅供参考" in resp.disclaimer


@patch("weldai.services.llm_service.requests.post")
def test_ask_correct_url_and_auth(mock_post, configured_service):
    """应调用正确的 URL 和 Authorization 头。"""
    mock_post.return_value = _mock_response()
    configured_service.ask("test")
    args, kwargs = mock_post.call_args
    assert "chat/completions" in args[0]
    assert kwargs["headers"]["Authorization"] == "Bearer test-key-123"


@patch("weldai.services.llm_service.requests.post")
def test_ask_401_invalid_key(mock_post, configured_service):
    """401 应提示 API key 无效。"""
    mock_post.return_value = _mock_response(status=401)
    resp = configured_service.ask("test")
    assert not resp.success
    assert "401" in resp.error
    assert "API key" in resp.error or "key" in resp.error.lower()


@patch("weldai.services.llm_service.requests.post")
def test_ask_timeout(mock_post, configured_service):
    """超时应返回超时错误。"""
    mock_post.side_effect = requests.exceptions.Timeout()
    resp = configured_service.ask("test")
    assert not resp.success
    assert "超时" in resp.error


@patch("weldai.services.llm_service.requests.post")
def test_ask_429_rate_limit(mock_post, configured_service):
    """429 应提示频率/额度。"""
    mock_post.return_value = _mock_response(status=429)
    resp = configured_service.ask("test")
    assert not resp.success
    assert "额度" in resp.error or "频率" in resp.error
