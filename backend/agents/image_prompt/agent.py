"""Prompt construction for the minimal image pipeline."""

from __future__ import annotations

from typing import Any

from backend.models.schemas import EntityExtraction, ImagePromptItem, ImagePrompts, NodeText


class ImagePromptAgent:
    """Build constrained prompts with must-have and forbidden elements."""

    DEFAULT_ASPECT_RATIO = "3:2"
    _FORBIDDEN_ELEMENTS = [
        "纯装饰性背景",
        "抽象科技光效",
        "与工程实施无关的人物摆拍",
        "海报式构图",
        "海报式大号文字",
        "大面积标题字",
        "图上醒目中文大字",
        "图上醒目英文大字",
        "封面式标题",
        "宣传标语",
        "整屏中文说明",
        "整屏英文说明",
        "宣传海报版式",
        "广告宣传图风格",
        "概念海报渲染",
        "夸张灯光秀效果",
        "水印、logo、页眉页脚式装饰",
        "卡通插画风格",
    ]
    _STYLE_PRESETS: tuple[dict[str, Any], ...] = (
        {
            "key": "engineering_simulation_detail",
            "label": "工程模拟细节动画图",
            "aspect_ratio": "2:1",
            "preferred_types": {"topology", "layout", "process"},
            "keywords": (
                "制冷站",
                "空压站",
                "真空站",
                "泵",
                "阀门",
                "机组",
                "换热器",
                "储罐",
                "管线",
                "联动",
                "组态",
                "SCADA",
                "控制柜",
                "传感器",
                "仪表",
                "回路",
                "监控平台",
                "流向",
            ),
            "style_identity": "数字三维工程模拟图、工业组态示意图或设备联动动画帧",
            "must_not_be": "真实摄影照片、平面 PPT 流程图、艺术概念海报",
            "composition": (
                "必须表现为工业系统的三维模拟总览或局部联动细节，"
                "设备、管线、阀门、测点、控制单元之间要有明确连接关系。"
            ),
            "visual_language": (
                "背景浅灰，主体设备为工业蓝灰金属质感，局部允许蓝色和绿色管线区分支路，"
                "整体应接近严肃的 HMI/SCADA 监控动画帧。"
            ),
            "details": (
                "必须准确体现设备本体、法兰、管口、流向箭头、测点框、传感器位置、"
                "回路连接和局部控制关系。"
            ),
            "text_rules": (
                "允许极少量小型状态框、小型设备编号和参数标签，"
                "但不能出现页面级大标题和整屏说明文字。"
            ),
            "variants": (
                {
                    "key": "system_overview",
                    "label": "整站总览",
                    "preferred_types": {"topology", "process"},
                    "keywords": ("系统", "站", "总览", "联动", "流程", "回路"),
                    "difference_goal": (
                        "本图必须是完整系统总览，重点做广角横向展开，显示多台设备和整条主管支路，"
                        "不要只聚焦单个设备。"
                    ),
                    "composition": "采用横向轴测总览构图，画面左右展开，前景和后景都有设备，整体偏全景。",
                    "camera": "使用稳定浅俯视或等轴视角，无真实摄影镜头感。",
                    "people": "画面中不出现施工人员。",
                    "lighting": "冷中性色工业照明，整体偏冷。",
                    "palette": "以蓝灰设备和蓝绿管线为主色，避免暖色占主导。",
                },
                {
                    "key": "equipment_cluster_focus",
                    "label": "设备群组局部细节",
                    "preferred_types": {"layout", "process"},
                    "keywords": ("机组", "泵", "阀门", "控制柜", "设备安装", "设备布置"),
                    "difference_goal": (
                        "本图必须聚焦一个关键设备群组，强调局部设备集群和相邻控制关系，"
                        "不要做整站大全景。"
                    ),
                    "composition": "采用中景偏近的局部设备群组构图，突出 2 到 4 台关键设备的组合关系。",
                    "camera": "使用略带斜向的工程演示视角，但仍然是三维模拟而非摄影镜头。",
                    "people": "画面中不出现施工人员。",
                    "lighting": "中性工业照明，局部可以稍暖，突出设备立体感。",
                    "palette": "设备灰蓝、控制柜灰白，局部以绿色或橙色小信号点缀。",
                },
                {
                    "key": "control_loop_detail",
                    "label": "控制联动局部图",
                    "preferred_types": {"topology", "layout"},
                    "keywords": ("PLC", "控制", "仪表", "传感器", "监控", "联锁", "测点"),
                    "difference_goal": (
                        "本图必须突出控制柜、传感器、测点和局部回路联动，"
                        "重点展示控制关系和信息流，而不是大面积展示所有设备。"
                    ),
                    "composition": "采用局部回路细节构图，控制柜或监控节点占据一侧，传感器和被控设备分布在另一侧。",
                    "camera": "使用工程软件截图式斜角视图，禁止真实摄影透视。",
                    "people": "画面中不出现施工人员。",
                    "lighting": "偏冷中性，强调仪表框和控制回路。",
                    "palette": "灰白控制柜配蓝绿信号线，局部允许黄色报警标签。",
                },
            ),
        },
        {
            "key": "engineering_flow_diagram",
            "label": "工程流程图",
            "aspect_ratio": "2:1",
            "preferred_types": {"topology", "process", "acceptance"},
            "keywords": (
                "流程",
                "步骤",
                "逻辑",
                "节点",
                "网络",
                "通信",
                "总线",
                "交换机",
                "诊断",
                "故障",
                "报警",
                "监测",
                "巡检",
                "整改",
                "闭环",
                "恢复",
                "处置",
                "应急",
            ),
            "style_identity": "平面工程流程图、节点诊断图或信息架构图",
            "must_not_be": "真实现场照片、机房实拍、三维设备渲染总览图",
            "composition": (
                "必须表现为结构化平面信息图，节点、箭头、模块层级和关系线是主体，"
                "不能出现写实机柜摄影画面。"
            ),
            "visual_language": (
                "浅灰或白底，深灰主节点，蓝绿黄紫等有限功能色块，"
                "整体像正式技术汇报图，不像宣传海报。"
            ),
            "details": (
                "必须准确体现监测对象、判断逻辑、故障类型、处理动作、恢复路径、"
                "节点关系或闭环关系。"
            ),
            "text_rules": (
                "允许模块内短句和简短中文标签，但不能堆成长段文字，"
                "更不能写营销文案。"
            ),
            "variants": (
                {
                    "key": "hub_diagnosis_map",
                    "label": "中心节点诊断图",
                    "preferred_types": {"topology"},
                    "keywords": ("网络", "通信", "节点", "交换机", "诊断", "总线", "故障"),
                    "difference_goal": (
                        "本图必须是中心节点加四周分支模块的诊断图，核心节点居中，四周模块分布均衡，"
                        "不要改成线性步骤图。"
                    ),
                    "composition": "采用中心核心卡片加四周四个功能模块的构图，模块之间用虚线或折线连接。",
                    "camera": "完全平面正视图，无任何透视。",
                    "people": "不出现人物。",
                    "lighting": "不是摄影画面，无光影要求，仅做干净平面视觉。",
                    "palette": "深灰中心卡片配四个功能色块，白灰背景。",
                },
                {
                    "key": "linear_operation_chain",
                    "label": "线性操作链路图",
                    "preferred_types": {"process"},
                    "keywords": ("启动", "停机", "步骤", "流程", "维护", "巡检", "顺序"),
                    "difference_goal": (
                        "本图必须是从左到右的线性步骤链路图，强调先后顺序，"
                        "不要做中心辐射结构。"
                    ),
                    "composition": "采用左到右 4 到 6 步顺序流程图，箭头单向明确，模块横向排开。",
                    "camera": "完全平面正视图，无任何透视。",
                    "people": "不出现人物。",
                    "lighting": "不是摄影画面，无光影要求，仅做技术信息图。",
                    "palette": "蓝绿为主，局部用橙红强调异常或关键动作。",
                },
                {
                    "key": "closed_loop_response",
                    "label": "闭环响应图",
                    "preferred_types": {"acceptance", "process"},
                    "keywords": ("报警", "整改", "闭环", "恢复", "验证", "报告", "应急"),
                    "difference_goal": (
                        "本图必须采用闭环或环状响应结构，强调异常发现到整改关闭的循环关系，"
                        "不要做水平链路图。"
                    ),
                    "composition": "采用环形、双环或近闭环的流程图，箭头形成明显循环。",
                    "camera": "完全平面正视图，无任何透视。",
                    "people": "不出现人物。",
                    "lighting": "不是摄影画面，无光影要求，仅做流程图视觉。",
                    "palette": "蓝绿橙红四色闭环分区，整体节奏清晰。",
                },
            ),
        },
        {
            "key": "engineering_site_photo",
            "label": "工程现场实景实拍图",
            "aspect_ratio": "3:2",
            "preferred_types": {"layout", "acceptance", "process"},
            "keywords": (
                "现场",
                "安装",
                "施工",
                "机房",
                "站房",
                "配电室",
                "控制室",
                "柜体",
                "控制柜",
                "配电柜",
                "调试",
                "验收",
                "投运",
                "设备就位",
                "实景",
                "落地柜",
                "通道",
                "巡检",
            ),
            "style_identity": "真实工业现场纪实摄影图",
            "must_not_be": "三维渲染模拟图、流程图、PPT 卡片图、概念效果图",
            "composition": (
                "必须是机房、站房、控制室或配电室中的真实工程安装场景，"
                "柜体、通道、桥架、墙面、地面和照明环境都应真实存在。"
            ),
            "visual_language": (
                "中性白光或现场自然光，真实摄影质感，保留工业空间环境信息，"
                "不要做宣传片级别的戏剧化打光。"
            ),
            "details": (
                "必须体现设备安装完成态、柜门、基础、通道距离、桥架或管线、"
                "设备与建筑环境之间的真实关系。"
            ),
            "text_rules": "原则上不叠加文字，只允许极少量小型设备标牌或角标。",
            "variants": (
                {
                    "key": "wide_corridor_no_people",
                    "label": "空旷通道广角",
                    "preferred_types": {"layout"},
                    "keywords": ("机房", "站房", "布置", "安装", "通道", "落地柜"),
                    "difference_goal": (
                        "本图必须是空旷通道的广角全景，强调整齐成排设备和空间尺度，"
                        "不要出现明显施工人员。"
                    ),
                    "composition": "采用正向或近正向通道广角构图，通道纵深明显，成排柜体对称或近对称展开。",
                    "camera": "使用人眼高度的广角纪实机位，稳定水平线。",
                    "people": "不出现施工人员或只允许极远处模糊小人影。",
                    "lighting": "偏冷中性色工业照明，整体清爽、秩序化。",
                    "palette": "灰白柜体、灰色地面、偏冷环境光。",
                },
                {
                    "key": "oblique_inspection_personnel",
                    "label": "单人巡检斜角",
                    "preferred_types": {"acceptance", "process"},
                    "keywords": ("验收", "调试", "巡检", "检查", "确认", "试运行"),
                    "difference_goal": (
                        "本图必须采用斜向机位，并包含 1 名巡检或调试人员，"
                        "强调现场操作动作，不要做空旷通道对称大远景。"
                    ),
                    "composition": "采用三分之二侧向或斜向通道视角，人物位于中景，设备形成斜向透视。",
                    "camera": "使用纪实中广角机位，略靠近人物和设备操作点。",
                    "people": "允许 1 名工作人员进行巡检、读表、操作或确认动作，但人物不是主角。",
                    "lighting": "中性偏暖现场照明，允许局部亮区和阴影变化。",
                    "palette": "灰白柜体配中性暖光，局部可见黄色或橙色安全帽/工装点缀。",
                },
                {
                    "key": "close_mid_cabinet_detail",
                    "label": "开柜近中景细节",
                    "preferred_types": {"layout", "acceptance"},
                    "keywords": ("控制柜", "柜门", "接线", "端子", "铭牌", "设备细节", "检修"),
                    "difference_goal": (
                        "本图必须做近中景设备细节，突出单侧柜体、开柜或面板细节，"
                        "不要再做整条通道的大景别。"
                    ),
                    "composition": "采用近中景局部构图，一到两面柜体占据主要画面，背景保留少量通道环境。",
                    "camera": "使用贴近设备的人眼高度机位，聚焦面板、柜门、局部接线或铭牌区域。",
                    "people": "不出现完整人物，最多允许一只戴手套的手或局部操作动作进入画面边缘。",
                    "lighting": "中性光，允许更明显的设备表面反光和细节阴影。",
                    "palette": "柜体灰白为主，背景和地面更克制，突出设备细节。",
                },
            ),
        },
    )

    def build(self, *, entities: EntityExtraction, node_text: NodeText) -> ImagePrompts:
        targets = self._collect_targets(node_text)
        prompt_types = self._select_prompt_types(entities, node_text)
        prompts: list[ImagePromptItem] = []
        used_preset_counts: dict[str, int] = {}
        used_variant_keys: set[str] = set()

        for index, image_type in enumerate(prompt_types, start=1):
            bind_anchor, bind_section = targets[min(index - 1, len(targets) - 1)]
            must_have = self._select_elements(
                image_type=image_type,
                entities=entities,
                node_text=node_text,
                bind_section=bind_section,
            )
            context = self._context_text(
                entities=entities,
                node_text=node_text,
                bind_section=bind_section,
            )
            style_preset = self._select_style_preset(
                image_type=image_type,
                context=context,
                used_preset_counts=used_preset_counts,
            )
            style_variant = self._select_style_variant(
                style_preset=style_preset,
                image_type=image_type,
                context=context,
                used_variant_keys=used_variant_keys,
            )
            preset_key = str(style_preset["key"])
            used_preset_counts[preset_key] = used_preset_counts.get(preset_key, 0) + 1
            used_variant_keys.add(f"{preset_key}:{style_variant['key']}")
            prompts.append(
                ImagePromptItem(
                    prompt_id=f"prompt_{index:03d}",
                    image_type=image_type,
                    style_preset=preset_key,
                    style_variant=str(style_variant["key"]),
                    aspect_ratio=str(style_preset["aspect_ratio"]),
                    prompt=self._render_prompt(
                        image_type=image_type,
                        node_title=node_text.title,
                        bind_section=bind_section,
                        must_have=must_have,
                        style_preset=style_preset,
                        style_variant=style_variant,
                    ),
                    must_have_elements=must_have,
                    forbidden_elements=list(self._FORBIDDEN_ELEMENTS),
                    bind_anchor=bind_anchor,
                    bind_section=bind_section,
                )
            )

        return ImagePrompts(node_uid=node_text.node_uid, prompts=prompts[:3])

    def strengthen_prompt(
        self,
        prompt_item: ImagePromptItem,
        *,
        missing_elements: list[str],
        retry_no: int,
    ) -> ImagePromptItem:
        if not missing_elements:
            return prompt_item
        must_have = list(prompt_item.must_have_elements)
        for item in missing_elements:
            if item not in must_have:
                must_have.append(item)
        updated_prompt = (
            f"{prompt_item.prompt.rstrip('。')}。"
            f"第{retry_no}次重试必须补足：{'、'.join(missing_elements)}。"
            "本次重试必须继续保持当前选定的风格类别和镜头变体，不要退化成通用海报图。"
        )
        return prompt_item.model_copy(
            update={
                "prompt": updated_prompt,
                "must_have_elements": must_have,
            }
        )

    def _collect_targets(self, node_text: NodeText) -> list[tuple[str, str]]:
        targets: list[tuple[str, str]] = []
        for section in node_text.sections:
            anchor = None
            for paragraph in section.paragraphs:
                if paragraph.anchors:
                    anchor = paragraph.anchors[0]
                    break
            targets.append((anchor or "anchor_default", section.title))
        if not targets:
            targets.append(("anchor_default", node_text.title))
        return targets

    @staticmethod
    def _select_prompt_types(entities: EntityExtraction, node_text: NodeText) -> list[str]:
        categories = {item.category for item in entities.entities}
        context = " ".join(
            [
                node_text.title,
                node_text.summary,
                *[section.title for section in node_text.sections],
                *[entity.name for entity in entities.entities],
            ]
        )
        types: list[str] = []
        if "topology" in categories or any(
            token in context for token in ("网络", "通信", "总线", "拓扑", "联动", "架构", "节点")
        ):
            types.append("topology")
        if "process" in categories or any(
            token in context for token in ("流程", "步骤", "巡检", "监测", "报警", "整改", "运行", "维护", "PLC")
        ):
            types.append("process")
        has_acceptance = "acceptance" in categories or any(
            token in context for token in ("验收", "测试", "检查", "确认", "试运行", "调试")
        )
        if has_acceptance:
            types.append("acceptance")
        if "device" in categories or any(
            token in context for token in ("安装", "机柜", "柜体", "配电柜", "桥架", "布置", "机房", "现场", "控制柜")
        ):
            types.append("layout")

        unique: list[str] = []
        for item in types:
            if item not in unique:
                unique.append(item)
        if len(unique) < 2 and "process" not in unique:
            unique.append("process")
        if len(unique) < 2 and "layout" not in unique:
            unique.append("layout")
        return unique[:3]

    @staticmethod
    def _select_elements(
        *,
        image_type: str,
        entities: EntityExtraction,
        node_text: NodeText,
        bind_section: str,
    ) -> list[str]:
        priority = {
            "topology": {"topology", "device", "scene"},
            "process": {"process", "scene", "device"},
            "layout": {"device", "scene", "process"},
            "acceptance": {"acceptance", "process", "scene"},
        }.get(image_type, {"process", "scene"})

        chosen: list[str] = []
        for entity in entities.entities:
            if entity.category in priority and entity.name not in chosen:
                chosen.append(entity.name)
        if bind_section not in chosen:
            chosen.append(bind_section)
        if node_text.title not in chosen:
            chosen.append(node_text.title)
        if len(chosen) < 2:
            chosen.extend(["工程对象", "关键标注"])
        return chosen[:4]

    def _select_style_preset(
        self,
        *,
        image_type: str,
        context: str,
        used_preset_counts: dict[str, int],
    ) -> dict[str, Any]:
        ranked = sorted(
            self._STYLE_PRESETS,
            key=lambda preset: self._score_style_preset(
                preset=preset,
                image_type=image_type,
                context=context,
                used_count=used_preset_counts.get(str(preset["key"]), 0),
            ),
            reverse=True,
        )
        return ranked[0]

    def _select_style_variant(
        self,
        *,
        style_preset: dict[str, Any],
        image_type: str,
        context: str,
        used_variant_keys: set[str],
    ) -> dict[str, Any]:
        ranked = sorted(
            style_preset["variants"],
            key=lambda variant: self._score_style_variant(
                style_preset=style_preset,
                variant=variant,
                image_type=image_type,
                context=context,
                used_variant_keys=used_variant_keys,
            ),
            reverse=True,
        )
        for variant in ranked:
            if f"{style_preset['key']}:{variant['key']}" not in used_variant_keys:
                return variant
        return ranked[0]

    @staticmethod
    def _context_text(
        *,
        entities: EntityExtraction,
        node_text: NodeText,
        bind_section: str,
    ) -> str:
        return " ".join(
            [
                node_text.title,
                node_text.summary,
                bind_section,
                *[section.title for section in node_text.sections],
                *[entity.name for entity in entities.entities],
            ]
        )

    @staticmethod
    def _score_style_preset(
        *,
        preset: dict[str, Any],
        image_type: str,
        context: str,
        used_count: int,
    ) -> int:
        score = 0
        if image_type in preset["preferred_types"]:
            score += 6
        for keyword in preset["keywords"]:
            if keyword in context:
                score += 3
        score -= used_count * 2
        return score

    @staticmethod
    def _score_style_variant(
        *,
        style_preset: dict[str, Any],
        variant: dict[str, Any],
        image_type: str,
        context: str,
        used_variant_keys: set[str],
    ) -> int:
        score = 0
        if image_type in variant["preferred_types"]:
            score += 4
        for keyword in variant["keywords"]:
            if keyword in context:
                score += 3
        if f"{style_preset['key']}:{variant['key']}" in used_variant_keys:
            score -= 8
        return score

    @staticmethod
    def _render_prompt(
        *,
        image_type: str,
        node_title: str,
        bind_section: str,
        must_have: list[str],
        style_preset: dict[str, Any],
        style_variant: dict[str, Any],
    ) -> str:
        type_name = {
            "topology": "系统拓扑图",
            "process": "工艺流程图",
            "layout": "设备布置图",
            "acceptance": "验收检查图",
        }.get(image_type, "工程技术图")
        aspect_ratio = str(style_preset["aspect_ratio"] or ImagePromptAgent.DEFAULT_ASPECT_RATIO)
        return (
            f"请为工程技术方案文档生成一张专业{type_name}，主题是“{node_title}”，绑定小节是“{bind_section}”。"
            f"这张图必须采用“{style_preset['label']}”风格，具体镜头变体必须采用“{style_variant['label']}”。"
            f"最终画幅必须是{aspect_ratio}横向长图，并适合技术文件整页通栏插图。"
            f"风格铁律：这张图必须被看成{style_preset['style_identity']}，绝对不要变成{style_preset['must_not_be']}。"
            f"同组图片去相似化要求：这张图必须与同节点其他图片在构图、机位、景别、地点感、色温、人员出镜状态上明显不同。"
            f"本图专属差异目标：{style_variant['difference_goal']}"
            f"一、总体画面结构：{style_preset['composition']}"
            f"二、本图构图方案：{style_variant['composition']}"
            f"三、视角与机位：{style_variant['camera']}"
            f"四、人员出镜规则：{style_variant['people']}"
            f"五、光线要求：{style_variant['lighting']}"
            f"六、颜色与材质：{style_preset['visual_language']} 本图配色重点：{style_variant['palette']}"
            f"七、工程细节：{style_preset['details']}"
            f"八、必须出现的工程对象：{'、'.join(must_have)}。这些对象必须真实可辨认，不能只做抽象象征。"
            f"九、文字和标注规则：{style_preset['text_rules']}"
            "十、结构约束：对象之间的连接、层级、流程顺序、空间位置、安装关系、控制关系必须正确，"
            "不能变成装饰性摆拍，也不能变成抽象概念海报。"
            "十一、总体气质：严肃、专业、克制、工程化，服务于投标技术文件，不追求艺术化炫技。"
            "十二、严格禁止：禁止任何大号标题字、宣传语、封面字、横幅字、整屏说明文字、海报式排版。"
            "No poster layout. No big title text. No large Chinese or English words overlaid on the image."
            f"十三、额外禁止项：{', '.join(ImagePromptAgent._FORBIDDEN_ELEMENTS)}。"
        )
