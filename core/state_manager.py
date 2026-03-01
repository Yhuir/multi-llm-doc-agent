from sqlalchemy import create_engine, Column, String, Integer, Text, DateTime, JSON
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import os
import json

Base = declarative_base()

class Task(Base):
    __tablename__ = 'tasks'
    id = Column(String, primary_key=True)
    status = Column(String, default="NEW") # NEW, PARSED, TOC_REVIEW, GENERATING, LAYOUTING, EXPORTING, DONE, PAUSED, FAILED
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    file_path = Column(String)

class TOCVersion(Base):
    __tablename__ = 'toc_versions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String)
    version = Column(Integer)
    toc_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

class NodeState(Base):
    __tablename__ = 'node_states'
    id = Column(String, primary_key=True) # Usually task_id + "_" + node_id
    task_id = Column(String)
    node_id = Column(String)
    status = Column(String, default="NODE_PENDING") # NODE_PENDING, TEXT_GENERATED, IMAGES_GENERATED, etc.
    metrics = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class StateManager:
    def __init__(self, db_path="sqlite:///db/app.db"):
        os.makedirs(os.path.dirname(db_path.replace("sqlite:///", "")), exist_ok=True) if "sqlite:///" in db_path and not db_path == "sqlite:///:memory:" else None
        if db_path.startswith("sqlite:///") and db_path != "sqlite:///:memory:":
            dir_path = os.path.dirname(db_path.replace("sqlite:///", ""))
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path, exist_ok=True)
                
        self.engine = create_engine(db_path)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def create_task(self, task_id: str, file_path: str):
        with self.Session() as session:
            task = Task(id=task_id, file_path=file_path)
            session.add(task)
            session.commit()
            return task_id

    def update_task_status(self, task_id: str, status: str):
        with self.Session() as session:
            task = session.query(Task).filter_by(id=task_id).first()
            if task:
                task.status = status
                session.commit()

    def get_task(self, task_id: str):
        with self.Session() as session:
            return session.query(Task).filter_by(id=task_id).first()

    def save_toc(self, task_id: str, version: int, toc_data: dict):
        with self.Session() as session:
            toc = TOCVersion(task_id=task_id, version=version, toc_data=toc_data)
            session.add(toc)
            session.commit()

    def get_latest_toc(self, task_id: str):
        with self.Session() as session:
            return session.query(TOCVersion).filter_by(task_id=task_id).order_by(TOCVersion.version.desc()).first()

    def update_node_state(self, task_id: str, node_id: str, status: str, metrics: dict = None):
        with self.Session() as session:
            node_state_id = f"{task_id}_{node_id}"
            node = session.query(NodeState).filter_by(id=node_state_id).first()
            if not node:
                node = NodeState(id=node_state_id, task_id=task_id, node_id=node_id, status=status, metrics=metrics or {})
                session.add(node)
            else:
                node.status = status
                if metrics:
                    node.metrics.update(metrics)
            session.commit()

    def get_node_states(self, task_id: str):
        with self.Session() as session:
            return session.query(NodeState).filter_by(task_id=task_id).all()
