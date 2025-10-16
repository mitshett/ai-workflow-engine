# AI Workflow Engine

A next-generation AI-native workflow orchestration system capable of executing complex workflows with Agents, Tools, and MCP (Model Context Protocol) Servers using DAG-based execution with durable state persistence.

## 🎯 Overview

The AI Workflow Engine is designed to orchestrate sophisticated AI workflows through:

- **DAG-based Execution**: Sequential, parallel, and conditional branching using topological sorting
- **Durable State Management**: Event sourcing with snapshots for reliable workflow persistence
- **AI-First Design**: Native support for AI agents, external tools, and MCP server integration
- **Plugin Architecture**: Extensible node types and custom execution logic
- **Production Ready**: Built with performance, reliability, and scalability in mind

## 🏗️ Architecture

### Core Components

- **MCP Coordinator**: Central workflow runtime that orchestrates DAG execution
- **Node Executors**: Specialized handlers for different node types (Agent, Tool, MCP Server)
- **Persistence Layer**: PostgreSQL with JSONB for flexible context storage
- **Event Sourcing**: Immutable event log with snapshot optimization
- **Context Manager**: Thread-safe workflow state management

### Supported Node Types

1. **Agent Nodes**: AI reasoning and decision-making (LLM integration)
2. **Tool Nodes**: External API calls and utility functions
3. **MCP Server Nodes**: Integration with Model Context Protocol compliant services
4. **Condition Nodes**: Dynamic branching based on expression evaluation

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 15+
- Poetry (for dependency management)

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd ai-workflow-engine
```

2. Install dependencies with Poetry:
```bash
poetry install
```

3. Set up the database:
```bash
# Create PostgreSQL database
createdb ai_workflow_engine

# Run migrations (coming in Phase 1)
poetry run workflow-engine db migrate
```

4. Start the engine:
```bash
poetry run workflow-engine start
```

## 📋 Example Workflow

```json
{
  "id": "ai_analysis_workflow",
  "name": "AI Data Analysis Pipeline",
  "nodes": [
    {
      "id": "data_agent",
      "type": "agent",
      "config": {
        "provider": "anthropic",
        "model": "claude-3-5-sonnet-20241022",
        "prompt": "Analyze the input data: ${context.input}"
      },
      "next": ["condition_check"]
    },
    {
      "id": "condition_check",
      "type": "condition",
      "expression": "context['data_agent']['confidence'] > 0.8",
      "true": ["process_data"],
      "false": ["review_data"]
    },
    {
      "id": "process_data",
      "type": "mcp_server",
      "config": {
        "server_id": "data_processor",
        "tool": "process_dataset",
        "arguments": {
          "data": "${context.data_agent.result}"
        }
      },
      "next": ["generate_report"]
    },
    {
      "id": "generate_report",
      "type": "agent",
      "config": {
        "provider": "openai",
        "model": "gpt-4",
        "prompt": "Generate a comprehensive report: ${context.process_data.output}"
      }
    }
  ]
}
```

## 🛠️ Development

### Project Structure

```
ai-workflow-engine/
├── src/
│   ├── workflow_engine/          # Main engine package
│   │   ├── core/                # Core orchestration logic
│   │   ├── executors/           # Node type executors
│   │   ├── persistence/         # Database models and persistence
│   │   └── mcp/                 # MCP protocol integration
│   ├── config/                  # Configuration management
│   └── cli/                     # Command line interface
├── tests/                       # Test suite
├── docs/                        # Documentation
└── pyproject.toml              # Project configuration
```

### Running Tests

```bash
# Run all tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=workflow_engine

# Run specific test file
poetry run pytest tests/unit/test_coordinator.py
```

### Code Quality

```bash
# Format code
poetry run black src/ tests/

# Sort imports
poetry run isort src/ tests/

# Lint code
poetry run flake8 src/ tests/

# Type checking
poetry run mypy src/
```

## 📊 Technology Stack

- **Language**: Python 3.11+
- **Database**: PostgreSQL 15+ with JSONB support
- **ORM**: SQLAlchemy 2.0 with async support
- **MCP Integration**: Anthropic MCP SDK
- **AI Providers**: OpenAI, Anthropic Claude
- **Web Framework**: FastAPI (for REST API)
- **Testing**: pytest with async support
- **Code Quality**: Black, isort, flake8, mypy

## 🗺️ Development Roadmap

### Phase 1: Foundation (Weeks 1-3)
- ✅ Project structure and configuration
- 🔄 Database schema and models
- 🔄 Core workflow parser and DAG builder
- 🔄 Basic sequential execution

### Phase 2: Advanced Features (Weeks 4-6)
- 📋 Parallel execution engine
- 📋 Conditional branching and triggers
- 📋 Event sourcing and snapshots

### Phase 3: MCP Integration (Weeks 7-10)
- 📋 MCP server registry and connections
- 📋 Protocol implementations (stdio, HTTP)
- 📋 Tool execution and result processing

### Phase 4: Production Ready (Weeks 11-14)
- 📋 Error handling and resilience
- 📋 Performance optimization
- 📋 Monitoring and observability
- 📋 Security and deployment

### Phase 5: Advanced Features (Weeks 15-18)
- 📋 Plugin system and extensibility
- 📋 REST API and integrations
- 📋 Distributed execution planning

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Guidelines

- Follow PEP 8 style guidelines
- Add type hints for all functions and methods
- Write comprehensive tests for new features
- Update documentation for API changes
- Use structured logging for all operations

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Inspired by [Temporal.io](https://temporal.io) for durable execution patterns
- [Apache Airflow](https://airflow.apache.org) for DAG orchestration concepts
- [Camunda](https://camunda.com) for workflow modeling approaches
- [Anthropic MCP](https://modelcontextprotocol.io) for standardized AI tool integration

## 📞 Support

- 📖 [Documentation](docs/)
- 🐛 [Issue Tracker](https://github.com/your-org/ai-workflow-engine/issues)
- 💬 [Discussions](https://github.com/your-org/ai-workflow-engine/discussions)
- 📧 Email: support@ai-workflow-engine.com

---

Built with ❤️ for the AI automation community