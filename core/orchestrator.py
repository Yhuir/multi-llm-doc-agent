import uuid
import os
import json
from core.state_manager import StateManager
from utils.llm_client import LLMClient
from core.agents.parser_agent import RequirementParserAgent
from core.agents.toc_agent import TOCGeneratorAgent, TOCReviewAgent
from core.agents.writer_agent import SectionWriterAgent
from core.agents.layout_agent import LayoutAgent

class Orchestrator:
    def __init__(self, db_path="sqlite:///db/app.db", template_path="docx_text_extract.txt"):
        self.state_manager = StateManager(db_path)
        self.llm_client = LLMClient()
        self.parser_agent = RequirementParserAgent(self.llm_client)
        self.toc_generator = TOCGeneratorAgent(self.llm_client)
        self.toc_reviewer = TOCReviewAgent(self.llm_client)
        self.writer_agent = SectionWriterAgent(self.llm_client)
        self.layout_agent = LayoutAgent()
        
        self.template_text = ""
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                self.template_text = f.read()

    def start_new_task(self, file_path: str) -> str:
        task_id = str(uuid.uuid4())
        self.state_manager.create_task(task_id, file_path)
        return task_id

    def process_parsing(self, task_id: str):
        task = self.state_manager.get_task(task_id)
        if not task:
            raise ValueError("Task not found")
            
        parsed_req = self.parser_agent.parse(task.file_path)
        
        os.makedirs(f"artifacts/{task_id}", exist_ok=True)
        with open(f"artifacts/{task_id}/requirement.json", "w", encoding='utf-8') as f:
            json.dump(parsed_req, f, ensure_ascii=False, indent=2)
            
        self.state_manager.update_task_status(task_id, "PARSED")
        return parsed_req

    def generate_toc(self, task_id: str):
        with open(f"artifacts/{task_id}/requirement.json", "r", encoding='utf-8') as f:
            parsed_req = json.load(f)
            
        toc = self.toc_generator.generate(parsed_req)
        self.state_manager.save_toc(task_id, toc.get('version', 1), toc)
        self.state_manager.update_task_status(task_id, "TOC_REVIEW")
        return toc

    def revise_toc(self, task_id: str, user_feedback: str):
        latest_toc_record = self.state_manager.get_latest_toc(task_id)
        if not latest_toc_record:
            raise ValueError("No TOC found to revise")
            
        new_toc = self.toc_reviewer.revise(latest_toc_record.toc_data, user_feedback)
        self.state_manager.save_toc(task_id, new_toc.get('version', latest_toc_record.version + 1), new_toc)
        return new_toc

    def confirm_toc_and_start_generation(self, task_id: str):
        self.state_manager.update_task_status(task_id, "GENERATING")
        latest_toc_record = self.state_manager.get_latest_toc(task_id)
        
        # Extract all Level 4 (Execution) nodes
        l3_nodes = []
        def extract_execution_nodes(node, level=1):
            if level == 4:
                l3_nodes.append(node)
            for child in node.get('children', []):
                extract_execution_nodes(child, level + 1)
                
        for node in latest_toc_record.toc_data.get('tree', []):
            extract_execution_nodes(node)
            
        for node in l3_nodes:
            self.state_manager.update_node_state(task_id, node['node_id'], "NODE_PENDING")
            
        return len(l3_nodes)

    def generate_content_for_node(self, task_id: str, node_id: str):
        self.state_manager.update_node_state(task_id, node_id, "TEXT_GENERATING")
        
        # Load requirements
        with open(f"artifacts/{task_id}/requirement.json", "r", encoding='utf-8') as f:
            parsed_req = json.load(f)
            
        # Get node info from TOC
        latest_toc_record = self.state_manager.get_latest_toc(task_id)
        node_info = None
        def find_node(node):
            nonlocal node_info
            if node.get('node_id') == node_id:
                node_info = node
            for child in node.get('children', []):
                find_node(child)
        for node in latest_toc_record.toc_data.get('tree', []):
            find_node(node)
            
        if not node_info:
            self.state_manager.update_node_state(task_id, node_id, "NODE_FAILED", {"error": "Node not found in TOC"})
            return None
            
        node_text = self.writer_agent.write_node(node_info, parsed_req, self.template_text)
        
        os.makedirs(f"artifacts/{task_id}/nodes/{node_id}", exist_ok=True)
        with open(f"artifacts/{task_id}/nodes/{node_id}/text.json", "w", encoding='utf-8') as f:
            json.dump(node_text, f, ensure_ascii=False, indent=2)
            
        self.state_manager.update_node_state(task_id, node_id, "TEXT_GENERATED")
        return node_text

    def layout_document(self, task_id: str):
        self.state_manager.update_task_status(task_id, "LAYOUTING")
        latest_toc_record = self.state_manager.get_latest_toc(task_id)
        toc_data = latest_toc_record.toc_data
        
        nodes_text = {}
        nodes_dir = f"artifacts/{task_id}/nodes"
        if os.path.exists(nodes_dir):
            for node_id in os.listdir(nodes_dir):
                text_file = os.path.join(nodes_dir, node_id, "text.json")
                if os.path.exists(text_file):
                    with open(text_file, "r", encoding='utf-8') as f:
                        nodes_text[node_id] = json.load(f)
                        
        output_path = self.layout_agent.generate_word(task_id, toc_data, nodes_text)
        self.state_manager.update_task_status(task_id, "DONE")
        return output_path
