"""SilverGuard Agent: use an LLM to understand the original bill text, then validate its claims."""

import json
import math
import re
import urllib.parse
import urllib.request

import config
from .core import ADVICE, money_values


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not follow redirects from a model endpoint."""

    def redirect_request(self, *args, **kwargs):
        return None


EXPECTED_KEYS = {
    "service_name", "category", "service_confidence", "service_evidence",
    "platform", "amount", "amount_evidence", "auto_renew", "renewal_evidence",
    "period", "what", "why", "risks", "next_steps",
}
UNKNOWN_SERVICE_NAMES = {"", "待确认服务", "未知", "不确定", "无法确认", "无"}
UNKNOWN_CATEGORIES = {"", "待确认", "待确认服务", "未知", "不确定", "无法确认"}


def _is_safe_url(base):
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme == "https" and parsed.hostname:
        return True
    return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}


def _normalize_for_match(value):
    """Normalize whitespace and punctuation for checking quoted evidence."""
    return re.sub(r"[\s\W_]+", "", value.casefold())


def _appears_in_text(quote, text):
    if not isinstance(quote, str) or not quote.strip():
        return False
    return _normalize_for_match(quote) in _normalize_for_match(text)


def _short_text(value, limit):
    if not isinstance(value, str):
        return ""
    value = " ".join(value.replace("\x00", " ").split()).strip()
    if len(value) > limit:
        value = value[:limit].rstrip()
    return value


def _safe_label(value, limit=24):
    value = _short_text(value, limit)
    if not value or any(ch in value for ch in "\r\n\t"):
        return ""
    return value


def _validate_model_shape(data):
    if not isinstance(data, dict) or set(data) != EXPECTED_KEYS:
        raise ValueError("模型输出字段不符合约定")
    if data["service_confidence"] not in {"high", "medium", "low"}:
        raise ValueError("服务置信度格式不正确")
    if data["amount"] is not None and (
        isinstance(data["amount"], bool)
        or not isinstance(data["amount"], (int, float))
        or not math.isfinite(float(data["amount"]))
        or not 0 <= float(data["amount"]) <= 10000000
    ):
        raise ValueError("模型金额格式不正确")
    if data["auto_renew"] is not None and type(data["auto_renew"]) is not bool:
        raise ValueError("续费状态格式不正确")
    if data["period"] not in {None, "月", "年", "一次性", "不明"}:
        raise ValueError("续费周期格式不正确")
    for key in ("service_name", "category", "service_evidence", "platform", "amount_evidence",
                "renewal_evidence", "what", "why"):
        if not isinstance(data[key], str):
            raise ValueError(f"模型字段 {key} 格式不正确")
    if not isinstance(data["risks"], list) or not isinstance(data["next_steps"], list):
        raise ValueError("模型风险和建议必须是列表")
    if any(not isinstance(item, str) for item in data["risks"] + data["next_steps"]):
        raise ValueError("模型风险和建议列表中包含非文本内容")


def _explicit_amount_from_evidence(amount, evidence, original_text):
    """Accept an LLM amount only when its quoted evidence appears in the input and states a currency."""
    if amount is None or not _appears_in_text(evidence, original_text):
        return None
    evidence = evidence.strip()
    # Require an explicit currency marker; bare numbers could be dates or order numbers.
    has_currency = bool(re.search(
        r"(?:[¥￥]\s*\d[\d,]*(?:\.\d{1,2})?|人民币\s*\d[\d,]*(?:\.\d{1,2})?|"
        r"\d[\d,]*(?:\.\d{1,2})?\s*(?:元|块钱|块|人民币|CNY|RMB))",
        evidence,
        flags=re.IGNORECASE,
    ))
    if not has_currency:
        return None
    try:
        return float(amount)
    except (TypeError, ValueError):
        return None


def _renewal_evidence_is_clear(evidence, value, original_text):
    if not evidence or not _appears_in_text(evidence, original_text):
        return False
    negative = (
        "已关闭自动续费", "自动续费已关闭", "已取消自动续费", "自动扣费已关闭",
        "未开通自动续费", "未开启自动续费", "不自动续费", "不会自动续费",
        "已停止自动续费", "续费已关闭", "已取消续订", "不会继续扣费",
    )
    positive = (
        "连续包月", "连续包年", "每月自动扣", "每年自动扣", "已开启自动续费",
        "已开通自动续费", "已开启自动续期", "到期自动续费", "将自动续费",
        "自动续费已开启", "每月续费", "每年续费", "按月续费", "按年续费",
        "自动扣款已开通", "自动续订已开启",
    )
    has_negative = any(phrase in evidence for phrase in negative)
    has_positive = any(phrase in evidence for phrase in positive)
    if has_negative and has_positive:
        return False
    if value is True:
        return has_positive and not has_negative
    if value is False:
        return has_negative and not has_positive
    return False


def _safe_model_list(items, limit, item_limit):
    output = []
    for item in items[:limit]:
        cleaned = _short_text(item, item_limit)
        if not cleaned:
            continue
        # Never display model-provided links or instructions that solicit secrets/actions.
        if re.search(r"https?://|www\.", cleaned, re.IGNORECASE):
            continue
        if re.search(r"(提供|发送|告知|告诉|转发).{0,10}(验证码|密码|银行卡号|支付密码)", cleaned):
            continue
        output.append(cleaned)
    return output


def _merge_model_analysis(result, original_text, data):
    """Merge useful model inferences while preserving stronger local evidence and safety checks."""
    _validate_model_shape(data)
    original_text = original_text.strip()
    confidence = data["service_confidence"]

    # Only accept a newly identified service if its name is actually present in the user's text.
    service_name = _short_text(data["service_name"], 60)
    if result["service"] == "待确认服务":
        if (service_name.casefold() not in {name.casefold() for name in UNKNOWN_SERVICE_NAMES}
                and confidence in {"high", "medium"}
                and _appears_in_text(service_name, original_text)):
            result["service"] = service_name
            result["service_source"] = "大模型根据输入文字推断，尚未核实"
            result["service_confidence"] = confidence
            for risk in result.get("risks", []):
                if risk.get("code") == "unknown_service":
                    risk["message"] = "服务名称已由大模型初步识别，但尚未通过官方账单核实；陌生名称本身不等于诈骗。"
                    risk["source"] = "大模型推断（未核实）"

    # Let the model propose a category when the local dictionary could not classify the item.
    category = _safe_label(data["category"], 24)
    if result["category"] in UNKNOWN_CATEGORIES and category and category not in UNKNOWN_CATEGORIES:
        result["category"] = category
        result["category_source"] = "大模型推断，尚未核实"

    # Platform is only filled from a model if the relevant platform is supported by the input text.
    if result.get("platform") == "未说明":
        platform = _safe_label(data["platform"], 24)
        platform_aliases = {
            "微信支付": ("微信支付", "微信"),
            "支付宝": ("支付宝",),
            "银行卡": ("银行卡", "信用卡", "借记卡"),
            "Apple Pay": ("Apple Pay", "苹果支付"),
        }
        if any(_appears_in_text(alias, original_text) for alias in platform_aliases.get(platform, (platform,)) if alias):
            result["platform"] = platform

    # Keep regex-extracted amounts. Only fill a missing amount from an explicit quoted currency phrase.
    if result.get("amount") is None:
        # If the text contains multiple explicit amounts, leave the amount unresolved rather than guessing.
        local_amounts = money_values(original_text)
        amount = None if len(local_amounts) > 1 else _explicit_amount_from_evidence(
            data["amount"], data["amount_evidence"], original_text
        )
        if amount is not None:
            result["amount"] = amount
            result["amount_source"] = "大模型提取并通过原文金额证据校验"

    # Do not override clear local renewal evidence. Use model status only when the quoted phrase is clear.
    if result.get("auto_renew") is None and data["auto_renew"] is not None:
        if _renewal_evidence_is_clear(data["renewal_evidence"], data["auto_renew"], original_text):
            result["auto_renew"] = data["auto_renew"]
            result["renewal_source"] = "大模型解释文字并通过关键词证据校验，仍需官方页面确认"
            if result.get("period") is None and data["period"] in {"月", "年"}:
                period_patterns = {
                    "月": r"每月|每个月|按月|月付|月费|包月|月度",
                    "年": r"每年|每一年|按年|年付|年费|包年|年度",
                }
                if re.search(period_patterns[data["period"]], original_text):
                    result["period"] = data["period"]
            if result["auto_renew"] is True:
                if "renew" not in result["advice_ids"]:
                    result["advice_ids"].append("renew")
                if "cancel" not in result["advice_ids"]:
                    result["advice_ids"].append("cancel")
                result["next_steps"] = [ADVICE[item] for item in result["advice_ids"]]
                if not any(risk["code"] == "llm_renewal_inference" for risk in result["risks"]):
                    result["risks"].append({
                        "code": "llm_renewal_inference",
                        "level": "待核实",
                        "message": "大模型根据输入文字推断可能存在自动续费，请到官方服务页面确认当前状态。",
                        "source": "大模型推断（未核实）",
                    })
                    if result["risk_level"] == "未发现规则命中":
                        result["risk_level"] = "注意"
            elif result["auto_renew"] is False and "paid" not in result["advice_ids"]:
                result["advice_ids"].append("paid")
                result["next_steps"] = [ADVICE[item] for item in result["advice_ids"]]

    # Model-generated explanations and suggestions are clearly marked as inferences.
    what = _short_text(data["what"], 400)
    why = _short_text(data["why"], 500)
    if what:
        result["what"] = what
    if why:
        result["why"] = why

    result["llm_risks"] = _safe_model_list(data["risks"], 3, 160)
    result["llm_next_steps"] = _safe_model_list(data["next_steps"], 4, 180)
    result["llm_source_note"] = "以下内容由大模型根据输入文字推断，未查询官方账户或交易记录，请自行核实。"
    result["mode"] = "本地规则 + 大模型账单理解 + 本地风险校验"
    result["llm_status"] = "成功：模型分析了原始账单并补充服务识别、类别、解释和建议"
    return result


def apply_agent(result, original_text=""):
    """Optionally analyze original bill text with the configured LLM; fall back to local rules on failure."""
    if not config.ENABLE_AGENT:
        return result

    base = config.LLM_BASE_URL.strip().rstrip("/")
    model = config.LLM_MODEL.strip()
    key = config.LLM_API_KEY.strip()
    local_api = urllib.parse.urlparse(base).hostname in {"localhost", "127.0.0.1", "::1"}

    if not base or not model or (not key and not local_api):
        result["llm_status"] = "模型地址、模型名称或密钥未配置，已使用本地规则结果"
        return result

    if not isinstance(original_text, str) or not original_text.strip():
        result["llm_status"] = "未提供原始账单文字，无法进行大模型账单理解"
        return result

    try:
        if not _is_safe_url(base):
            raise ValueError("模型服务必须使用 HTTPS，或使用本地 HTTP 地址")

        facts = {
            "bill_text": original_text[:12000],
            "local_analysis": {
                "service": result.get("service"),
                "category": result.get("category"),
                "platform": result.get("platform"),
                "amount": result.get("amount"),
                "auto_renew": result.get("auto_renew"),
                "period": result.get("period"),
                "risk_codes": [risk["code"] for risk in result.get("risks", [])],
            },
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": config.SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        req = urllib.request.Request(
            base + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=config.LLM_TIMEOUT) as response:
            raw = response.read(200001)
        if len(raw) > 200000:
            raise ValueError("模型返回内容过长")

        response_data = json.loads(raw.decode("utf-8"))
        content = response_data["choices"][0]["message"]["content"]
        model_analysis = json.loads(content)
        return _merge_model_analysis(result, original_text, model_analysis)
    except Exception as exc:
        # Never include raw request text, response body, or API key in the terminal error.
        result["llm_status"] = (
            f"模型调用失败或输出校验未通过（{type(exc).__name__}），已使用本地规则结果"
        )
        return result
