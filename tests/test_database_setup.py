"""Test database setup and model functionality."""

import pytest
import uuid
from datetime import datetime

from workflow_engine.persistence import (
    Workflow,
    WorkflowRun,
    NodeExecution,
    WorkflowEvent,
    SystemConfig,
)


def test_workflow_model():
    """Test workflow model creation."""
    workflow = Workflow(
        id="test-workflow-1",
        name="Test Workflow",
        description="A test workflow",
        definition={
            "nodes": [
                {"id": "start", "type": "agent", "config": {"prompt": "Hello"}}
            ]
        }
    )

    assert workflow.id == "test-workflow-1"
    assert workflow.name == "Test Workflow"
    assert workflow.definition["nodes"][0]["type"] == "agent"


def test_workflow_run_model():
    """Test workflow run model creation."""
    run = WorkflowRun(
        id="run-123",
        workflow_id="test-workflow-1",
        status="running",
        context={"step": 1, "data": "test"},
        input_data={"user_input": "Hello world"}
    )

    assert run.id == "run-123"
    assert run.status == "running"
    assert run.context["step"] == 1
    # Version defaults to 1 but may not be set until database insert


def test_node_execution_model():
    """Test node execution model creation."""
    execution = NodeExecution(
        id=str(uuid.uuid4()),
        run_id="run-123",
        node_id="start",
        node_type="agent",
        status="completed",
        input={"prompt": "Hello"},
        output={"response": "Hi there!"},
        duration_ms=150
    )

    assert execution.node_type == "agent"
    assert execution.status == "completed"
    assert execution.output["response"] == "Hi there!"


def test_workflow_event_model():
    """Test workflow event model creation."""
    event = WorkflowEvent(
        event_id=str(uuid.uuid4()),
        run_id="run-123",
        sequence_number=1,
        event_type="NODE_STARTED",
        node_id="start",
        payload={"node_type": "agent", "timestamp": datetime.now().isoformat()}
    )

    assert event.event_type == "NODE_STARTED"
    assert event.sequence_number == 1
    assert event.payload["node_type"] == "agent"


def test_system_config_model():
    """Test system config model creation."""
    config = SystemConfig(
        key="max_parallel_nodes",
        value={"count": 10, "enabled": True},
        description="Maximum number of parallel node executions"
    )

    assert config.key == "max_parallel_nodes"
    assert config.value["count"] == 10
    assert config.value["enabled"] is True


if __name__ == "__main__":
    """Run basic model tests without database connection."""
    print("🧪 Testing AI Workflow Engine models...")

    try:
        test_workflow_model()
        print("✅ Workflow model test passed")

        test_workflow_run_model()
        print("✅ WorkflowRun model test passed")

        test_node_execution_model()
        print("✅ NodeExecution model test passed")

        test_workflow_event_model()
        print("✅ WorkflowEvent model test passed")

        test_system_config_model()
        print("✅ SystemConfig model test passed")

        print("\n🎉 All model tests passed!")
        print("📋 Models are ready for database table creation")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        raise