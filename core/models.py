from pydantic import BaseModel, Field
from typing import List, Optional

class Milestone(BaseModel):
    name: str
    date: str

class RequirementProject(BaseModel):
    name: str
    customer: Optional[str] = None
    location: Optional[str] = None
    duration_days: Optional[int] = None
    milestones: List[Milestone] = []

class RequirementItem(BaseModel):
    type: str
    key: Optional[str] = None
    value: Optional[str] = None
    text: Optional[str] = None
    source_ref: Optional[str] = None

class Subsystem(BaseModel):
    name: str
    description: Optional[str] = None
    requirements: List[RequirementItem] = []
    interfaces: List[str] = []

class RequirementScope(BaseModel):
    overview: str
    subsystems: List[Subsystem] = []

class RequirementConstraints(BaseModel):
    standards: List[str] = []
    acceptance: List[str] = []

class SourceIndexItem(BaseModel):
    ref_id: str
    page: Optional[int] = None
    paragraph_id: Optional[str] = None
    text: Optional[str] = None

class ParsedRequirement(BaseModel):
    project: RequirementProject
    scope: RequirementScope
    constraints: RequirementConstraints
    source_index: List[SourceIndexItem] = []

class TOCConstraints(BaseModel):
    min_words: int = 1800
    images: List[int] = [2, 3]

class TOCLevel3Node(BaseModel):
    node_id: str
    level: int = 4
    title: str
    constraints: Optional[TOCConstraints] = None
    source_refs: List[str] = []

class TOCLevel2Node(BaseModel):
    node_id: str
    level: int = 3
    title: str
    children: List[TOCLevel3Node] = []

class TOCSubsystemNode(BaseModel):
    node_id: str
    level: int = 2
    subsystem: bool = True
    title: str
    children: List[TOCLevel2Node] = []

class TOCLevel1Node(BaseModel):
    node_id: str
    level: int = 1
    title: str
    children: List[TOCSubsystemNode] = []

class TOC(BaseModel):
    version: int
    generated_at: str
    tree: List[TOCLevel1Node]

class SectionStyle(BaseModel):
    bold: Optional[bool] = None
    color: Optional[str] = None

class SectionText(BaseModel):
    h: str
    text: Optional[str] = None
    min_words: Optional[int] = None
    table_ref: Optional[str] = None
    style: Optional[SectionStyle] = None

class NodeText(BaseModel):
    node_id: str
    title: str
    sections: List[SectionText]
    references: Optional[List[str]] = []

class TableData(BaseModel):
    table_id: str
    title: str
    columns: List[str]
    rows: List[List[str]]

class NodeTables(BaseModel):
    tables: List[TableData]
