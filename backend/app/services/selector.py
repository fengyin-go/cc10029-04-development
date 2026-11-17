"""抽取规则业务规则：状态流转、字段校验与筛选口径都收在这里。

站点选择器绑定记录台账：读取目标站点准入数据集建立绑定，
绑定关系必须引用仍处于已准入状态的站点；重复或并发写入的第二份结果被拒绝。
"""
from __future__ import annotations

from typing import Any

from app.services import siteadmission
from app.store import store

MODULE = "selector"
LIST_FIELDS = ["规则编号", "归属站点", "列表选择器", "详情选择器", "字段选择器", "分页参数", "等待条件", "字符编码"]
REQUIRED_FIELDS = ["规则编号", "归属站点", "列表选择器"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用配置": "已启用", "停用配置": "已停用"}
NEGATIVE_ACTIONS = ["停用配置"]


class SelectorService:
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
            rows = [row for row in rows if keyword.casefold() in str(row.get("规则编号", "")).casefold()]
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
            return None, f"选择器规则 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于抽取规则可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"选择器规则已{action}"

    def list_bindings(
        self,
        *,
        keyword: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """读取站点选择器绑定记录台账。"""
        rows = siteadmission.list_bindings()
        if keyword:
            rows = [row for row in rows if keyword.casefold() in str(row.get("规则编号", "")).casefold()]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def establish_binding(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        """按规则的归属站点读取准入数据集，建立一条站点选择器绑定记录。"""
        rule = store.find(MODULE, entry_id)
        if rule is None:
            return None, f"选择器规则 {entry_id} 不存在或已归档"
        owner = str(rule.get("归属站点", "")).strip()
        site = siteadmission.find_site_by_key(owner)
        if site is None:
            return None, f"归属站点「{owner}」未在采集目标登记，不能建立绑定"
        record = siteadmission.find_admission_by_url(str(site.get("入口URL", "")).strip())
        if record is None or record.get("检查结论") != siteadmission.ADMITTED:
            return None, f"归属站点「{owner}」当前不在已准入状态，不能建立绑定"
        binding, effective = siteadmission.create_binding(rule, record)
        if not effective:
            return None, f"规则{rule.get('规则编号')}与站点{record.get('站点编号')}已存在生效绑定，第二份结果被拒绝"
        return binding, f"站点选择器绑定已建立（{binding['绑定编号']}），引用准入记录{record['准入编号']}"

    def sync_bindings(self) -> str:
        """从目标站点准入数据集全量同步绑定台账，重复结果只生效一次。"""
        created = 0
        rejected = 0
        skipped = 0
        for rule in store.rows(MODULE):
            owner = str(rule.get("归属站点", "")).strip()
            site = siteadmission.find_site_by_key(owner)
            record = siteadmission.find_admission_by_url(str(site.get("入口URL", "")).strip()) if site else None
            if record is None or record.get("检查结论") != siteadmission.ADMITTED:
                skipped += 1
                continue
            _, effective = siteadmission.create_binding(rule, record)
            if effective:
                created += 1
            else:
                rejected += 1
        return f"同步完成：新建绑定{created}条，拒绝重复{rejected}条，跳过未准入站点{skipped}条"
