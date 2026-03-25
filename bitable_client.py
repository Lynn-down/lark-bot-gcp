"""
bitable_client.py - Lark Bitable HR看板 客户端
支持：查询面试记录、新增记录、更新字段
"""
import logging
import requests
import time
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 国际版 open API base（Bitable 必须用 larksuite）
LARK_OPEN_BASE = "https://open.larksuite.com/open-apis"

# HR 看板配置（从 URL 提取）
HR_BOARD_WIKI_TOKEN = "LUI3wLWbliXDy9kWx4MlW0KvgXs"
HR_BOARD_TABLE_ID   = "tblBJz4F3owR3gOB"
HR_BOARD_VIEW_ID    = "vewSBm7mk4"

# 成员名册配置（直接 bitable URL，与 HR 看板同一个 base）
ROSTER_BITABLE_TOKEN = "Lpbhb302ZaVHmmsmbeCuhqQMsBd"
ROSTER_TABLE_ID      = "tbl6pInc5Iiipz7R"
ROSTER_VIEW_ID       = "vewmxmc30u"

# 字段展示顺序（其余字段会追加在后面）
_FIELD_ORDER = ["面试岗位", "岗位性质", "办公方式", "一面日期", "状态", "结果", "备注"]


def _val(raw) -> str:
    """把 Bitable 各种类型的字段值转为可读字符串"""
    if raw is None:
        return ""
    if isinstance(raw, list):
        parts = []
        for item in raw:
            if isinstance(item, dict):
                parts.append(item.get("text") or item.get("name") or str(item))
            else:
                parts.append(str(item))
        return "、".join(p for p in parts if p)
    if isinstance(raw, dict):
        # 优先返回 link URL；无 link 时返回 text/name（如人员、选项字段）
        return raw.get("link") or raw.get("text") or raw.get("name") or str(raw)
    if isinstance(raw, (int, float)) and raw > 1_000_000_000_000:
        # 时间戳（ms）
        try:
            return datetime.fromtimestamp(raw / 1000).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
    return str(raw)


class BitableClient:
    """HR 看板 Bitable 客户端"""

    def __init__(self, get_token_func):
        self.get_token = get_token_func
        self._app_token: Optional[str] = None
        self._cache: List[Dict] = []
        self._cache_ts: float = 0
        self._cache_ttl: int = 300  # 5 分钟

    # ── 内部工具 ──────────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.get_token()}",
            "Content-Type": "application/json",
        }

    def get_app_token(self) -> str:
        """通过 wiki token 解析真实的 bitable app_token"""
        if self._app_token:
            return self._app_token
        try:
            resp = requests.get(
                f"{LARK_OPEN_BASE}/wiki/v2/spaces/get_node",
                headers=self._headers(),
                params={"token": HR_BOARD_WIKI_TOKEN},
                timeout=10,
            )
            data = resp.json()
            logger.info(f"[Bitable] wiki node: code={data.get('code')} "
                        f"obj_type={data.get('data',{}).get('node',{}).get('obj_type')}")
            if data.get("code") == 0:
                node = data["data"]["node"]
                token = node.get("obj_token", "")
                if token:
                    self._app_token = token
                    return self._app_token
        except Exception as e:
            logger.error(f"[Bitable] get_app_token error: {e}")
        # fallback：直接用 wiki token 当 app_token
        self._app_token = HR_BOARD_WIKI_TOKEN
        logger.warning(f"[Bitable] Using wiki token as app_token (fallback)")
        return self._app_token

    def _invalidate_cache(self):
        self._cache = []
        self._cache_ts = 0

    # ── 读取 ──────────────────────────────────────────────────────────────────

    def get_all_records(self, force: bool = False) -> List[Dict]:
        """获取所有记录（带 5 分钟缓存）"""
        if not force and self._cache and time.time() - self._cache_ts < self._cache_ttl:
            return self._cache

        app_token = self.get_app_token()
        records, page_token = [], ""
        success = False

        while True:
            params: dict = {"page_size": 100}
            if HR_BOARD_VIEW_ID:
                params["view_id"] = HR_BOARD_VIEW_ID
            if page_token:
                params["page_token"] = page_token
            try:
                resp = requests.get(
                    f"{LARK_OPEN_BASE}/bitable/v1/apps/{app_token}"
                    f"/tables/{HR_BOARD_TABLE_ID}/records",
                    headers=self._headers(),
                    params=params,
                    timeout=15,
                )
                data = resp.json()
                if data.get("code") != 0:
                    logger.error(f"[Bitable] list_records failed: {data}")
                    break
                items = data.get("data", {}).get("items", [])
                records.extend(items)
                if not data["data"].get("has_more"):
                    success = True
                    break
                page_token = data["data"].get("page_token", "")
            except Exception as e:
                logger.error(f"[Bitable] list_records error: {e}")
                break

        if success:
            self._cache = records
            self._cache_ts = time.time()
            logger.info(f"[Bitable] loaded {len(records)} records")
        elif self._cache:
            logger.warning("[Bitable] fetch failed, returning stale cache")
        return self._cache if self._cache else records

    def search_by_name(self, name: str) -> List[Dict]:
        """按姓名模糊搜索"""
        name_q = name.strip().lower()
        results = []
        for rec in self.get_all_records():
            raw = rec.get("fields", {}).get("姓名", "")
            rec_name = _val(raw).lower()
            if rec_name and (name_q in rec_name or rec_name in name_q):
                results.append(rec)
        return results

    def format_record(self, rec: Dict) -> str:
        """格式化单条记录为可读文本（展示所有非空字段）"""
        fields = rec.get("fields", {})
        name = _val(fields.get("姓名", "")) or "未知"
        lines = [f"**{name}**"]
        shown = {"姓名"}
        # 优先按预设顺序展示已知字段
        for f in _FIELD_ORDER:
            v = _val(fields.get(f, ""))
            if v:
                lines.append(f"  {f}：{v}")
            shown.add(f)
        # 展示其余所有非空字段（含实际链接字段，不论名称）
        for f, raw in fields.items():
            if f in shown:
                continue
            v = _val(raw)
            if v:
                lines.append(f"  {f}：{v}")
        return "\n".join(lines)

    def summary_list(self) -> str:
        """返回所有候选人的概览列表"""
        records = self.get_all_records()
        if not records:
            return "HR看板暂无记录"
        lines = [f"HR看板共 **{len(records)}** 条记录："]
        for rec in records:
            f = rec.get("fields", {})
            name     = _val(f.get("姓名", ""))
            position = _val(f.get("面试岗位", ""))
            status   = _val(f.get("状态", ""))
            result   = _val(f.get("结果", ""))
            parts = [x for x in [position, status, result] if x]
            lines.append(f"• {name}" + (f" | {' / '.join(parts)}" if parts else ""))
        return "\n".join(lines)

    # ── 写入 ──────────────────────────────────────────────────────────────────

    def create_record(self, fields: dict) -> Optional[str]:
        """新增一条记录，返回 record_id"""
        app_token = self.get_app_token()
        try:
            resp = requests.post(
                f"{LARK_OPEN_BASE}/bitable/v1/apps/{app_token}"
                f"/tables/{HR_BOARD_TABLE_ID}/records",
                headers=self._headers(),
                json={"fields": fields},
                timeout=15,
            )
            data = resp.json()
            if data.get("code") == 0:
                rid = data["data"]["record"]["record_id"]
                self._invalidate_cache()
                logger.info(f"[Bitable] created record {rid}")
                return rid
            logger.error(f"[Bitable] create_record failed: {data}")
        except Exception as e:
            logger.error(f"[Bitable] create_record error: {e}")
        return None

    def update_record(self, record_id: str, fields: dict) -> bool:
        """更新指定记录的字段"""
        app_token = self.get_app_token()
        try:
            resp = requests.put(
                f"{LARK_OPEN_BASE}/bitable/v1/apps/{app_token}"
                f"/tables/{HR_BOARD_TABLE_ID}/records/{record_id}",
                headers=self._headers(),
                json={"fields": fields},
                timeout=15,
            )
            data = resp.json()
            if data.get("code") == 0:
                self._invalidate_cache()
                return True
            logger.error(f"[Bitable] update_record failed: {data}")
        except Exception as e:
            logger.error(f"[Bitable] update_record error: {e}")
        return False


# ── 全局实例 ──────────────────────────────────────────────────────────────────

hr_board: Optional[BitableClient] = None


def init_hr_board(get_token_func) -> BitableClient:
    global hr_board
    hr_board = BitableClient(get_token_func)
    return hr_board


# ── 成员名册 Bitable ──────────────────────────────────────────────────────────

class RosterBitableClient:
    """成员名册 Bitable 客户端（只读，写入权限待后续开放）"""

    def __init__(self, get_token_func):
        self.get_token = get_token_func
        self._cache: List[Dict] = []
        self._cache_ts: float = 0
        self._cache_ttl: int = 300

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.get_token()}",
            "Content-Type": "application/json",
        }

    def _invalidate_cache(self):
        self._cache = []
        self._cache_ts = 0

    def get_all_records(self, force: bool = False) -> List[Dict]:
        if not force and self._cache and time.time() - self._cache_ts < self._cache_ttl:
            return self._cache

        records, page_token, success = [], "", False
        while True:
            params: dict = {"page_size": 100, "view_id": ROSTER_VIEW_ID}
            if page_token:
                params["page_token"] = page_token
            try:
                resp = requests.get(
                    f"{LARK_OPEN_BASE}/bitable/v1/apps/{ROSTER_BITABLE_TOKEN}"
                    f"/tables/{ROSTER_TABLE_ID}/records",
                    headers=self._headers(), params=params, timeout=15,
                )
                data = resp.json()
                if data.get("code") != 0:
                    logger.error(f"[RosterBitable] list failed: {data}")
                    break
                records.extend(data.get("data", {}).get("items", []))
                if not data["data"].get("has_more"):
                    success = True
                    break
                page_token = data["data"].get("page_token", "")
            except Exception as e:
                logger.error(f"[RosterBitable] error: {e}")
                break

        if success:
            self._cache = records
            self._cache_ts = time.time()
            logger.info(f"[RosterBitable] loaded {len(records)} records")
        elif self._cache:
            logger.warning("[RosterBitable] fetch failed, using stale cache")
        return self._cache if self._cache else records

    def to_roster_data(self) -> Optional[List[list]]:
        """转换为 roster_module 使用的 list-of-lists 格式（第一行为表头）"""
        records = self.get_all_records()
        if not records:
            return None
        # 收集所有字段名作为表头
        all_fields: List[str] = []
        seen = set()
        for rec in records:
            for k in rec.get("fields", {}):
                if k not in seen:
                    all_fields.append(k)
                    seen.add(k)
        result: List[list] = [all_fields]
        for rec in records:
            fields = rec.get("fields", {})
            result.append([_val(fields.get(h, "")) for h in all_fields])
        return result

    def update_record(self, record_id: str, fields: dict) -> bool:
        """尝试写入（当前权限可能不足，失败静默返回 False）"""
        try:
            resp = requests.put(
                f"{LARK_OPEN_BASE}/bitable/v1/apps/{ROSTER_BITABLE_TOKEN}"
                f"/tables/{ROSTER_TABLE_ID}/records/{record_id}",
                headers=self._headers(),
                json={"fields": fields},
                timeout=15,
            )
            data = resp.json()
            if data.get("code") == 0:
                self._invalidate_cache()
                return True
            logger.warning(f"[RosterBitable] update failed (no write perm?): {data.get('code')} {data.get('msg')}")
        except Exception as e:
            logger.error(f"[RosterBitable] update error: {e}")
        return False

    def find_record_id(self, name: str) -> Optional[str]:
        """按姓名找 record_id（用于写入时定位行）"""
        name_q = name.strip().lower()
        for rec in self.get_all_records():
            v = _val(rec.get("fields", {}).get("姓名", "")).lower()
            if v and (name_q in v or v in name_q):
                return rec["record_id"]
        return None


roster_bitable: Optional[RosterBitableClient] = None


def init_roster_bitable(get_token_func) -> RosterBitableClient:
    global roster_bitable
    roster_bitable = RosterBitableClient(get_token_func)
    return roster_bitable
