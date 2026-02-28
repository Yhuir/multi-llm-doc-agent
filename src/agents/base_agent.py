from src.utils.llm_client import LLMClient

class BaseAgent:
    def __init__(self, name: str, model: str = "gpt-4o"):
        self.name = name
        self.llm = LLMClient(model=model)
        
    def run(self, *args, **kwargs):
        raise NotImplementedError("Subclasses must implement the run method")
