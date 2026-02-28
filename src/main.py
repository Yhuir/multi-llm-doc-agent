import os
import json
import time
from dotenv import load_dotenv

# Import all agents
from src.agents.requirement_parser import RequirementParserAgent
from src.agents.master_gantt import MasterGanttAgent
from src.agents.subsystem_gantt import SubsystemGanttAgent
from src.agents.plan_generator import PlanGeneratorAgent
from src.agents.content_generator import ContentGeneratorAgent
from src.agents.technical_detail import TechnicalDetailAgent
from src.agents.length_control import LengthControlAgent
from src.agents.diagram_image import DiagramImageAgent
from src.agents.relevance_checker import RelevanceCheckerAgent
from src.agents.consistency_check import ConsistencyCheckAgent
from src.agents.word_exporter import WordExporterAgent

# Load environment variables
load_dotenv()

class DocumentGenerationOrchestrator:
    def __init__(self):
        # Initialize agents (Now utilizing specialized roles for high quality)
        self.requirement_parser = RequirementParserAgent()
        self.master_gantt_agent = MasterGanttAgent()
        self.subsystem_gantt_agent = SubsystemGanttAgent()
        self.plan_generator_agent = PlanGeneratorAgent()
        self.content_generator_agent = ContentGeneratorAgent()
        self.technical_detail_agent = TechnicalDetailAgent()
        self.length_controller_agent = LengthControlAgent() # Re-enabled for auditing
        self.diagram_generator_agent = DiagramImageAgent()
        self.relevance_checker_agent = RelevanceCheckerAgent()
        self.consistency_checker_agent = ConsistencyCheckAgent()
        self.word_exporter_agent = WordExporterAgent()

    def run_pipeline(self, input_docx_path: str):
        print("=== 开始执行智能工程实施方案生成系统 (v6.0 深度精修模式) ===")

        # 1. 需求解析
        print("\n>>> 阶段 1: 需求解析")
        project_reqs = self.requirement_parser.run(input_docx_path)

        # 2. 总体甘特图
        print("\n>>> 阶段 2: 生成总体甘特图")
        master_gantt = self.master_gantt_agent.run(project_reqs)

        # 3. 子系统分解
        subsystems = project_reqs.get("subsystems", [])
        
        final_document_data = {
            "project_info": project_reqs,
            "master_gantt": master_gantt,
            "subsystem_details": []
        }

        for sub_name in subsystems:
            print(f"\n--- 处理子系统: {sub_name} ---")
            # 3.1 生成子系统甘特图
            sub_gantt = self.subsystem_gantt_agent.run(master_gantt, sub_name)
            # 3.2 生成阶段计划 (Plans)
            sub_plans_json = self.plan_generator_agent.run(sub_gantt)
            plans_list = sub_plans_json.get("plans", [])

            sub_data = {
                "name": sub_name,
                "plans": []
            }

            for plan in plans_list:
                plan_title = plan.get("title")
                print(f"\n>>> 阶段 4: 处理计划 [{plan_title}]")
                
                # 3.3 生成该计划下的具体施工动作 (Contents)
                # 即使 PlanGenerator 有初步列表，我们也通过 ContentGenerator 进一步细化
                contents_json = self.content_generator_agent.run(plan)
                contents_list = contents_json.get("contents", [])

                plan_data = {
                    "plan_title": plan_title,
                    "contents": []
                }

                for content in contents_list:
                    content_title = content.get("title")
                    print(f"\n--- 动作: [{content_title}] ---")
                    
                    # 5. 生成技术方案 (Pro Model 驱动)
                    detail_text = self.technical_detail_agent.run(content)

                    # 6. 字数审计与质量补齐
                    print(f"\n>>> 阶段 6: 执行字数审计与补齐")
                    refined_text = self.length_controller_agent.run(detail_text)

                    # 7. 生图方案与生图
                    print(f"\n>>> 阶段 7: 生成强关联配图")
                    diagrams_json = self.diagram_generator_agent.run(refined_text)
                    images_list = diagrams_json.get("images", [])

                    # 8. 图文一致性校验
                    print(f"\n>>> 阶段 8: 图文相关性审计")
                    self.relevance_checker_agent.run(refined_text, images_list)

                    plan_data["contents"].append({
                        "title": content_title,
                        "text": refined_text,
                        "images": images_list
                    })
                
                sub_data["plans"].append(plan_data)
            
            final_document_data["subsystem_details"].append(sub_data)

        # 9. 全局一致性检查
        print("\n>>> 阶段 9: 全局逻辑检查")
        self.consistency_checker_agent.run(final_document_data)
        
        # 10. 保存中间结果
        os.makedirs("outputs", exist_ok=True)
        with open("outputs/final_data.json", "w", encoding="utf-8") as f:
            json.dump(final_document_data, f, ensure_ascii=False, indent=2)
            
        # 11. Word 文档导出 (原生排版)
        print("\n>>> 阶段 11: 导出正式 Word 文档")
        output_file = self.word_exporter_agent.run(final_document_data)
        
        print("\n=== 系统执行完毕！文件已生成至 outputs/ 目录 ===")
        return output_file
