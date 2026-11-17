"""目标站点准入数据集与站点选择器绑定台账。

这是采集目标与抽取规则共用的数据面：

- 准入数据集按「入口URL」唯一：同一入口URL的重复准入检查只刷新检查时间与约束快照，
  不会生成第二条有效准入记录；并发提交由锁串行化，只允许一个提交生效。
- 准入规则由采集目标判定：口径（字符编码白名单）、上限（重试上限）、范围（URL 协议）、
  条件（抓取间隔下限、请求头必含 User-Agent）同时生效，任一不满足都不得进入已准入范围。
- 保存的请求约束始终快照目标站点当前生效配置；检查过程中发生编码修订与入口重定向
  冲突时，以站点当前生效配置为实际约束来源，最终只落一份数据集。
- 绑定台账按「规则编号 + 站点编号」唯一：抽取规则只能引用仍处于已准入状态的站点，
  重复或并发回写的第二份结果会被拒绝；站点复检未准入时，既有绑定同步失效。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from app.store import store

ADMISSION_MODULE = "siteadmission"
BINDING_MODULE = "selectorbinding"
TARGET_MODULE = "targetsite"
RULE_MODULE = "selector"

ADMISSION_FIELDS = [
    "准入编号", "站点编号", "站点名称", "入口URL", "请求方法", "请求头模板",
    "字符编码", "重试上限", "抓取间隔", "约束来源", "检查结论", "未准入原因",
    "冲突说明", "重定向URL", "检查时间",
]
BINDING_FIELDS = [
    "绑定编号", "规则编号", "站点编号", "站点名称", "入口URL",
    "准入编号", "约束来源", "绑定时间",
]

ADMITTED = "已准入"
REJECTED = "未准入"
BINDING_ACTIVE = "生效"
BINDING_INVALID = "失效"

# 约束来源：准入记录里保存的请求约束取自哪里。
SOURCE_SITE_CONFIG = "站点生效配置"
SOURCE_REDIRECT_OBSERVED = "重定向后观测约束"

# ---- 采集目标侧判定阈值：口径、上限、范围、条件同时生效 ----
ALLOWED_ENCODINGS = {"UTF-8", "GBK", "GB2312", "GB18030", "BIG5", "ISO-8859-1"}  # 口径
MAX_RETRY_LIMIT = 10  # 上限：重试上限不得超过
URL_SCOPE_PREFIXES = ("http://", "https://")  # 范围：入口URL协议
MIN_FETCH_INTERVAL = 1.0  # 条件：抓取间隔下限（秒）
REQUIRED_HEADER_KEYS = ("user-agent",)  # 条件：请求头模板必含字段
REQUIRED_CONSTRAINT_FIELDS = ["入口URL", "字符编码", "抓取间隔", "请求头模板"]

# 准入数据集与绑定台账共用一把可重入锁：检查提交与回写在同一把锁内完成，
# 并发写入时只允许一个提交成功，第二份结果被拒绝。
_lock = threading.RLock()


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _next_id(rows: list[dict[str, Any]]) -> int:
    return max((int(row.get("id", 0)) for row in rows), default=0) + 1


def _next_code(rows: list[dict[str, Any]], field: str, prefix: str) -> str:
    suffixes = []
    for row in rows:
        code = str(row.get(field, ""))
        if code.startswith(prefix) and code[len(prefix):].isdigit():
            suffixes.append(int(code[len(prefix):]))
    return f"{prefix}{(max(suffixes, default=0) + 1):04d}"


def evaluate_constraints(site: dict[str, Any]) -> list[str]:
    """按采集目标的判定口径核验站点约束，返回未准入原因列表（空列表表示通过）。

    口径、上限、范围、条件四类规则同时生效；缺字段的站点直接判未准入。
    """
    reasons: list[str] = []
    missing = [field for field in REQUIRED_CONSTRAINT_FIELDS if not str(site.get(field) or "").strip()]
    if missing:
        reasons.append(f"缺少必填字段：{'、'.join(missing)}")

    url = str(site.get("入口URL") or "").strip()
    if url and not url.lower().startswith(URL_SCOPE_PREFIXES):
        reasons.append("入口URL不在允许范围（仅支持 http/https）")

    encoding = str(site.get("字符编码") or "").strip()
    if encoding and encoding.upper() not in ALLOWED_ENCODINGS:
        reasons.append(f"字符编码「{encoding}」不在允许口径内")

    interval_raw = str(site.get("抓取间隔") or "").strip()
    if interval_raw:
        try:
            interval = float(interval_raw)
        except ValueError:
            reasons.append(f"抓取间隔「{interval_raw}」不是有效数值")
        else:
            if interval < MIN_FETCH_INTERVAL:
                reasons.append(f"抓取间隔{interval_raw}秒低于下限{MIN_FETCH_INTERVAL:g}秒")

    retry_raw = str(site.get("重试上限") or "").strip()
    if retry_raw:
        try:
            retry = int(float(retry_raw))
        except ValueError:
            reasons.append(f"重试上限「{retry_raw}」不是有效整数")
        else:
            if retry > MAX_RETRY_LIMIT:
                reasons.append(f"重试上限{retry_raw}超过上限{MAX_RETRY_LIMIT}")

    headers = str(site.get("请求头模板") or "").strip()
    if headers and not any(key in headers.lower() for key in REQUIRED_HEADER_KEYS):
        reasons.append("请求头模板缺少 User-Agent")
    return reasons


def find_admission_by_url(url: str) -> dict[str, Any] | None:
    for row in store.rows(ADMISSION_MODULE):
        if row.get("入口URL") == url:
            return row
    return None


def find_site_by_key(key: str) -> dict[str, Any] | None:
    """按站点名称或站点编号在采集目标里定位站点。"""
    key = key.strip()
    if not key:
        return None
    for row in store.rows(TARGET_MODULE):
        if key in {str(row.get("站点名称", "")), str(row.get("站点编号", ""))}:
            return row
    return None


def list_admissions() -> list[dict[str, Any]]:
    return list(store.rows(ADMISSION_MODULE))


def list_bindings() -> list[dict[str, Any]]:
    return list(store.rows(BINDING_MODULE))


def _rule_matches_record(rule: dict[str, Any], record: dict[str, Any]) -> bool:
    owner = str(rule.get("归属站点", "")).strip()
    return bool(owner) and owner in {str(record.get("站点名称", "")), str(record.get("站点编号", ""))}


def _find_binding_locked(rule_code: str, site_code: str) -> dict[str, Any] | None:
    for row in store.rows(BINDING_MODULE):
        if row.get("规则编号") == rule_code and row.get("站点编号") == site_code:
            return row
    return None


def create_binding(rule: dict[str, Any], record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """建立一条站点选择器绑定；已存在生效绑定时拒绝第二份结果。

    返回 (绑定记录, 是否本次生效)。失效绑定重新准入时原位复活，仍只算一条记录。
    """
    with _lock:
        rows = store.rows(BINDING_MODULE)
        rule_code = str(rule.get("规则编号", ""))
        site_code = str(record.get("站点编号", ""))
        existing = _find_binding_locked(rule_code, site_code)
        now = _now_text()
        if existing is not None:
            if existing.get("status") == BINDING_ACTIVE:
                return existing, False
            existing.update({
                "准入编号": record.get("准入编号", ""),
                "约束来源": record.get("约束来源", ""),
                "入口URL": record.get("入口URL", ""),
                "绑定时间": now,
                "status": BINDING_ACTIVE,
            })
            return existing, True
        binding = {
            "id": _next_id(rows),
            "绑定编号": _next_code(rows, "绑定编号", "BIND-"),
            "规则编号": rule_code,
            "站点编号": site_code,
            "站点名称": record.get("站点名称", ""),
            "入口URL": record.get("入口URL", ""),
            "准入编号": record.get("准入编号", ""),
            "约束来源": record.get("约束来源", ""),
            "绑定时间": now,
            "status": BINDING_ACTIVE,
        }
        rows.append(binding)
        return binding, True


def _write_back_locked(record: dict[str, Any]) -> tuple[int, int]:
    """把准入结果回写到抽取规则的绑定台账，返回 (新建数, 被拒绝的重复数)。"""
    created = 0
    rejected = 0
    for rule in store.rows(RULE_MODULE):
        if not _rule_matches_record(rule, record):
            continue
        _, effective = create_binding(rule, record)
        if effective:
            created += 1
        else:
            rejected += 1
    return created, rejected


def _invalidate_bindings_locked(record: dict[str, Any]) -> int:
    """站点复检未准入时，引用它的生效绑定同步失效。"""
    invalidated = 0
    for row in store.rows(BINDING_MODULE):
        if row.get("站点编号") == record.get("站点编号") and row.get("status") == BINDING_ACTIVE:
            row["status"] = BINDING_INVALID
            invalidated += 1
    return invalidated


def check_site_admission(
    site: dict[str, Any],
    *,
    redirect_url: str = "",
    detected_encoding: str = "",
) -> dict[str, Any]:
    """对目标站点执行准入检查并提交准入数据集。

    返回 {"record": 准入记录或None, "created": 是否新建, "conclusion": 结论,
          "reasons": 未准入原因, "bound": 回写新建数, "rejected": 回写拒绝数,
          "invalidated": 失效绑定数}。
    """
    reasons = evaluate_constraints(site)
    conclusion = ADMITTED if not reasons else REJECTED
    url = str(site.get("入口URL") or "").strip()
    redirect_url = redirect_url.strip()
    detected = detected_encoding.strip()
    configured_encoding = str(site.get("字符编码") or "").strip()

    # 编码修订与入口重定向的冲突裁定：约束始终取自站点当前生效配置。
    source = SOURCE_SITE_CONFIG
    conflict = ""
    if redirect_url and detected:
        if redirect_url == url and detected.upper() == configured_encoding.upper():
            source = SOURCE_REDIRECT_OBSERVED
        elif redirect_url != url and detected.upper() != configured_encoding.upper():
            conflict = "编码修订与入口重定向冲突，已按站点当前生效配置裁定"

    result: dict[str, Any] = {
        "record": None, "created": False, "conclusion": conclusion,
        "reasons": reasons, "bound": 0, "rejected": 0, "invalidated": 0,
    }
    if not url:
        # 没有入口URL无法作为准入键，检查结论照常返回但不落数据集。
        return result

    with _lock:
        rows = store.rows(ADMISSION_MODULE)
        now = _now_text()
        snapshot = {
            "站点编号": site.get("站点编号", ""),
            "站点名称": site.get("站点名称", ""),
            "入口URL": url,
            "请求方法": site.get("请求方法", ""),
            "请求头模板": site.get("请求头模板", ""),
            "字符编码": site.get("字符编码", ""),
            "重试上限": site.get("重试上限", ""),
            "抓取间隔": site.get("抓取间隔", ""),
            "约束来源": source,
            "检查结论": conclusion,
            "未准入原因": "；".join(reasons),
            "冲突说明": conflict,
            "重定向URL": redirect_url,
            "检查时间": now,
            "status": conclusion,
        }
        existing = find_admission_by_url(url)
        if existing is not None:
            # 重复检查：只更新检查时间与约束快照，不生成第二条记录。
            existing.update(snapshot)
            record = existing
        else:
            record = {"id": _next_id(rows), "准入编号": _next_code(rows, "准入编号", "ADM-")}
            record.update(snapshot)
            rows.append(record)
            result["created"] = True
        result["record"] = record
        if conclusion == ADMITTED:
            bound, rejected = _write_back_locked(record)
            result["bound"] = bound
            result["rejected"] = rejected
        else:
            result["invalidated"] = _invalidate_bindings_locked(record)
    return result
