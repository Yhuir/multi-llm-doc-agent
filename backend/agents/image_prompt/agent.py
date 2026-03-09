"""Prompt construction for the minimal image pipeline."""

from __future__ import annotations

from backend.models.schemas import EntityExtraction, ImagePromptItem, ImagePrompts, NodeText


class ImagePromptAgent:
    """Build constrained prompts with must-have and forbidden elements."""

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

    def build(self, *, entities: EntityExtraction, node_text: NodeText) -> ImagePrompts:
        targets = self._collect_targets(node_text)
        prompt_types = self._select_prompt_types(entities, node_text)
        prompts: list[ImagePromptItem] = []

        for index, image_type in enumerate(prompt_types, start=1):
            bind_anchor, bind_section = targets[min(index - 1, len(targets) - 1)]
            must_have = self._select_elements(
                image_type=image_type,
                entities=entities,
                node_text=node_text,
                bind_section=bind_section,
            )
            prompts.append(
                ImagePromptItem(
                    prompt_id=f"prompt_{index:03d}",
                    image_type=image_type,
                    prompt=self._render_prompt(
                        image_type=image_type,
                        node_title=node_text.title,
                        bind_section=bind_section,
                        must_have=must_have,
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
        types: list[str] = []
        if "topology" in categories:
            types.append("topology")
        types.append("process")
        has_acceptance = "acceptance" in categories or any(
            token in section.title for section in node_text.sections for token in ("验收", "测试")
        )
        if has_acceptance:
            types.append("acceptance")
        if "device" in categories:
            types.append("layout")

        unique: list[str] = []
        for item in types:
            if item not in unique:
                unique.append(item)
        if len(unique) < 2:
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

    @staticmethod
    def _render_prompt(
        *,
        image_type: str,
        node_title: str,
        bind_section: str,
        must_have: list[str],
    ) -> str:
        type_name = {
            "topology": "系统拓扑图",
            "process": "工艺流程图",
            "layout": "设备布置图",
            "acceptance": "验收检查图",
        }.get(image_type, "工程技术图")
        visual_style = {
            "topology": "优先生成严肃专业的工程结构图、CAD图、电气原理图或P&ID图，突出设备、管线、阀门、控制关系和连接方向，画面应像正式工程设计资料而不是海报。",
            "process": "优先生成严肃专业的工程流程结构图、P&ID图、CAD工艺图或工业工程结构图，突出流程路径、设备流向和控制节点，禁止海报式演绎画面。",
            "layout": "优先生成真实工程现场实景拍摄风格的设备安装图、机房/站房实景图；若不适合实拍，再生成CAD布置图、轴测图或严肃专业的工业设备安装结构图。",
            "acceptance": "优先生成真实现场验收拍摄风格的工程图片，体现设备状态、检测动作和验收点位；若不适合实拍，再生成严肃专业的验收结构示意图。",
        }.get(image_type, "优先生成严肃专业的工程结构图、真实工程现场拍摄图或CAD图；若不适合实拍，再生成P&ID图或工业设备结构图。")
        return (
            f"生成一张用于工程技术方案文档的专业{type_name}，主题为“{node_title}”，对应小节“{bind_section}”。"
            f"{visual_style}"
            f"画面中必须以工程对象形式体现：{'、'.join(must_have)}。"
            "要求主体完整、结构关系准确、材质和设备细节真实，画面气质严肃、专业、克制，适合投标技术文件插图。"
            "构图要求尽量采用1:1正方形，主体居中，宽幅排版友好。"
            "优先选择严肃的工程结构图、真实工程现场拍摄图或CAD图风格，不要做宣传海报、封面图、营销图或概念海报。"
            "如果生成结构图，应接近正式设计资料、施工图、布置图、P&ID图、电气原理图或CAD图；如果生成实景图，应接近真实工业现场拍摄，不要艺术海报风。"
            "除少量必要的设备编号、箭头或细小功能标识外，禁止任何大号文字、标题字、宣传语、封面字、横幅字、整屏说明文字、海报式标题。"
            "No poster layout. No big title text. No large Chinese or English words overlaid on the image."
            f"forbidden elements：{'、'.join(ImagePromptAgent._FORBIDDEN_ELEMENTS)}。"
        )
