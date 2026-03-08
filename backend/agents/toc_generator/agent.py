"""Rule-based TOC generator agent for V1 skeleton."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from backend.models.schemas import RequirementDocument, RequirementSubsystem, TOCDocument, TOCNode


class TOCGeneratorAgent:
    """Generate engineering-style TOC with stable node_uid values."""

    _HEADING_PARAGRAPH_PATTERN = re.compile(r"^heading_l(?P<level>[1-4])_(?P<order>\d+)$")
    _GENERIC_PHASE_TITLES = {"实施范围与目标", "实施准备与条件确认", "系统优化与实施", "联调测试与验收"}
    _PHASE_SPECS = (
        ("scope_goal", "实施范围与目标"),
        ("prep", "实施准备与条件确认"),
        ("implement", "系统优化与实施"),
        ("acceptance", "联调测试与验收"),
    )

    _LEVEL4_CHILDREN: dict[str, list[str]] = {
        "scope_goal": ["现状梳理与边界确认", "目标分解与实施方案细化"],
        "prep": ["现场勘察与施工条件确认", "资源准备与进度计划编排"],
        "implement": ["功能优化与参数配置实施", "接口联调与系统验证"],
        "acceptance": ["联调测试与问题整改", "验收交付与运行切换"],
    }

    def generate(self, *, requirement: RequirementDocument, version_no: int) -> TOCDocument:
        engineering_doc = self._build_engineering_outline_toc(requirement)
        if engineering_doc is not None:
            return TOCDocument(version=version_no, based_on_version=None, tree=[engineering_doc])

        outline_doc = self._build_outline_toc(requirement)
        if outline_doc is not None:
            return TOCDocument(version=version_no, based_on_version=None, tree=[outline_doc])

        root = TOCNode(
            node_uid="uid_root_001",
            node_id="1",
            level=1,
            title="工程实施方案",
            is_generation_unit=False,
            children=[],
        )

        for index, subsystem in enumerate(requirement.scope.subsystems, start=1):
            level2_node = self._build_subsystem_node(subsystem=subsystem, index=index)
            root.children.append(level2_node)

        if not root.children:
            root.children.append(self._build_fallback_node(requirement))

        return TOCDocument(version=version_no, based_on_version=None, tree=[root])

    def _build_engineering_outline_toc(self, requirement: RequirementDocument) -> TOCNode | None:
        if not self._should_use_engineering_outline(requirement):
            return None

        root = TOCNode(
            node_uid="uid_root_001",
            node_id="1",
            level=1,
            title="工程实施方案",
            is_generation_unit=False,
            source_refs=self._match_source_refs(requirement, ["项目内容", "系统技术要求", "相关标准规范"]),
            children=[],
        )

        for chapter_index, chapter_spec in enumerate(self._engineering_outline_specs(requirement), start=1):
            chapter_title, chapter_keywords, sections = chapter_spec
            chapter_refs = self._match_source_refs(requirement, chapter_keywords)
            chapter_node = TOCNode(
                node_uid=self._stable_uid("l2", f"chapter::{chapter_index}::{self._normalize_token(chapter_title)}"),
                node_id=f"1.{chapter_index}",
                level=2,
                title=chapter_title,
                is_generation_unit=False,
                source_refs=chapter_refs,
                children=[],
            )

            for section_index, (section_title, leaf_titles) in enumerate(sections, start=1):
                section_refs = self._match_source_refs(
                    requirement,
                    [section_title, *leaf_titles[:2]],
                    fallback=chapter_refs,
                )
                section_node = TOCNode(
                    node_uid=self._stable_uid(
                        "l3",
                        f"{chapter_node.node_uid}::section::{section_index}::{self._normalize_token(section_title)}",
                    ),
                    node_id=f"{chapter_node.node_id}.{section_index}",
                    level=3,
                    title=section_title,
                    is_generation_unit=False,
                    source_refs=section_refs,
                    children=[],
                )

                for leaf_index, leaf_title in enumerate(leaf_titles, start=1):
                    leaf_refs = self._match_source_refs(
                        requirement,
                        [leaf_title, section_title],
                        fallback=section_refs,
                    )
                    section_node.children.append(
                        TOCNode(
                            node_uid=self._stable_uid(
                                "l4",
                                f"{section_node.node_uid}::leaf::{leaf_index}::{self._normalize_token(leaf_title)}",
                            ),
                            node_id=f"{section_node.node_id}.{leaf_index}",
                            level=4,
                            title=leaf_title,
                            is_generation_unit=True,
                            constraints=self._generation_constraints(),
                            source_refs=leaf_refs,
                            children=[],
                        )
                    )

                chapter_node.children.append(section_node)

            root.children.append(chapter_node)

        return root

    def _should_use_engineering_outline(self, requirement: RequirementDocument) -> bool:
        texts = [item.text for _, item in sorted(requirement.source_index.items(), key=lambda pair: self._line_no_from_source_ref(pair[0]))]
        signals = 0
        keyword_groups = [
            ("项目内容", "系统技术要求"),
            ("空压机余热回收系统", "水源热泵"),
            ("闪蒸汽", "乏汽"),
            ("冷凝水", "热力站"),
            ("空气源热泵",),
            ("板式换热器", "水箱"),
            ("电控系统技术要求", "PLC"),
            ("上位系统",),
        ]
        merged = "\n".join(texts)
        for keywords in keyword_groups:
            if any(keyword in merged for keyword in keywords):
                signals += 1
        core_sections = sum(
            1
            for keywords in (
                ("项目内容",),
                ("标准", "规范"),
                ("技术要求",),
                ("验收",),
            )
            if any(keyword in merged for keyword in keywords)
        )
        return signals >= 5 or (core_sections >= 3 and any(token in merged for token in ("系统", "热泵", "换热器", "控制")))

    def _engineering_outline_specs(
        self,
        requirement: RequirementDocument,
    ) -> list[tuple[str, list[str], list[tuple[str, list[str]]]]]:
        texts = self._source_texts(requirement)
        merged = "\n".join(texts)

        def has_any(*keywords: str) -> bool:
            return any(keyword in merged for keyword in keywords)

        specs: list[tuple[str, list[str], list[tuple[str, list[str]]]]] = []

        specs.append(
            (
                "项目理解与建设目标",
                ["项目内容", "提升工厂生产余热回收率", "满足生产需求", "联动控制"],
                [
                    ("项目背景与建设范围", ["项目建设背景", "项目建设范围", "项目涉及系统与专业边界"]),
                    ("建设目标", ["运行保障目标", "节能降耗目标", "自动化与集成目标"]),
                    ("项目实施边界", ["本次改造实施范围", "设备供货边界", "安装施工边界"]),
                    ("改造原则与总体思路", ["利旧与更新结合原则", "分系统改造与整体协同原则", "安全可靠与节能高效并重原则"]),
                    ("对招标需求的响应说明", ["对项目建设内容的响应", "对设备技术要求的响应", "对安装调试与验收要求的响应"]),
                ],
            )
        )

        if has_any("新建", "更新", "购置并安装", "优化", "改造"):
            specs.append(
                (
                    "项目建设内容总述",
                    ["项目内容", "新建", "更新", "优化", "购置并安装"],
                    [
                        ("新建系统范围", self._pick_titles(
                            texts,
                            ["空压机余热回收系统", "乏汽余热回收系统", "水箱换热系统", "热分层储能装置", "空气源热泵"],
                            ["空压机余热回收系统", "乏汽余热回收系统", "水箱换热系统"],
                        )),
                        ("更新改造范围", self._pick_titles(
                            texts,
                            ["空气源热泵系统更新", "管壳式换热器更新", "原有系统优化改造", "空压机群控系统优化", "太阳能余热回收控制系统优化"],
                            ["空气源热泵系统更新", "管壳式换热器更新", "原有系统优化改造"],
                        )),
                        ("新增设备与主要配置", ["热泵、换热器与储能装置配置", "循环水泵与阀门仪表配置", "配套电控及线缆桥架配置"]),
                        ("改造后总体功能目标", ["余热回收能力提升目标", "热水系统稳定运行目标", "上位系统集成与集中监控目标"]),
                    ],
                )
            )

        if has_any("相关标准规范", "设计安装标准", "验收标准", "消防", "特种设备"):
            specs.append(
                (
                    "设计依据与执行标准",
                    ["相关标准规范", "设计安装标准", "验收标准", "安全", "消防", "环保", "特种设备"],
                    [
                        ("国家及行业规范", ["烟草行业相关规范", "特种设备与安全生产规范", "建筑节能与消防规范"]),
                        ("设计安装标准", ["设备安装与抗震设计标准", "管道焊接与绝热设计标准", "电缆与供配电设计标准"]),
                        ("验收标准", ["自动化与仪表工程验收标准", "电气安装与设备交接验收标准", "管道与绝热工程验收标准"]),
                        ("安全、消防、环保要求", ["安全施工与运行要求", "消防与防火要求", "环保与规范达标要求"]),
                        ("特种设备合规要求", ["压力容器安装告知要求", "使用登记与报检要求", "制造安装资质要求"]),
                    ],
                )
            )

        if has_any("拆除内容", "保护性拆除", "搬迁", "移装"):
            specs.append(
                (
                    "现场现状与拆除迁改方案",
                    ["拆除内容", "保护性拆除", "搬迁", "移装"],
                    [
                        ("现场现状分析", ["制丝屋顶现状分析", "热力站现状分析", "空压站现状分析"]),
                        ("拆除范围说明", ["制丝屋顶空气源热泵拆除", "热力站管式换热器拆除", "闪蒸汽换热装置拆除"]),
                        ("配套拆除与搬迁要求", ["太阳能循环水泵拆除", "空压站循环水泵及配套设施保护性拆除", "拆除设备搬迁至指定位置"]),
                        ("设备搬迁与利旧方案", ["原有循环水泵利旧方案", "原有电缆仪表利旧方案", "原有控制系统资源利旧方案"]),
                        ("拆除后恢复措施", ["管道阀门及保温恢复措施", "土建恢复与基础外观协调措施", "成品保护与现场清理措施"]),
                    ],
                )
            )

        if has_any("系统技术要求", "余热回收", "联动控制", "上位系统"):
            specs.append(
                (
                    "总体技术方案",
                    ["系统技术要求", "余热回收", "空气源热泵", "太阳能", "联动控制"],
                    [
                        ("系统总体架构", ["热源侧系统架构", "用户侧系统架构", "自控与监控系统架构"]),
                        ("热源综合利用逻辑", ["空压机余热利用逻辑", "闪蒸汽与冷凝水余热利用逻辑", "太阳能与空气源热泵协同利用逻辑"]),
                        ("各子系统耦合关系", ["热泵与储能装置耦合关系", "热水箱与换热系统耦合关系", "余热回收系统与上位监控耦合关系"]),
                        ("工艺流程设计", ["空压机余热回收工艺流程", "乏汽与冷凝水回收工艺流程", "热水换热与供热工艺流程"]),
                        ("系统运行模式", ["正常运行模式", "优先级切换模式", "联动控制模式"]),
                        ("系统节能与效率提升分析", ["节能机理分析", "运行效率提升路径", "综合效益分析"]),
                    ],
                )
            )

        if has_any("空压机余热回收系统", "水源热泵", "热分层储能装置"):
            specs.append(
                (
                    "空压机余热回收系统方案",
                    ["空压机余热回收系统", "水源热泵", "热分层储能装置", "空压机冷却水"],
                    [
                        ("系统组成", ["热源侧设备组成", "储热与换热设备组成", "用户侧循环设备组成"]),
                        ("水源热泵机组配置方案", ["设计工况与性能参数", "冷媒、启动柜与机组配置", "通讯接口与控制显示要求"]),
                        ("热分层储能装置方案", ["结构形式与材质要求", "分层储热功能设计", "安装尺寸与基础协调要求"]),
                        ("用户侧循环系统方案", ["循环水泵配置方案", "管路与阀门配置方案", "仪表与热量计配置方案"]),
                        ("换热与储热逻辑", ["余热回收换热逻辑", "储能装置充放热逻辑", "热量平衡与温度分层控制逻辑"]),
                        ("与空压机冷却系统联动方案", ["冷却方式自动切换逻辑", "余热消纳不足时散热保障逻辑", "系统稳定运行保障措施"]),
                        ("运行控制策略", ["自动与手动控制策略", "联动启停与热切换策略", "运行监测与报警策略"]),
                    ],
                )
            )

        if has_any("乏汽", "闪蒸汽", "回收装置"):
            specs.append(
                (
                    "乏汽余热回收系统方案",
                    ["乏汽", "闪蒸汽", "回收装置", "压力容器"],
                    [
                        ("闪蒸汽回收装置方案", ["设计工况与换热参数", "结构形式与材质要求", "压降、寿命与资质要求"]),
                        ("设计工况与参数校核", ["热侧工况参数校核", "冷侧工况参数校核", "系统换热能力校核"]),
                        ("材质与寿命设计", ["管程与壳程材质要求", "耐温耐压性能要求", "使用寿命保障措施"]),
                        ("压力容器合规要求", ["制造资质要求", "安装告知要求", "使用登记要求"]),
                        ("安装布置方案", ["屋顶设备布置原则", "配套管路与阀门布置", "检修维护空间预留"]),
                        ("运行控制方案", ["温度检测与自动启停逻辑", "系统运行联动逻辑", "运行安全保障措施"]),
                    ],
                )
            )

        if has_any("冷凝水", "热力站", "管式换热器"):
            specs.append(
                (
                    "冷凝水余热回收及热力站改造方案",
                    ["冷凝水", "热力站", "管式换热器"],
                    [
                        ("管式换热器更换方案", ["设备选型与品牌档次要求", "设计工况与参数要求", "结构材质与压降要求"]),
                        ("热力站系统接入方案", ["系统接口与接入边界", "管路阀门与仪表接入方案", "热力站平台安装协调方案"]),
                        ("共用循环泵运行方案", ["共泵运行逻辑", "原有水泵利旧方案", "电缆及控制接入方案"]),
                        ("温度检测与自动启停逻辑", ["热侧温度检测策略", "自动启停控制逻辑", "异常工况处理逻辑"]),
                        ("热量计量与监测方案", ["热能表配置方案", "热量数据采集方案", "热量统计与分析方案"]),
                    ],
                )
            )

        if has_any("空气源热泵"):
            specs.append(
                (
                    "空气源热泵系统方案",
                    ["空气源热泵", "除霜", "防冻", "光照度"],
                    [
                        ("设备选型与数量配置", ["设备数量与分组配置", "品牌档次与压缩机要求", "主机功能与防护等级要求"]),
                        ("设计工况说明", ["制热工况参数", "运行环境适应性要求", "最高出水温度要求"]),
                        ("分组控制策略", ["两组热泵分组控制方案", "按温度分级启停逻辑", "逐台减载退出逻辑"]),
                        ("冬季除霜与防冻设计", ["自动除霜功能设计", "自动防冻功能设计", "冬季稳定运行保障措施"]),
                        ("与太阳能及水源热泵协同控制", ["多热源优先级控制逻辑", "热水温度不足时补热逻辑", "与现有PLC系统协同控制逻辑"]),
                        ("安装与利旧衔接方案", ["原循环水泵利旧方案", "原供电电缆利旧方案", "新增热能表及电缆配置方案"]),
                    ],
                )
            )

        if has_any("水箱换热", "板式换热器", "热水箱", "电动调节阀"):
            specs.append(
                (
                    "水箱换热及热水系统平衡方案",
                    ["水箱换热", "板式换热器", "热水箱", "电动调节阀"],
                    [
                        ("制丝与卷包水箱换热逻辑", ["水箱之间热量平衡需求", "换热联动控制逻辑", "温差驱动运行逻辑"]),
                        ("板式换热器配置方案", ["设备选型与性能参数", "板片材质与承压要求", "品牌档次与安装要求"]),
                        ("水温平衡控制策略", ["温差检测策略", "水温平衡调节策略", "热水供应稳定性保障策略"]),
                        ("循环泵与阀门控制方案", ["循环泵控制方案", "电动阀配置方案", "联动启停与调节逻辑"]),
                        ("系统运行工况说明", ["正常运行工况", "峰值补热工况", "异常工况处理方式"]),
                    ],
                )
            )

        if has_any("同等档次", "技术要求", "品牌", "参数"):
            specs.append(
                (
                    "主要设备技术响应",
                    ["技术要求", "品牌", "档次", "参数", "配置"],
                    [
                        ("水源热泵技术响应", ["设计工况与性能响应", "机组配置与控制响应", "品牌档次与接口响应"]),
                        ("空气源热泵技术响应", ["工况参数与运行环境响应", "主机功能与自控接入响应", "品牌档次与核心部件响应"]),
                        ("闪蒸汽回收装置技术响应", ["换热性能响应", "结构材质响应", "压力容器资质响应"]),
                        ("管式换热器技术响应", ["换热能力响应", "安装空间与检修条件响应", "材质寿命与资质响应"]),
                        ("板式换热器技术响应", ["换热能力与工况响应", "板片材质与承压响应", "品牌档次响应"]),
                        ("循环水泵技术响应", ["立式泵技术响应", "卧式泵技术响应", "能效、防护与材质响应"]),
                        ("热分层储能装置技术响应", ["容积材质与结构响应", "温度分层与监测响应", "安装尺寸与基础协调响应"]),
                        ("配套仪表与附件技术响应", ["温度压力液位仪表响应", "热能表与光照度传感器响应", "电动阀与调节阀响应"]),
                    ],
                )
            )

        if has_any("管道技术要求", "阀门技术要求", "支架及支座技术要求", "保温技术要求"):
            specs.append(
                (
                    "管道、阀门、支架及保温方案",
                    ["管道技术要求", "阀门技术要求", "支架及支座技术要求", "保温技术要求"],
                    [
                        ("管道材料与连接工艺", ["不锈钢管材要求", "管件法兰与垫片要求", "焊接与法兰连接工艺要求"]),
                        ("阀门选型与配置方案", ["通用阀门选型要求", "特殊阀门选型要求", "阀门压力等级与材质要求"]),
                        ("支吊架与设备支座方案", ["管道支吊架制作安装要求", "图集标准执行要求", "设备支座与U型抱箍支座要求"]),
                        ("保温材料与外护层方案", ["设备保温方案", "热水管道保温方案", "外保护层配置方案"]),
                        ("排气、泄水与过滤措施", ["自动排气与泄水设置要求", "过滤器配置要求", "阀门检修可达性要求"]),
                        ("安装工艺与质量控制", ["支架防腐与保温外置要求", "施工质量控制要求", "现场安装协调要求"]),
                    ],
                )
            )

        if has_any("电控系统技术要求", "PLC", "桥架", "电缆", "启动柜", "自动与手动控制", "联动控制"):
            specs.append(
                (
                    "电气与自控系统方案",
                    ["电控系统技术要求", "PLC", "桥架", "电缆", "启动柜", "自动与手动控制", "联动控制"],
                    [
                        ("电控系统总体设计", ["系统组成与控制层级", "设计原则与总体要求", "控制模式与功能目标"]),
                        ("空压站PLC改造方案", ["新增设备控制模块配置", "触摸屏更换与画面重构", "水源热泵联动与冷却切换逻辑"]),
                        ("太阳能余热控制系统优化方案", ["制丝卷包统一画面风格优化", "多子系统统一接入优化", "生产管理需求适配优化"]),
                        ("空气源热泵组态与集控方案", ["两组热泵集控器配置方案", "PLC组态编程方案", "分组启停与温度联动方案"]),
                        ("光照度联动控制方案", ["光照度传感器配置方案", "太阳能循环泵联动控制逻辑", "光照度显示与设定功能"]),
                        ("闪蒸汽与冷凝水回收自控方案", ["闪蒸汽回收系统控制方案", "冷凝水回收换热控制方案", "共用循环泵控制方案"]),
                        ("电动阀与调节阀控制方案", ["电动阀控制方案", "电动调节阀控制方案", "阀门位置反馈与联锁逻辑"]),
                        ("通讯协议与系统接口方案", ["现有PLC品牌与协议适配", "EtherNet/IP通讯接入方案", "光纤通信与系统互联方案"]),
                        ("启动柜与控制柜方案", ["柜体结构与散热设计", "电气元件选型要求", "图纸配置与柜内布置要求"]),
                        ("数据采集、报警、报表与曲线功能", ["数据采集记录功能", "报表曲线与统计分析功能", "预警报警与故障诊断功能"]),
                    ],
                )
            )

        if has_any("上位系统集成要求", "上位系统", "远程监控", "远程操作"):
            specs.append(
                (
                    "上位系统集成方案",
                    ["上位系统集成要求", "上位系统", "远程监控", "远程操作"],
                    [
                        ("集成范围", ["空压机余热回收系统集成", "太阳能系统集成", "相关子系统数据接入范围"]),
                        ("远程监控与操作功能", ["远程监视功能", "远程操作功能", "权限与安全控制要求"]),
                        ("数据接口与通讯架构", ["控制层与监控层接口关系", "数据采集传输架构", "系统通信可靠性保障措施"]),
                        ("画面统一与组态设计", ["制丝卷包统一风格设计", "系统主画面与子画面设计", "操作与监视界面设计要求"]),
                        ("源文件开放与可扩展性说明", ["控制系统源文件开放要求", "后续扩展与升级能力要求", "第三方系统接入兼容性要求"]),
                    ],
                )
            )

        if has_any("安装", "施工", "基础", "工期", "吊装"):
            specs.append(
                (
                    "施工组织与实施方案",
                    ["设备基础", "安装", "施工", "特种设备", "工期"],
                    [
                        ("施工总体部署", ["施工组织原则", "施工阶段划分", "现场资源配置计划"]),
                        ("设备基础施工方案", ["新建设备基础施工要求", "基础尺寸与外观协调要求", "基础施工质量控制要求"]),
                        ("设备安装方案", ["热泵及换热设备安装方案", "储能装置安装方案", "水泵及附属设备安装方案"]),
                        ("管道安装方案", ["管道预制与安装工艺", "阀门法兰与支架安装工艺", "保温与外护层安装工艺"]),
                        ("电气仪表安装方案", ["电缆桥架安装方案", "仪表安装与接线方案", "控制柜与现场设备接电方案"]),
                        ("高空与屋顶作业措施", ["屋顶设备施工措施", "高空吊装安全措施", "交叉作业防护措施"]),
                        ("特种设备报装与登记配合", ["安装告知手续办理", "检验检测配合工作", "使用登记证办理配合"]),
                        ("施工进度计划", ["施工节点安排", "关键线路控制措施", "工期保障措施"]),
                    ],
                )
            )

        if has_any("验收", "调试", "试运行"):
            specs.append(
                (
                    "调试、试运行与验收方案",
                    ["验收标准", "调试", "试运行", "验收"],
                    [
                        ("单机调试", ["热泵与换热设备单机调试", "水泵与阀门单机调试", "仪表与控制柜单机调试"]),
                        ("分系统调试", ["空压机余热回收系统调试", "乏汽与冷凝水回收系统调试", "水箱换热与空气源热泵系统调试"]),
                        ("联动调试", ["多热源协同联动调试", "PLC与上位系统联动调试", "异常工况联动调试"]),
                        ("试运行方案", ["试运行组织方式", "试运行监测内容", "试运行问题整改机制"]),
                        ("验收标准与验收流程", ["设备安装验收", "系统功能验收", "资料与手续验收"]),
                        ("竣工资料交付", ["竣工图纸交付", "技术文档与源文件交付", "验收资料与台账交付"]),
                    ],
                )
            )

        if has_any("安全", "消防", "环保", "应急", "质量"):
            specs.append(
                (
                    "质量、安全、环保保障措施",
                    ["质量", "安全", "消防", "环保", "应急"],
                    [
                        ("质量保证体系", ["质量管理组织体系", "质量控制流程", "关键工序质量保障措施"]),
                        ("安全施工措施", ["施工安全管理措施", "设备吊装与用电安全措施", "现场应急处置措施"]),
                        ("消防保障措施", ["施工现场消防措施", "屋顶及机房消防风险控制措施", "动火作业消防管理措施"]),
                        ("环保与文明施工措施", ["施工噪声与废弃物控制措施", "现场文明施工措施", "环境保护达标措施"]),
                        ("风险识别与应急预案", ["施工风险识别", "运行风险识别", "应急预案与响应机制"]),
                    ],
                )
            )

        if has_any("培训", "维护", "售后", "服务", "维保"):
            specs.append(
                (
                    "培训、售后与服务承诺",
                    ["培训", "服务", "售后", "维护"],
                    [
                        ("培训方案", ["操作培训方案", "维护培训方案", "培训资料与考核方案"]),
                        ("维保服务方案", ["例行巡检与维护方案", "关键设备维保方案", "预防性维护方案"]),
                        ("故障响应机制", ["故障分级响应机制", "现场处置响应机制", "远程支持响应机制"]),
                        ("备品备件与技术支持", ["常用备件配置方案", "紧急备件保障方案", "长期技术支持方案"]),
                        ("服务承诺", ["质量保修承诺", "响应时效承诺", "持续优化服务承诺"]),
                    ],
                )
            )

        if has_any("招标", "同等档次", "偏差", "响应"):
            specs.append(
                (
                    "技术偏差表与响应表",
                    ["技术要求", "响应", "品牌", "参数"],
                    [
                        ("技术条款逐条响应", ["项目内容条款响应", "技术要求条款响应", "安装调试条款响应"]),
                        ("品牌与档次响应", ["主机设备品牌响应", "配套设备品牌响应", "电气自控品牌响应"]),
                        ("关键参数响应", ["热泵与换热器参数响应", "水泵与储能装置参数响应", "仪表阀门与电控参数响应"]),
                        ("偏差说明", ["正偏离说明", "等效替代说明", "无偏差承诺说明"]),
                    ],
                )
            )

        if has_any("主要材料清单", "材料清单", "图纸", "样本", "资料"):
            specs.append(
                (
                    "附件",
                    ["主要材料清单", "工艺流程", "控制逻辑", "标准规范"],
                    [
                        ("主要设备参数表", ["热泵与换热器参数表", "水泵与储能装置参数表", "仪表阀门与电控参数表"]),
                        ("主要材料配置表", ["管道材料配置表", "电缆桥架配置表", "保温与附件配置表"]),
                        ("工艺流程图", ["空压机余热回收流程图", "乏汽与冷凝水回收流程图", "水箱换热与热水系统流程图"]),
                        ("系统控制逻辑说明", ["热泵联动控制逻辑说明", "多热源优先级控制逻辑说明", "上位系统监控逻辑说明"]),
                        ("施工平面与布置示意", ["屋顶设备布置示意", "空压站设备布置示意", "热力站设备布置示意"]),
                        ("其他支撑资料", ["标准规范索引", "设备样本与证明资料", "其他技术支撑文件"]),
                    ],
                )
            )

        return specs

    def _match_source_refs(
        self,
        requirement: RequirementDocument,
        keywords: list[str],
        *,
        fallback: list[str] | None = None,
        limit: int = 10,
    ) -> list[str]:
        source_refs: list[str] = []
        normalized_keywords = [self._clean_title(keyword) for keyword in keywords if keyword]
        for source_ref, item in sorted(
            requirement.source_index.items(),
            key=lambda pair: self._line_no_from_source_ref(pair[0]),
        ):
            text = self._clean_title(item.text)
            if any(keyword and keyword in text for keyword in normalized_keywords):
                source_refs.append(source_ref)
            if len(source_refs) >= limit:
                break

        if source_refs:
            return source_refs
        if fallback:
            return fallback[:limit]
        return list(requirement.source_index.keys())[:limit]

    def _source_texts(self, requirement: RequirementDocument) -> list[str]:
        return [
            item.text
            for _, item in sorted(
                requirement.source_index.items(),
                key=lambda pair: self._line_no_from_source_ref(pair[0]),
            )
        ]

    def _pick_titles(self, texts: list[str], candidates: list[str], fallback: list[str], limit: int = 3) -> list[str]:
        picked: list[str] = []
        merged = "\n".join(texts)
        for candidate in candidates:
            if candidate in merged and candidate not in picked:
                picked.append(candidate)
            if len(picked) >= limit:
                break
        if picked:
            return picked
        return fallback[:limit]

    def _build_outline_toc(self, requirement: RequirementDocument) -> TOCNode | None:
        outline_entries = self._extract_heading_entries(requirement)
        if len(outline_entries) < 2:
            return None

        level1_entries = [entry for entry in outline_entries if entry["source_level"] == 1]
        use_source_root = len(level1_entries) == 1 and any(
            entry["source_level"] > 1 for entry in outline_entries
        )

        if use_source_root:
            root_entry = level1_entries[0]
            root = TOCNode(
                node_uid="uid_root_001",
                node_id="1",
                level=1,
                title=root_entry["title"],
                is_generation_unit=False,
                source_refs=[root_entry["source_ref"]],
                children=[],
            )
            entries = [entry for entry in outline_entries if entry["source_ref"] != root_entry["source_ref"]]
            min_level = 2
        else:
            min_level = min(entry["source_level"] for entry in outline_entries)
            root = TOCNode(
                node_uid="uid_root_001",
                node_id="1",
                level=1,
                title=requirement.project.name or "工程实施方案",
                is_generation_unit=False,
                source_refs=[],
                children=[],
            )
            entries = outline_entries

        stack: list[TOCNode] = [root]
        for entry in entries:
            target_level = entry["source_level"] if use_source_root else entry["source_level"] - min_level + 2
            if target_level < 2:
                continue
            if target_level > 4:
                target_level = 4
            while len(stack) > target_level - 1:
                stack.pop()
            if target_level > len(stack) + 1:
                target_level = len(stack) + 1
            parent = stack[-1]
            node = TOCNode(
                node_uid=self._stable_uid(
                    f"l{target_level}",
                    f"{entry['source_ref']}::{self._normalize_token(entry['title'])}",
                ),
                node_id=f"{parent.node_id}.{len(parent.children) + 1}",
                level=target_level,
                title=entry["title"],
                is_generation_unit=False,
                constraints=None,
                source_refs=[entry["source_ref"]],
                children=[],
            )
            parent.children.append(node)
            stack.append(node)

        if not root.children:
            return None

        self._ensure_outline_generation_units(root)
        return root

    def _build_subsystem_node(self, *, subsystem: RequirementSubsystem, index: int) -> TOCNode:
        source_refs = self._subsystem_source_refs(subsystem)
        semantic_key = self._semantic_key(subsystem)
        requires_level4 = self._need_level4(subsystem)

        level2 = TOCNode(
            node_uid=self._stable_uid("l2", semantic_key),
            node_id=f"1.{index}",
            level=2,
            title=self._clean_title(subsystem.name),
            is_generation_unit=False,
            source_refs=source_refs,
            children=[],
        )

        for phase_index, (phase_key, phase_title) in enumerate(self._build_phase_specs(subsystem), start=1):
            phase_uid_key = f"{semantic_key}::{phase_key}"
            level3 = TOCNode(
                node_uid=self._stable_uid("l3", phase_uid_key),
                node_id=f"{level2.node_id}.{phase_index}",
                level=3,
                title=phase_title,
                is_generation_unit=not requires_level4,
                constraints=self._generation_constraints(),
                source_refs=source_refs,
                children=[],
            )

            if requires_level4:
                level3.is_generation_unit = False
                for child_index, child_title in enumerate(self._LEVEL4_CHILDREN[phase_key], start=1):
                    child_uid_key = f"{phase_uid_key}::{child_index}"
                    level4 = TOCNode(
                        node_uid=self._stable_uid("l4", child_uid_key),
                        node_id=f"{level3.node_id}.{child_index}",
                        level=4,
                        title=child_title,
                        is_generation_unit=True,
                        constraints=self._generation_constraints(),
                        source_refs=source_refs,
                        children=[],
                    )
                    level3.children.append(level4)

            level2.children.append(level3)

        return level2

    def _build_fallback_node(self, requirement: RequirementDocument) -> TOCNode:
        fallback_key = self._normalize_token(requirement.project.name or "实施专题")
        level2 = TOCNode(
            node_uid=self._stable_uid("l2", fallback_key),
            node_id="1.1",
            level=2,
            title=requirement.project.name or "实施专题",
            is_generation_unit=False,
            source_refs=list(requirement.source_index.keys())[:10],
            children=[],
        )
        for index, (_, phase_title) in enumerate(self._PHASE_SPECS, start=1):
            level2.children.append(
                TOCNode(
                    node_uid=self._stable_uid("l3", f"{fallback_key}::{index}"),
                    node_id=f"1.1.{index}",
                    level=3,
                    title=phase_title,
                    is_generation_unit=True,
                    constraints=self._generation_constraints(),
                    source_refs=level2.source_refs,
                    children=[],
                )
            )
        return level2

    def _extract_heading_entries(self, requirement: RequirementDocument) -> list[dict[str, str | int]]:
        entries: list[dict[str, str | int]] = []
        for source_ref, item in sorted(
            requirement.source_index.items(),
            key=lambda pair: self._line_no_from_source_ref(pair[0]),
        ):
            match = self._HEADING_PARAGRAPH_PATTERN.match(item.paragraph_id)
            if match is None:
                continue
            title = self._clean_title(item.text)
            if not title:
                continue
            entries.append(
                {
                    "source_ref": source_ref,
                    "source_level": int(match.group("level")),
                    "title": title,
                }
            )
        return entries

    def _ensure_outline_generation_units(self, root: TOCNode) -> None:
        self._renumber_children(root)
        for child in root.children:
            self._ensure_node_generation_units(child)

    def _ensure_node_generation_units(self, node: TOCNode) -> None:
        if node.children:
            node.is_generation_unit = False
            for child in node.children:
                self._ensure_node_generation_units(child)
            self._renumber_children(node)
            return

        if node.level >= 3:
            node.is_generation_unit = True
            node.constraints = self._generation_constraints()
            return

        node.is_generation_unit = False
        outline_specs = self._build_outline_leaf_specs(node.title)
        for phase_index, phase_title in enumerate(outline_specs, start=1):
            phase_uid_key = f"{node.node_uid}::outline::{phase_index}"
            level3 = TOCNode(
                node_uid=self._stable_uid("l3", phase_uid_key),
                node_id=f"{node.node_id}.{phase_index}",
                level=node.level + 1,
                title=phase_title,
                is_generation_unit=True,
                constraints=self._generation_constraints(),
                source_refs=node.source_refs,
                children=[],
            )
            node.children.append(level3)
        self._renumber_children(node)

    def _renumber_children(self, parent: TOCNode) -> None:
        for index, child in enumerate(parent.children, start=1):
            child.node_id = f"{parent.node_id}.{index}"
            self._renumber_children(child)

    def _build_phase_specs(self, subsystem: RequirementSubsystem) -> list[tuple[str, str]]:
        title = subsystem.name
        has_interface = any("接口" in item for item in subsystem.interfaces)
        implement_title = "系统优化与实施"
        if any(token in title for token in ("控制", "系统", "平台", "模块")):
            implement_title = f"{self._clean_title(title)}优化与实施"
        if has_interface:
            implement_title = f"{self._clean_title(title)}优化与接口联调"

        return [
            ("scope_goal", "实施范围与目标"),
            ("prep", "实施准备与条件确认"),
            ("implement", implement_title),
            ("acceptance", "联调测试与验收"),
        ]

    def _build_outline_leaf_specs(self, title: str) -> list[str]:
        cleaned_title = self._clean_title(title)
        subject = self._extract_outline_subject(cleaned_title)

        if cleaned_title == "其他":
            return [
                "补充实施要求",
                "配合条件与边界控制",
                "资料提交与后续支持要求",
            ]
        if "验收标准" in cleaned_title:
            return [
                "验收依据与判定标准",
                "功能与性能验收要求",
                "验收资料与签认要求",
            ]
        if "设计安装标准" in cleaned_title:
            return [
                "设计依据与执行标准",
                "安装工艺与质量标准",
                "安全文明与成品保护要求",
            ]
        if "拆除内容" in cleaned_title or cleaned_title.startswith("拆除"):
            return [
                "拆除范围与边界条件",
                "拆除实施与安全控制",
                "拆除后恢复与移交要求",
            ]
        if "集成要求" in cleaned_title:
            return [
                f"{subject}接口与边界要求",
                f"{subject}数据接入与联调要求",
                f"{subject}测试与交付要求",
            ]
        if "安装要求" in cleaned_title:
            return [
                f"{subject}安装范围与条件",
                f"{subject}安装工艺与质量控制",
                f"{subject}调试与验收要求",
            ]
        if "技术要求" in cleaned_title:
            return [
                f"{subject}配置与选型要求",
                f"{subject}性能与控制要求",
                f"{subject}安装与验收要求",
            ]
        if cleaned_title.endswith("要求"):
            return [
                f"{subject}实施边界与条件",
                f"{subject}关键控制要求",
                f"{subject}验收与资料要求",
            ]
        if any(token in cleaned_title for token in ("总体", "系统", "方案", "内容")):
            return [
                f"{subject}范围与目标",
                f"{subject}关键实施要求",
                f"{subject}验收与交付要求",
            ]
        return [
            f"{subject}范围与边界说明",
            f"{subject}实施与质量控制",
            f"{subject}验收与资料要求",
        ]

    def _extract_outline_subject(self, title: str) -> str:
        subject = self._clean_title(title)
        for suffix in (
            "技术要求",
            "安装要求",
            "集成要求",
            "验收标准",
            "设计安装标准",
            "功能要求",
            "实施要求",
            "要求",
        ):
            if subject.endswith(suffix) and len(subject) > len(suffix):
                subject = subject[: -len(suffix)]
                break
        subject = subject.strip("与及、 ")
        return subject or self._clean_title(title) or "本章节"

    def _need_level4(self, subsystem: RequirementSubsystem) -> bool:
        title = subsystem.name
        description = subsystem.description or ""
        requirement_count = len(subsystem.requirements)
        source_ref_count = len(self._subsystem_source_refs(subsystem))

        multi_module = any(token in title + description for token in ("及", "与", "、", "模块", "子系统"))
        broad_title = any(token in title for token in ("总体", "综合", "概述", "平台", "系统优化"))
        description_heavy = len(description.strip()) >= 40
        too_many_clauses = requirement_count >= 2 or source_ref_count >= 2

        return multi_module or broad_title or description_heavy or too_many_clauses

    def _semantic_key(self, subsystem: RequirementSubsystem) -> str:
        refs = self._subsystem_source_refs(subsystem)
        ref_part = refs[0] if refs else self._normalize_token(subsystem.name)
        return f"{ref_part}::{self._normalize_token(subsystem.name)}"

    def _subsystem_source_refs(self, subsystem: RequirementSubsystem) -> list[str]:
        refs = [item.source_ref for item in subsystem.requirements if item.source_ref]
        return refs[:10]

    def _clean_title(self, title: str) -> str:
        cleaned = re.sub(r"\s+", "", title)
        cleaned = re.sub(r"^[0-9.、\-]+", "", cleaned)
        cleaned = re.sub(r"^[（(]?[一二三四五六七八九十0-9]+[)）.、]+", "", cleaned)
        cleaned = cleaned.strip("，。；：- ")
        return cleaned or "实施专题"

    def _normalize_token(self, text: str) -> str:
        cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", self._clean_title(text))
        return cleaned[:48] or "topic"

    def _line_no_from_source_ref(self, source_ref: str) -> int:
        match = re.search(r"#L(\d+)$", source_ref)
        if match is None:
            return 0
        return int(match.group(1))

    def _stable_uid(self, level: str, seed: str) -> str:
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
        return f"uid_{level}_{digest}"

    def _generation_constraints(self) -> dict[str, Any]:
        return {
            "min_words": 1800,
            "recommended_words": [1800, 2200],
            "images": [2, 3],
        }
