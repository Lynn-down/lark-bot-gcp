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
        """根据姓名查询人员信息"""
        name = name.strip().lower()
        for row in self.data[1:]:  # 跳过表头
            row_name = self._get_field(row, "姓名").lower()
            # 支持中英文名称匹配
            if name in row_name or row_name in name:
                return self._row_to_dict(row)
        return None
    
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
    
    def format_person_info(self, person: Dict) -> str:
        """格式化人员信息"""
        lines = []
        lines.append(f"【{person.get('姓名', 'N/A')}】")
        
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
        
        return "\n".join(lines)
    
    def search(self, keyword: str) -> str:
        """通用搜索"""
        keyword = keyword.strip().lower()
        if not keyword:
            return "请输入搜索关键词"
        
        # 先尝试精确匹配姓名
        person = self.query_by_name(keyword)
        if person:
            return self.format_person_info(person)
        
        # 尝试职位匹配
        by_position = self.query_by_position(keyword)
        if by_position:
            results = [f"找到 {len(by_position)} 个'{keyword}'相关职位的人员："]
            for p in by_position[:10]:  # 最多显示10个
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

def query_member(keyword: str) -> str:
    """查询成员信息"""
    global roster_manager
    if roster_manager is None:
        init_roster()
    return roster_manager.search(keyword)

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
