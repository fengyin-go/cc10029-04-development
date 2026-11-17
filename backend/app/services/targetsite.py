"""采集目标业务规则：状态流转、字段校验与筛选口径都收在这里。

准入检查（目标站点准入数据集）的规则也由采集目标判定：
口径、上限、范围、条件同时生效，阈值常量集中在 app.services.siteadmission。
"""
from __future__ import annotations

from typing import Any

from app.services import siteadmission
from app.store import store

MODULE = "targetsite"
LIST_FIELDS = ["站点编号", "站点名称", "入口URL", "请求方法", "请求头模板", "字符编码", "重试上限", "抓取间隔"]
REQUIRED_FIELDS = ["站点编号", "站点名称", "入口URL"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用配置": "已启用", "停用配置": "已停用"}
NEGATIVE_ACTIONS = ["停用配置"]


class TargetsiteService:
    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        for field, expected in (filters or {}).items():
            rows = [row for row in rows if expected.casefold() in str(row.get(field, "")).casefold()]
        if keyword:
            rows = [row for row in rows if keyword.casefold() in str(row.get("站点编号", "")).casefold()]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in LIST_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"目标站点 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于采集目标可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"目标站点已{action}"

    def list_admissions(
        self,
        *,
        keyword: str | None = None,
        conclusion: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """读取目标站点准入数据集；字段名与返回结构保持稳定。"""
        rows = siteadmission.list_admissions()
        if keyword:
            rows = [row for row in rows if keyword.casefold() in str(row.get("站点编号", "")).casefold()]
        if conclusion:
            rows = [row for row in rows if row.get("检查结论") == conclusion]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def check_admission(
        self,
        entry_id: int,
        *,
        redirect_url: str = "",
        detected_encoding: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        """校验站点可采集性并提交目标站点准入数据集。

        同一入口URL只保留一条有效记录：重复检查只更新检查时间与约束快照；
        并发写入由数据面的锁串行化，只允许一个提交成功。
        """
        site = store.find(MODULE, entry_id)
        if site is None:
            return None, f"目标站点 {entry_id} 不存在或已归档"
        result = siteadmission.check_site_admission(
            site, redirect_url=redirect_url, detected_encoding=detected_encoding)
        record = result["record"]
        if record is None:
            return None, f"准入检查未通过：{'；'.join(result['reasons'])}；未生成准入记录"
        if result["conclusion"] == siteadmission.ADMITTED:
            message = f"准入检查通过，结论：已准入（{record['准入编号']}）"
            if not result["created"]:
                message += "；该入口URL已存在有效准入记录，本次仅更新检查时间"
            message += f"；回写站点选择器绑定{result['bound']}条"
            if result["rejected"]:
                message += f"，拒绝重复{result['rejected']}条"
        else:
            message = f"准入检查未通过：{'；'.join(result['reasons'])}"
            if result["invalidated"]:
                message += f"；同步失效绑定{result['invalidated']}条"
        if record.get("冲突说明"):
            message += f"；{record['冲突说明']}"
        return record, message
