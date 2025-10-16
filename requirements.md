# AI Workflow Engine - Requirements

## Goal:
Build a next-generation AI-native Workflow Engine (POC) — capable of orchestrating Agents, Tools, and MCP Servers with branching, sequential, and parallel logic.
The system must implement durable state persistence, AI orchestration capabilities, and support the Model Context Protocol (MCP) integration model.
Focus on clean architecture, modularity, extensibility, and correctness (not auth, observability, or scaling yet).

## 1. Core Objective
Design and implement a POC workflow engine that:
- Executes workflow definitions defined as DAGs (Directed Acyclic Graphs) in JSON/YAML.
- Supports sequential, parallel, and conditional branching.
- Can orchestrate three node types:
  - **Agent Nodes** — AI reasoning or decision agents (LLMs or logic handlers).
  - **Tool Nodes** — External APIs, functions, or utilities callable by the workflow.
  - **MCP Server Nodes** — External services compliant with the Model Context Protocol (Anthropic MCP).
- Is managed by a central **MCP Coordinator** (Runtime Engine) that:
  - Loads workflow definitions.
  - Manages execution order using graph traversal algorithms.
  - Maintains workflow context (state, outputs, and intermediate data).
  - Persists and resumes state safely.
  - Uses PostgreSQL as the persistence layer (with JSONB for context).

## 2. High-Level Architecture
### Components:
- **MCP Coordinator** (Workflow Runtime)
  - Orchestrates the DAG.
  - Evaluates conditions.
  - Handles sequential and parallel execution.
  - Manages execution context and updates persistence.
- **Workflow Definition Parser**
  - Reads JSON definitions.
  - Builds in-memory DAG structure (nodes + edges).
- **Node Executors**
  - AgentExecutor → Runs AI logic (e.g., LLM or scripted decision).
  - ToolExecutor → Calls external tools or APIs.
  - MCPServerExecutor → Connects to external MCP servers (following Anthropic MCP standard).
- **Persistence Layer**
  - PostgreSQL (JSONB-based schema).
  - Stores workflows, workflow runs, node executions, and context.
  - Ensures durable, resumable execution.
- **Context Manager**
  - Holds shared workflow state.
  - Supports merging outputs and retrieving previous node results.

## 3. Data Structures & Algorithms
### ✅ Data Structures
| Purpose | Recommended Structure | Reason |
|---------|----------------------|---------|
| Workflow DAG | Adjacency List (dict of node → children) | Efficient traversal and dependency resolution |
| Execution Queue | Queue / Topological Order List | Deterministic task scheduling |
| Workflow Context | Dictionary / JSONB in DB | Dynamic structure for arbitrary AI data |
| Node Registry | HashMap of node_id → NodeMetadata | O(1) lookup of node info during execution |
| State Store | Relational (Postgres tables) + JSONB | Fast indexing and flexible data |

### ⚙️ Algorithms
| Operation | Algorithm | Notes |
|-----------|-----------|-------|
| Execution Ordering | Topological Sort (Kahn's Algorithm) | Guarantees valid DAG traversal |
| Condition Evaluation | Safe expression parser (e.g., asteval, custom parser) | Secure conditional branching |
| Parallel Execution | ThreadPoolExecutor (Python) or async tasks | Simulate concurrency in POC |
| State Merge | Recursive Dict Merge (for JSON context) | Maintains dynamic state consistency |
| Fault Recovery | Resume from persisted node state | Enables durability and replay |

## 4. Database Schema (PostgreSQL)
Use PostgreSQL for persistence with the following schema:

```sql
CREATE TABLE workflows (
  id TEXT PRIMARY KEY,
  name TEXT,
  definition JSONB,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE workflow_runs (
  id TEXT PRIMARY KEY,
  workflow_id TEXT REFERENCES workflows(id),
  status TEXT,
  context JSONB,
  current_node TEXT,
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE node_executions (
  id TEXT PRIMARY KEY,
  run_id TEXT REFERENCES workflow_runs(id),
  node_id TEXT,
  node_type TEXT,
  status TEXT,
  input JSONB,
  output JSONB,
  started_at TIMESTAMP,
  finished_at TIMESTAMP
);
```

## 5. Example Workflow Definition (JSON)
```json
{
  "id": "ai_workflow_demo",
  "name": "AI Decision Workflow",
  "nodes": [
    {
      "id": "agent_decision",
      "type": "agent",
      "config": { "model": "claude-3.5", "prompt": "Classify request type." },
      "next": ["branch_condition"]
    },
    {
      "id": "branch_condition",
      "type": "condition",
      "expression": "context['agent_decision']['result'] == 'search'",
      "true": ["search_tool"],
      "false": ["mcp_server"]
    },
    {
      "id": "search_tool",
      "type": "tool",
      "config": { "tool": "web_search" },
      "next": ["final_summary"]
    },
    {
      "id": "mcp_server",
      "type": "mcp_server",
      "config": { "endpoint": "https://mcp.example.com/process" },
      "next": ["final_summary"]
    },
    {
      "id": "final_summary",
      "type": "agent",
      "config": { "model": "claude-3.5", "prompt": "Summarize results." }
    }
  ]
}
```

## 6. Key Technical Requirements
- **Language**: Python (preferred)
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Execution**: Local single-process orchestration (POC)
- **Error Handling**: Retry and mark node failure with reason
- **Extensibility**:
  - Each node type (agent/tool/mcp) as plugin class
  - New node types can be registered dynamically
- **AI Capability Support**:
  - Agent nodes can call LLMs or local reasoning logic
  - Tool nodes can execute any configured tool function
  - MCP Server nodes execute external services via API or local protocol

## 7. Deliverables
- **MCP Coordinator Implementation**
  - Core scheduler and runtime controller.
- **DAG Executor**
  - Handles sequential, parallel, and conditional nodes.
- **Persistence Layer**
  - SQLAlchemy models for workflow + runs + nodes.
- **Execution Context Manager**
  - Shared state store (with read/write/merge).
- **Plugin Registry**
  - Supports registering custom agent, tool, or MCP node handlers.
- **Demo Workflow**
  - Run example workflow (above) end-to-end, storing results in DB.

## 8. Non-Functional Requirements
- Simple POC — no auth, UI, or observability yet.
- Logs to console only.
- Modular, readable, and easy to extend.
- Future-ready for:
  - Distributed workers
  - Task queues (Redis, Kafka)
  - Observability layer
  - Versioning and visualization (BPMN-style)

## 9. Industry Inspiration
- **Temporal.io** — deterministic workflow execution and state management.
- **Camunda 8 / Zeebe** — declarative process orchestration (BPMN).
- **Airflow** — DAG traversal and dependency-based task scheduling.
- **LangGraph / CrewAI / AutoGen** — AI agent orchestration.
- **Anthropic MCP** (Model Context Protocol) — external tool and capability integration standard.

## ✅ Summary
Build an AI-native Workflow Engine (POC) powered by an MCP Coordinator, capable of executing Agents, Tools, and MCP Servers with full DAG orchestration (sequential, parallel, conditional), durable state persistence, and extensibility for AI workflows — aligning with Temporal, Camunda, and Anthropic MCP architecture best practices.