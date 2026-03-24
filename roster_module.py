"""
成员名册查询模块
"""
import json
import os
from typing import Dict, List, Optional

class RosterManager:
    """成员名册管理器"""
    
    def __init__(self, roster_file: str = "roster.json"):
        self.roster_file = roster_file
        self.data = []
        self.headers = []
        self._load_data()
    
    def _load_data(self):
        """加载名册数据"""
        try:
            with open(self.roster_file, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            if self.data:
                self.headers = self.data[0]  # 第一行是表头
            print(f"[Roster] 加载了 {len(self.data)} 条记录")
        except Exception as e:
            print(f"[Roster] 加载失败: {e}")
            self.data = []
            self.headers = []
    
    def _get_field(self, row: list, field_name: str) -> str:
        """获取指定字段的值"""
        if field_name in self.headers:
            idx = self.headers.index(field_name)
            if idx < len(row):
                val = row[idx]
                return str(val) if val else ""
        return ""
    
    def query_by_name(self, name: str) -> Optional[Dict]:
        """根据姓名查询人员信息（优先在职记录）"""
        name = name.strip().lower()
        best_match = None
        for row in self.data[1:]:  # 跳过表头
            # 姓名字段和人员字段都尝试匹配
            row_name = self._get_field(row, "姓名").lower()
            row_member = self._get_field(row, "人员").lower()
            candidate = row_name or row_member
            if not candidate:
                continue  # 两个字段都为空则跳过，避免空字符串误匹配
            if name in candidate or candidate in name:
                d = self._row_to_dict(row)
                # 优先返回在职记录
                if "在职" in d.get("工作状态", ""):
                    return d
                if best_match is None:
                    best_match = d
        return best_match
    
    def query_by_position(self, position: str) -> List[Dict]:
        """根据职位查询人员"""
        results = []
        position = position.lower()
        for row in self.data[1:]:
            pos = self._get_field(row, "合同职务").lower()
            if position in pos:
                results.append(self._row_to_dict(row))
        return results
    
    def query_by_status(self, status: str) -> List[Dict]:
        """根据工作状态查询"""
        results = []
        for row in self.data[1:]:
            row_status = self._get_field(row, "工作状态")
            if status in row_status:
                results.append(self._row_to_dict(row))
        return results
    
    def query_by_work_type(self, work_type: str) -> List[Dict]:
        """根据工作类型查询"""
        results = []
        for row in self.data[1:]:
            wt = self._get_field(row, "工作类型")
            if work_type in wt:
                results.append(self._row_to_dict(row))
        return results
    
    def _row_to_dict(self, row: list) -> Dict:
        """将行数据转换为字典"""
        result = {}
        for i, header in enumerate(self.headers):
            if i < len(row) and row[i]:
                result[header] = row[i]
        return result
    
    def get_statistics(self) -> Dict:
        """获取统计数据"""
        stats = {
            "total": len(self.data) - 1,
            "在职": 0,
            "离职归档": 0,
            "全职": 0,
            "兼职": 0,
            "实习": 0,
            "顾问": 0,
            "代发": 0,
            "劳务": 0
        }
        
        for row in self.data[1:]:
            status = self._get_field(row, "工作状态")
            work_type = self._get_field(row, "工作类型")
            
            if "在职" in status:
                stats["在职"] += 1
            elif "离职归档" in status:
                stats["离职归档"] += 1
            
            if "全职" in work_type:
                stats["全职"] += 1
            elif "兼职" in work_type:
                stats["兼职"] += 1
            elif "实习" in work_type:
                stats["实习"] += 1
            elif "顾问" in work_type:
                stats["顾问"] += 1
            elif "代发" in work_type:
                stats["代发"] += 1
            elif "劳务" in work_type:
                stats["劳务"] += 1
        
        return stats
    
    def format_person_info(self, person: Dict, is_hr: bool = False) -> str:
        """格式化人员信息"""
        lines = []
        display_name = person.get('姓名') or person.get('人员') or 'N/A'
        lines.append(f"【{display_name}】")

        if person.get('合同职务'):
            lines.append(f"职务：{person['合同职务']}")
        if person.get('工作类型'):
            lines.append(f"类型：{person['工作类型']}")
        if person.get('工作状态'):
            lines.append(f"状态：{person['工作状态']}")
        if person.get('主体'):
            lines.append(f"主体：{person['主体']}")
        if person.get('开始日期') and person['开始日期'] != 'None':
            lines.append(f"入职：{person['开始日期'][:10] if len(person['开始日期']) > 10 else person['开始日期']}")
        if person.get('+1'):
            lines.append(f"汇报给：{person['+1']}")
        if person.get('法律状态'):
            lines.append(f"合同类型：{person['法律状态']}")
        if person.get('学历'):
            lines.append(f"学历：{person['学历']}")

        # 联系信息（HR 可见）
        if is_hr:
            if person.get('手机号'):
                lines.append(f"手机：{person['手机号']}")
            if person.get('邮箱'):
                lines.append(f"邮箱：{person['邮箱']}")

        if is_hr:
            lines.append("")
            lines.append("── HR专属信息 ──")
            if person.get('月薪'):
                lines.append(f"月薪：{person['月薪']} 元")
            if person.get('日薪'):
                lines.append(f"日薪：{person['日薪']} 元")
            if person.get('年薪'):
                lines.append(f"年薪：{person['年薪']} 元")
            if person.get('到手工资'):
                lines.append(f"到手工资：{person['到手工资']} 元")
            if person.get('用人成本'):
                lines.append(f"用人成本：{person['用人成本']} 元")
            if person.get('身份证号'):
                lines.append(f"身份证：{person['身份证号']}")
            if person.get('收款银行'):
                lines.append(f"收款银行：{person['收款银行']}")
            if person.get('收款卡号'):
                lines.append(f"收款卡号：{person['收款卡号']}")
            if person.get('收款银行预留手机号'):
                lines.append(f"预留手机：{person['收款银行预留手机号']}")
            if person.get('合同'):
                lines.append(f"合同文件：{person['合同']}")

        return "\n".join(lines)
    
    def search(self, keyword: str, is_hr: bool = False) -> str:
        """通用搜索"""
        keyword = keyword.strip().lower()
        if not keyword:
            return "请输入搜索关键词"

        # 先尝试精确匹配姓名
        person = self.query_by_name(keyword)
        if person:
            return self.format_person_info(person, is_hr=is_hr)

        # 尝试职位匹配
        by_position = self.query_by_position(keyword)
        if by_position:
            results = [f"找到 {len(by_position)} 个'{keyword}'相关职位的人员："]
            for p in by_position[:10]:
                name = p.get('姓名', 'N/A')
                pos = p.get('合同职务', 'N/A')
                status = p.get('工作状态', '')
                results.append(f"- {name} | {pos} | {status}")
            if len(by_position) > 10:
                results.append(f"...还有 {len(by_position) - 10} 人")
            return "\n".join(results)

        # 尝试工作类型匹配
        by_type = self.query_by_work_type(keyword)
        if by_type:
            results = [f"找到 {len(by_type)} 个'{keyword}'类型的人员："]
            for p in by_type[:10]:
                name = p.get('姓名', 'N/A')
                pos = p.get('合同职务', 'N/A')
                status = p.get('工作状态', '')
                results.append(f"- {name} | {pos} | {status}")
            return "\n".join(results)

        return f"未找到与'{keyword}'相关的人员信息"

# 初始化名册管理器
roster_manager = None

def init_roster(roster_file: str = "roster.json"):
    """初始化名册管理器"""
    global roster_manager
    roster_manager = RosterManager(roster_file)
    return roster_manager

def query_member(keyword: str, is_hr: bool = False) -> str:
    """查询成员信息"""
    global roster_manager
    if roster_manager is None:
        init_roster()
    return roster_manager.search(keyword, is_hr=is_hr)

def get_roster_stats() -> str:
    """获取名册统计"""
    global roster_manager
    if roster_manager is None:
        init_roster()

    stats = roster_manager.get_statistics()
    lines = ["【人员统计】"]
    lines.append(f"总人数：{stats['total']} 人")
    lines.append(f"")
    lines.append(f"按状态：")
    lines.append(f"  在职：{stats['在职']} 人")
    lines.append(f"  离职归档：{stats['离职归档']} 人")
    lines.append(f"")
    lines.append(f"按类型：")
    lines.append(f"  全职：{stats['全职']} 人")
    lines.append(f"  实习：{stats['实习']} 人")
    lines.append(f"  兼职：{stats['兼职']} 人")
    lines.append(f"  顾问：{stats['顾问']} 人")
    lines.append(f"  代发：{stats['代发']} 人")
    lines.append(f"  劳务：{stats['劳务']} 人")
    return "\n".join(lines)

def query_roster_detail(work_type: str = "", status: str = "在职") -> str:
    """
    按工作类型和状态查询详细人员列表（供LLM工具调用）
    work_type: 全职/实习/兼职/顾问/代发/劳务，空则不限
    status: 在职/离职归档，空则不限
    """
    global roster_manager
    if roster_manager is None:
        init_roster()

    results = []
    for row in roster_manager.data[1:]:
        wt = roster_manager._get_field(row, "工作类型")
        st = roster_manager._get_field(row, "工作状态")
        name = roster_manager._get_field(row, "姓名") or roster_manager._get_field(row, "人员")
        if not name:
            continue
        if work_type and work_type not in wt:
            continue
        if status and status not in st:
            continue
        pos = roster_manager._get_field(row, "合同职务")
        manager = roster_manager._get_field(row, "+1")
        results.append({
            "姓名": name,
            "工作类型": wt,
            "职务": pos,
            "工作状态": st,
            "汇报给": manager,
        })

    if not results:
        desc = f"{work_type or '全部'}类型" + (f"/{status}" if status else "")
        return f"没有找到符合条件的人员（{desc}）"

    type_desc = work_type or "全部"
    status_desc = f"（{status}）" if status else ""
    lines = [f"【{type_desc}人员{status_desc}，共 {len(results)} 人】"]
    for p in results:
        line = f"• {p['姓名']}"
        if p['职务']:
            line += f" | {p['职务']}"
        if p['汇报给']:
            line += f" | 汇报给 {p['汇报给']}"
        lines.append(line)
    return "\n".join(lines)

def get_roster_stats() -> str:
    """获取名册统计"""
    global roster_manager
    if roster_manager is None:
        init_roster()

    stats = roster_manager.get_statistics()
    lines = ["【人员统计】"]
    lines.append(f"总人数：{stats['total']} 人")
    lines.append(f"")
    lines.append(f"按状态：")
    lines.append(f"  在职：{stats['在职']} 人")
    lines.append(f"  离职归档：{stats['离职归档']} 人")
    lines.append(f"")
    lines.append(f"按类型：")
    lines.append(f"  全职：{stats['全职']} 人")
    lines.append(f"  实习：{stats['实习']} 人")
    lines.append(f"  兼职：{stats['兼职']} 人")
    lines.append(f"  顾问：{stats['顾问']} 人")
    lines.append(f"  代发：{stats['代发']} 人")
    lines.append(f"  劳务：{stats['劳务']} 人")
    return "\n".join(lines)


# ─── 字段别名映射 ───────────────────────────────────────────────────────────────

FIELD_ALIASES: Dict[str, str] = {
    "姓名": "姓名", "名字": "姓名",
    "职务": "合同职务", "岗位": "合同职务", "职位": "合同职务", "合同职务": "合同职务",
    "工作类型": "工作类型", "类型": "工作类型", "雇佣类型": "工作类型",
    "工作状态": "工作状态", "状态": "工作状态",
    "部门": "部门", "团队": "部门",
    "汇报给": "汇报给", "上级": "汇报给", "直接上级": "汇报给",
    "薪资": "薪资", "工资": "薪资", "月薪": "薪资",
    "入职日期": "入职日期", "入职时间": "入职日期",
    "离职日期": "离职日期", "离职时间": "离职日期",
    "身份证": "身份证号码", "身份证号": "身份证号码", "身份证号码": "身份证号码",
    "邮箱": "邮箱", "工作邮箱": "邮箱",
    "手机": "手机号", "电话": "手机号", "手机号": "手机号",
    "银行卡": "银行卡号", "银行卡号": "银行卡号",
    "开户行": "开户行",
}


def update_member(name: str, field: str, value: str) -> str:
    """
    更新名册中某成员的字段值，并持久化到 roster.json。
    name : 成员姓名
    field: 字段名（支持中文别名，如"职位"→"合同职务"）
    value: 新的字段值
    """
    global roster_manager
    if roster_manager is None:
        init_roster()

    # 解析字段别名
    real_field = FIELD_ALIASES.get(field, field)
    if real_field not in roster_manager.headers:
        return f"❌ 未知字段：{field}（可用字段：{', '.join(FIELD_ALIASES.keys())}）"

    col_idx = roster_manager.headers.index(real_field)

    # 找到对应行（优先在职记录）
    target_row_idx = None
    name_lower = name.strip().lower()
    for i, row in enumerate(roster_manager.data[1:], start=1):
        row_name = roster_manager._get_field(row, "姓名").lower()
        row_member = roster_manager._get_field(row, "人员").lower()
        candidate = row_name or row_member
        if not candidate:
            continue
        if name_lower in candidate or candidate in name_lower:
            status = roster_manager._get_field(row, "工作状态")
            if "在职" in status:
                target_row_idx = i
                break
            if target_row_idx is None:
                target_row_idx = i

    if target_row_idx is None:
        return f"❌ 未找到成员：{name}"

    # 更新内存数据（补齐行长度）
    row = roster_manager.data[target_row_idx]
    while len(row) <= col_idx:
        row.append("")
    old_value = row[col_idx]
    row[col_idx] = value

    # 持久化到 roster.json
    try:
        roster_file = roster_manager.roster_file
        with open(roster_file, 'w', encoding='utf-8') as f:
            json.dump(roster_manager.data, f, ensure_ascii=False, indent=2)
        return f"✅ 已将 {name} 的「{real_field}」从「{old_value}」更新为「{value}」"
    except Exception as e:
        # 写入失败时回滚内存
        row[col_idx] = old_value
        return f"❌ 更新失败（写入文件出错）：{e}"
