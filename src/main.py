import os
import json
from dotenv import load_dotenv

# Import all agents
from src.agents.requirement_parser import RequirementParserAgent
from src.agents.master_gantt import MasterGanttAgent
from src.agents.subsystem_gantt import SubsystemGanttAgent
from src.agents.plan_generator import PlanGeneratorAgent
# from src.agents.content_generator import ContentGeneratorAgent # Deprecated
from src.agents.integrated_content import IntegratedContentAgent
from src.agents.diagram_image import DiagramImageAgent
from src.agents.consistency_check import ConsistencyCheckAgent
from src.agents.word_exporter import WordExporterAgent

# Load environment variables
load_dotenv()

class DocumentGenerationOrchestrator:
    def __init__(self):
        # Initialize necessary agents
        self.requirement_parser = RequirementParserAgent()
        self.master_gantt_agent = MasterGanttAgent()
        self.subsystem_gantt_agent = SubsystemGanttAgent()
        self.plan_generator_agent = PlanGeneratorAgent()
        self.integrated_content_agent = IntegratedContentAgent() # Batch Agent
        self.diagram_generator_agent = DiagramImageAgent()
        self.consistency_checker_agent = ConsistencyCheckAgent()
        self.word_exporter_agent = WordExporterAgent()

    def run_pipeline(self, input_docx_path: str):
        print("=== 开始执行智能工程实施方案生成系统 (RPD 优化版) ===")

        # 1. 需求解析
        print("\n>>> 阶段 1: 需求解析")
        project_reqs = self.requirement_parser.run(input_docx_path)

        # 2. 总体甘特图
        print("\n>>> 阶段 2: 生成总体甘特图")
        master_gantt = self.master_gantt_agent.run(project_reqs)

        # 3-5. 子系统分解与计划规划
        print("\n>>> 阶段 3-5: 子系统分解与计划规划")
        subsystems = project_reqs.get("subsystems", [])
        
        final_document_data = {
            "project_info": project_reqs,
            "master_gantt": master_gantt,
            "subsystem_details": []
        }

        for sub_name in subsystems:
            print(f"\n--- 处理子系统: {sub_name} ---")
            sub_gantt = self.subsystem_gantt_agent.run(master_gantt, sub_name)
            sub_plans_json = self.plan_generator_agent.run(sub_gantt)
            plans_list = sub_plans_json.get("plans", []) if isinstance(sub_plans_json, dict) else sub_plans_json

            sub_data = {
                "name": sub_name,
                "plans": []
            }

            for plan in plans_list:
                plan_title = plan.get("title")
                # 关键改进：批量处理所有动作，而不是循环 Content
                print(f"\n>>> 阶段 6-9: 批量处理计划章节 [{plan_title}]")
                # 这里我们直接让模型基于 plan 内部信息生成整章内容
                # 假设 Plan 内部已经包含了动作简述，如果没有，我们可以先通过 PlanGenerator 获取
                # 这里为了极致省 RPD，我们让模型自己从 plan_title 联想施工动作
                integrated_text = self.integrated_content_agent.run(plan_title, plan.get("contents", []))
                
                # 阶段 7: 生图 (解析文本中已有的 JSON，不消耗额外 RPD)
                image_configs = self.integrated_content_agent.parse_images(integrated_text)
                final_images = []
                for img_config in image_configs:
                    print(f"[{self.diagram_generator_agent.name}] 正在生图: {img_config.get('caption')}")
                    # 注意：generate_image 调用的是生图接口，不计入 Gemini RPD
                    img_path = self.diagram_generator_agent.llm.generate_image(
                        img_config.get("prompt"), 
                        f"data/images/img_{os.urandom(4).hex()}.png"
                    )
                    img_config["source"] = img_path
                    final_images.append(img_config)

                sub_data["plans"].append({
                    "plan_title": plan_title,
                    "full_text": integrated_text,
                    "images": final_images
                })
            
            final_document_data["subsystem_details"].append(sub_data)

        # 10. 全局一致性检查
        print("\n>>> 阶段 10: 全局逻辑检查")
        self.consistency_checker_agent.run(final_document_data)
        
        # 保存中间结果
        os.makedirs("outputs", exist_ok=True)
        with open("outputs/final_data.json", "w", encoding="utf-8") as f:
            json.dump(final_document_data, f, ensure_ascii=False, indent=2)
            
        # 11. Word 文档排版导出
        print("\n>>> 阶段 11: 导出 Word 文档")
        output_file = self.word_exporter_agent.run(final_document_data)
        
        print("\n=== 系统执行完毕！文件已生成至 outputs/ 目录 ===")
        return output_file

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python src/main.py <path_to_word_doc>")
        sys.exit(1)
        
    input_doc = sys.argv[1]
    if not os.path.exists(input_doc):
        print(f"Error: File '{input_doc}' not found.")
        sys.exit(1)
        
    orchestrator = DocumentGenerationOrchestrator()
    orchestrator.run_pipeline(input_doc)
