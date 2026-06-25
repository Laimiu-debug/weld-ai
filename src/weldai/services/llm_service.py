"""LLM 焊接专家问答服务。

基于 OpenAI 兼容协议调用大模型（GLM/DeepSeek/Kimi 等，用户自带 key）。
预设焊接领域专家提示词模板，针对几类高频问题优化。

关键安全设计：
  - LLM 输出标注"仅供参考"
  - 涉及合规判定时提示以 weldAI 规则引擎校验结果为准
  - 避免 LLM 幻觉导致违规评定
"""
from __future__ import annotations

from dataclasses import dataclass

import requests

from .config_service import LLMConfig, load_config


# ---------------------------------------------------------------------------
# 预设焊接专家提示词
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是承压设备焊接工艺专家，熟悉以下国内标准：
- NB/T 47014《承压设备焊接工艺评定》
- NB/T 47015《压力容器焊接规程》
- TSG Z6002《特种设备焊接操作人员考核细则》
- GB/T 150《压力容器》、TSG 21《固定式压力容器安全技术监察规程》
- 各类母材(GB/T 713/24511)、焊材(GB/T 5117/5118/983/8110)标准

回答必须遵循：
1. 优先依据国内标准（而非 ISO/ASME），并标注标准条款来源
2. 涉及"是否需要重新评定""因素等级""覆盖范围"等合规判定时，明确提示：
   "此判定请以 weldAI 规则引擎校验结果为准，本回答仅供参考"
3. 给出焊接工艺建议时，说明适用条件、限制和潜在风险
4. 使用规范的中文专业术语
5. 如不确定或缺乏依据，明确说明，不要编造标准条款"""


# 问题类型 → user prompt 模板（{} 处填入用户问题或上下文）
PROMPT_TEMPLATES: dict[str, str] = {
    "process": (
        "【工艺咨询】\n{question}\n\n"
        "请从母材可焊性、焊接方法选择、焊材匹配、预热/PWHT要求等方面分析，"
        "并给出推荐的焊接工艺要点。标注适用标准条款。"
    ),
    "defect": (
        "【缺陷分析】\n{question}\n\n"
        "请分析该焊接缺陷(气孔/裂纹/未熔合/夹渣等)的可能成因，"
        "从工艺参数、材料、操作三方面给出对策。"
    ),
    "factor": (
        "【评定因素解释】\n{question}\n\n"
        "请解释 NB/T 47014 中该评定因素的重要性等级、变更后果及覆盖范围规则。"
        "注意：实际的重新评定判定请以 weldAI 规则引擎为准。"
    ),
    "rule_check": (
        "【规则引擎结果解读】\n"
        "weldAI 规则引擎已完成校验，结果如下：\n{context}\n\n"
        "用户问题：{question}\n\n"
        "请基于上述规则引擎的客观校验结果进行解读和解释。"
        "规则引擎的判定结论具有合规效力，你的解读仅作辅助说明。"
    ),
    "general": "{question}",
}


@dataclass
class LLMResponse:
    """LLM 回复。"""

    answer: str
    disclaimer: str = "⚠ 本回答由大模型生成，仅供参考。涉及合规判定以 weldAI 规则引擎结果为准。"
    error: str = ""
    success: bool = True


class LLMService:
    """LLM 焊接专家问答服务。"""

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or load_config().llm

    @property
    def is_configured(self) -> bool:
        """是否已配置可用（有 key 和 base_url）。"""
        return bool(self.config.api_key and self.config.base_url)

    def build_messages(
        self, question: str, question_type: str = "general", context: str = ""
    ) -> list[dict]:
        """构建请求消息（system + user）。"""
        template = PROMPT_TEMPLATES.get(question_type, PROMPT_TEMPLATES["general"])
        user_content = template.format(question=question, context=context or "（无）")
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    def ask(
        self,
        question: str,
        question_type: str = "general",
        context: str = "",
        timeout: int = 60,
    ) -> LLMResponse:
        """向 LLM 提问。

        question_type: process/defect/factor/rule_check/general
        context: 规则引擎结果等上下文（rule_check 类型时使用）

        失败时返回 LLMResponse(success=False, error=...)，不抛异常。
        """
        if not self.is_configured:
            return LLMResponse(
                answer="",
                error="未配置 LLM。请在「设置」中填写 API key 和服务商。",
                success=False,
            )

        messages = self.build_messages(question, question_type, context)
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]
            return LLMResponse(answer=answer)
        except requests.exceptions.Timeout:
            return LLMResponse(answer="", error="请求超时，请检查网络或重试。",
                               success=False)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            hint = ""
            if status == 401:
                hint = "（API key 无效或过期，请检查设置）"
            elif status == 429:
                hint = "（请求频率超限或额度不足）"
            return LLMResponse(
                answer="",
                error=f"API 调用失败 (HTTP {status}){hint}",
                success=False,
            )
        except (KeyError, IndexError) as e:
            return LLMResponse(
                answer="", error=f"响应解析失败: {e}", success=False
            )
        except Exception as e:
            return LLMResponse(answer="", error=f"调用异常: {e}", success=False)


# 问题类型选项（供 UI 下拉）
QUESTION_TYPES: list[tuple[str, str]] = [
    ("general", "💬 通用咨询"),
    ("process", "🔧 工艺咨询（母材可焊性/方法/焊材/参数）"),
    ("defect", "🔬 缺陷分析（气孔/裂纹/未熔合成因对策）"),
    ("factor", "📐 评定因素解释（NB/T 47014 因素等级）"),
    ("rule_check", "📊 规则引擎结果解读（结合校验结果）"),
]
