"""AI Workflow Engine - Pydantic Schema Models

Comprehensive schema definitions for workflow validation with support for:
- Multi-provider AI agents (OpenAI, Anthropic, Azure)
- Smart MCP tools with LLM-based tool discovery
- Tools and MCP server integrations
- Conditional branching and triggers
- DAG validation and dependency management
"""

import os
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


class NodeType(str, Enum):
    """Supported workflow node types."""
    START = "start"
    END = "end"
    AGENT = "agent"
    TOOL = "tool"
    MCP_TOOL = "mcp_tool"
    CONDITION = "condition"


class AIProvider(str, Enum):
    """Supported AI providers for agent nodes."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE = "azure"
    AZURE_OPENAI = "azure_openai"


class TriggerRule(str, Enum):
    """Node execution trigger rules."""
    ALL_SUCCESS = "all_success"      # All upstream nodes must succeed
    ONE_SUCCESS = "one_success"      # At least one upstream node succeeded
    ALL_DONE = "all_done"            # All upstream nodes completed (success or failure)
    ALWAYS = "always"                # Execute regardless of upstream status
    NONE_FAILED = "none_failed"      # Execute if no upstream nodes failed


# ============================================================================
# LLM CONFIGURATION SCHEMAS
# ============================================================================

class LLMConfig(BaseModel):
    """Unified LLM configuration with automatic environment variable loading."""
    
    # Core settings (configurable)
    provider: Literal["azure_openai", "openai", "anthropic", "ollama"] = "azure_openai"
    model: str = "gpt-4o-mini"
    temperature: float = Field(0.1, ge=0.0, le=2.0, description="LLM temperature")
    max_tokens: Optional[int] = Field(None, ge=100, le=32000, description="Maximum tokens (None = model default)")
    
    # Azure OpenAI configuration (configurable)
    endpoint: Optional[str] = Field(None, description="Azure OpenAI endpoint URL (auto-loaded from LLM_ENDPOINT)")
    api_version: str = Field("2024-08-01-preview", description="Azure API version")
    deployment: Optional[str] = Field(None, description="Azure deployment name (auto-loaded from model name)")
    
    # Authentication (auto-populated from environment)
    client_id: Optional[str] = Field(default=None, description="Auto-loaded from AZURE_OPENAI_CLIENT_ID")
    client_secret: Optional[str] = Field(default=None, description="Auto-loaded from AZURE_OPENAI_CLIENT_SECRET") 
    app_key: Optional[str] = Field(default=None, description="Auto-loaded from AZURE_OPENAI_APP_KEY")
    tenant_id: str = Field("common", description="Azure tenant ID")
    
    # Alternative API key authentication
    api_key: Optional[str] = Field(None, description="Direct API key (alternative to OAuth2)")
    
    def __init__(self, **data):
        """Initialize LLMConfig with automatic environment variable loading."""
        
        # Auto-populate provider from environment if not provided
        if 'provider' not in data or data['provider'] is None:
            data['provider'] = os.getenv("LLM_PROVIDER", "azure_openai")
            
        # Auto-populate model from environment if not provided  
        if 'model' not in data or data['model'] is None:
            data['model'] = os.getenv("AZURE_OPENAI_MODEL", "gpt-4o-mini")
            
        # Auto-populate endpoint from environment if not provided
        if 'endpoint' not in data or data['endpoint'] is None:
            data['endpoint'] = os.getenv("LLM_ENDPOINT", "https://chat-ai.cisco.com")
            
        # Auto-populate deployment from model name if not provided
        if 'deployment' not in data or data['deployment'] is None:
            data['deployment'] = data.get('model', 'gpt-4o-mini')
        
        # Auto-populate OAuth2 credentials from environment if not provided
        if 'client_id' not in data or data['client_id'] is None:
            data['client_id'] = os.getenv("AZURE_OPENAI_CLIENT_ID")
        
        if 'client_secret' not in data or data['client_secret'] is None:
            data['client_secret'] = os.getenv("AZURE_OPENAI_CLIENT_SECRET")
            
        if 'app_key' not in data or data['app_key'] is None:
            data['app_key'] = os.getenv("AZURE_OPENAI_APP_KEY")
        
        super().__init__(**data)
    
    @model_validator(mode='after')
    def validate_auth_config(self) -> 'LLMConfig':
        """Validate authentication configuration after environment loading."""
        if self.provider == "azure_openai":
            if not self.api_key and (not self.client_id or not self.client_secret):
                raise ValueError(
                    "Azure OpenAI requires either api_key or OAuth2 credentials. "
                    "Set AZURE_OPENAI_CLIENT_ID and AZURE_OPENAI_CLIENT_SECRET environment variables "
                    "or provide api_key in configuration."
                )
        return self


# ============================================================================
# NODE CONFIGURATION SCHEMAS
# ============================================================================

class AgentNodeConfig(BaseModel):
    """Simplified agent node configuration using unified LLMConfig."""
    
    llm_config: LLMConfig = Field(..., description="LLM configuration")
    prompt: str = Field(..., description="User prompt with template support")
    system_prompt: Optional[str] = Field(None, description="System instructions")
    
    # Response configuration
    response_format: Optional[Dict[str, Any]] = Field(None, description="JSON schema or output format")
    
    # Execution settings
    timeout: int = Field(120, ge=30, le=1800, description="Execution timeout")


class ToolNodeConfig(BaseModel):
    """Configuration schema for tool execution nodes."""

    tool_name: str = Field(..., description="Name of the tool to execute")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    timeout: int = Field(300, ge=1, le=3600, description="Execution timeout in seconds")
    retry_attempts: int = Field(3, ge=0, le=10, description="Number of retry attempts")

    @field_validator('tool_name')
    @classmethod
    def validate_tool_name(cls, v: str) -> str:
        """Validate tool name format."""
        if not v or not v.replace('_', '').replace('-', '').isalnum():
            raise ValueError("tool_name must be alphanumeric with underscores or hyphens")
        return v


class MCPServerConfig(BaseModel):
    """Generic configuration for MCP server connection supporting all transport types."""
    
    # Core transport configuration
    type: Literal["http", "stdio", "sse", "streamable-http"] = Field("http", description="MCP server transport type")
    
    # HTTP/SSE/Streamable-HTTP configuration
    url: Optional[str] = Field(None, description="Server URL (for http/sse/streamable-http types)")
    headers: Optional[Dict[str, str]] = Field(None, description="Custom HTTP headers")
    
    # Stdio configuration  
    command: Optional[str] = Field(None, description="Command to start stdio server")
    args: Optional[List[str]] = Field(None, description="Arguments for stdio server command")
    
    # Common configuration
    timeout: int = Field(30, ge=1, le=600, description="Connection timeout in seconds")
    retry_attempts: int = Field(3, ge=0, le=10, description="Max retry attempts")
    
    # Optional server identification
    name: Optional[str] = Field(None, description="Human-readable server name")
    description: Optional[str] = Field(None, description="Server description")
    
    @model_validator(mode='after')
    def validate_server_config(self) -> 'MCPServerConfig':
        """Validate server configuration based on transport type."""
        if self.type in ["http", "sse", "streamable-http"]:
            if not self.url:
                raise ValueError(f"{self.type} MCP server requires 'url' field")
            if not self.url.startswith(('http://', 'https://')):
                raise ValueError("MCP server url must be a valid HTTP/HTTPS URL")
                
            # Set default headers for streamable-http and sse
            if self.type in ["sse", "streamable-http"]:
                if not self.headers:
                    self.headers = {}
                if "Accept" not in self.headers:
                    self.headers["Accept"] = "application/json, text/event-stream"
                    
        elif self.type == "stdio":
            if not self.command:
                raise ValueError("stdio MCP server requires 'command' field")
                
        return self


class MCPToolNodeConfig(BaseModel):
    """MCP tool configuration supporting both smart and direct execution modes."""
    
    # MCP Server
    server: MCPServerConfig = Field(..., description="MCP server configuration")
    
    # Execution mode
    smart_mcp_enabled: bool = Field(True, description="Enable smart MCP mode")
    
    # Smart execution fields (required when smart_mcp_enabled=True)
    llm_config: Optional[LLMConfig] = Field(None, description="LLM configuration for smart mode") 
    user_prompt: Optional[str] = Field(None, description="Natural language task description for smart mode")
    context_data: Dict[str, Any] = Field(default_factory=dict, description="Template variables")
    
    # Direct execution fields (required when smart_mcp_enabled=False)
    tool_name: Optional[str] = Field(None, description="Specific tool name for direct mode")
    tool_arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments for direct mode")
    
    # Common execution behavior
    preferred_tools: Optional[List[str]] = Field(None, description="Tool selection hints")
    max_tool_calls: int = Field(10, ge=1, le=20, description="Maximum tool calls per execution")
    output_format: Literal["auto", "json", "text"] = Field("auto", description="Expected output format")
    timeout: int = Field(300, ge=30, le=1800, description="Total execution timeout")
    
    @model_validator(mode='after')
    def validate_mode_requirements(self) -> 'MCPToolNodeConfig':
        """Validate configuration based on execution mode."""
        if self.smart_mcp_enabled:
            if not self.llm_config:
                raise ValueError("smart_mcp_enabled=True requires llm_config")
            if not self.user_prompt:
                raise ValueError("smart_mcp_enabled=True requires user_prompt")
        else:
            if not self.tool_name:
                raise ValueError("smart_mcp_enabled=False requires tool_name")
        return self


class ConditionRule(BaseModel):
    """Single condition rule for evaluation."""
    name: str = Field(..., description="Rule name for identification")
    value: Union[str, int, float, bool] = Field(..., description="Expected value to match against")
    target: str = Field(..., description="Target node ID if condition matches")
    case_sensitive: bool = Field(True, description="Whether string matching should be case sensitive")


class ConditionNodeConfig(BaseModel):
    """Configuration schema for enterprise-grade conditional branching nodes."""
    condition_type: str = Field(..., description="Type of condition evaluation (string_match, numeric_comparison, etc.)")
    input_source: str = Field(..., description="Template string to resolve input value from context")
    rules: List[ConditionRule] = Field(..., description="List of condition rules to evaluate")
    default_target: Optional[str] = Field(None, description="Default target node if no rules match")
    timeout: int = Field(60, ge=1, le=300, description="Condition evaluation timeout")
    
    @field_validator('condition_type')
    @classmethod
    def validate_condition_type(cls, v: str) -> str:
        """Validate condition type is supported."""
        valid_types = ['string_match', 'string_contains', 'regex_match', 'numeric_comparison', 
                      'boolean_check', 'json_path', 'range_check', 'list_contains', 'custom']
        if v not in valid_types:
            raise ValueError(f"condition_type must be one of: {valid_types}")
        return v
    
    @field_validator('input_source')
    @classmethod
    def validate_input_source(cls, v: str) -> str:
        """Basic validation of input source template."""
        if not v or len(v.strip()) == 0:
            raise ValueError("input_source cannot be empty")
        return v.strip()


class StartNodeConfig(BaseModel):
    """Configuration schema for workflow start nodes."""
    
    name: Optional[str] = Field(None, description="Optional start node name")
    description: Optional[str] = Field(None, description="Optional start node description")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Optional metadata")


class EndNodeConfig(BaseModel):
    """Configuration schema for workflow end nodes."""
    
    name: Optional[str] = Field(None, description="Optional end node name") 
    description: Optional[str] = Field(None, description="Optional end node description")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Optional metadata")
    collect_outputs: bool = Field(True, description="Whether to collect workflow outputs")


# ============================================================================
# CORE WORKFLOW SCHEMAS
# ============================================================================

class WorkflowNode(BaseModel):
    """Individual workflow node definition."""

    id: str = Field(..., description="Unique node identifier")
    type: NodeType = Field(..., description="Node type")
    config: Dict[str, Any] = Field(..., description="Node-specific configuration")

    # Dependency configuration
    dependencies: List[str] = Field(default_factory=list, description="Required predecessor nodes")
    next: Optional[List[str]] = Field(None, description="Successor nodes")
    trigger_rule: TriggerRule = Field(TriggerRule.ALL_SUCCESS, description="Execution trigger rule")

    # Metadata
    name: Optional[str] = Field(None, description="Human-readable node name")
    description: Optional[str] = Field(None, description="Node documentation")
    alias: Optional[str] = Field(None, description="Human-readable alias for template variable references")
    tags: List[str] = Field(default_factory=list, description="Node tags for organization")

    @field_validator('id')
    @classmethod
    def validate_node_id(cls, v: str) -> str:
        """Validate node ID format and uniqueness."""
        if not v or len(v.strip()) == 0:
            raise ValueError("node id cannot be empty")

        # Must be valid identifier-like string
        clean_id = v.replace('_', '').replace('-', '')
        if not clean_id.isalnum():
            raise ValueError("node id must be alphanumeric with underscores or hyphens")

        return v.strip()

    @field_validator('dependencies', 'next')
    @classmethod
    def validate_node_references(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate node reference lists."""
        if v is None:
            return v

        # Check for duplicates
        if len(v) != len(set(v)):
            raise ValueError("node references cannot contain duplicates")

        # Validate each reference format
        for ref in v:
            if not ref or len(ref.strip()) == 0:
                raise ValueError("node references cannot be empty strings")

        return v

    @model_validator(mode='after')
    def validate_node_config(self) -> 'WorkflowNode':
        """Validate node configuration based on node type."""
        config_classes = {
            NodeType.START: StartNodeConfig,
            NodeType.END: EndNodeConfig,
            NodeType.AGENT: AgentNodeConfig,
            NodeType.TOOL: ToolNodeConfig,
            NodeType.MCP_TOOL: MCPToolNodeConfig,
            NodeType.CONDITION: ConditionNodeConfig,
        }
        
        if self.type in config_classes:
            config_class = config_classes[self.type]
            try:
                # Validate the config dict against the appropriate schema
                config_class.model_validate(self.config)
            except Exception as e:
                raise ValueError(f"Invalid config for {self.type} node '{self.id}': {str(e)}")
        
        return self


class WorkflowMetadata(BaseModel):
    """Workflow metadata and configuration."""

    version: str = Field("1.0", description="Workflow schema version")
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")
    author: Optional[str] = Field(None, description="Workflow author")
    tags: List[str] = Field(default_factory=list, description="Workflow tags")

    # Execution configuration
    max_parallel_nodes: int = Field(10, ge=1, le=100, description="Maximum parallel node execution")
    default_timeout: int = Field(300, ge=1, le=3600, description="Default node timeout")
    retry_policy: Dict[str, Any] = Field(default_factory=dict, description="Default retry configuration")


class WorkflowDefinition(BaseModel):
    """Complete workflow definition with validation."""

    # Core identification
    id: str = Field(..., description="Unique workflow identifier")
    name: str = Field(..., description="Human-readable workflow name")
    description: Optional[str] = Field(None, description="Workflow documentation")

    # Workflow structure
    nodes: List[WorkflowNode] = Field(..., min_length=1, description="Workflow nodes")

    # Configuration and metadata
    metadata: WorkflowMetadata = Field(default_factory=WorkflowMetadata, description="Workflow metadata")

    @field_validator('id')
    @classmethod
    def validate_workflow_id(cls, v: str) -> str:
        """Validate workflow ID format."""
        if not v or len(v.strip()) == 0:
            raise ValueError("workflow id cannot be empty")

        # Must be valid identifier-like string
        clean_id = v.replace('_', '').replace('-', '')
        if not clean_id.isalnum():
            raise ValueError("workflow id must be alphanumeric with underscores or hyphens")

        return v.strip()

    @field_validator('name')
    @classmethod
    def validate_workflow_name(cls, v: str) -> str:
        """Validate workflow name."""
        if not v or len(v.strip()) == 0:
            raise ValueError("workflow name cannot be empty")
        return v.strip()

    @model_validator(mode='after')
    def validate_workflow_structure(self) -> 'WorkflowDefinition':
        """Validate overall workflow structure and consistency."""
        # Check for duplicate node IDs
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("workflow contains duplicate node IDs")

        # Validate node references exist
        node_id_set = set(node_ids)

        for node in self.nodes:
            # Check dependencies exist
            for dep in node.dependencies:
                if dep not in node_id_set:
                    raise ValueError(f"node '{node.id}' references non-existent dependency '{dep}'")

            # Check next nodes exist
            if node.next:
                for next_node in node.next:
                    if next_node not in node_id_set:
                        raise ValueError(f"node '{node.id}' references non-existent next node '{next_node}'")

        return self


# ============================================================================
# VALIDATION RESULT SCHEMAS
# ============================================================================

class ValidationError(BaseModel):
    """Individual validation error details."""

    field: str = Field(..., description="Field that failed validation")
    message: str = Field(..., description="Error message")
    value: Any = Field(None, description="Invalid value that caused the error")
    node_id: Optional[str] = Field(None, description="Node ID if error is node-specific")


class ValidationResult(BaseModel):
    """Comprehensive validation result."""

    valid: bool = Field(..., description="Whether validation passed")
    errors: List[ValidationError] = Field(default_factory=list, description="Validation errors")
    warnings: List[str] = Field(default_factory=list, description="Validation warnings")

    # Performance metrics
    validation_time_ms: Optional[float] = Field(None, description="Validation time in milliseconds")
    node_count: Optional[int] = Field(None, description="Number of nodes validated")

    def add_error(self, field: str, message: str, value: Any = None, node_id: str = None) -> None:
        """Add validation error."""
        self.errors.append(ValidationError(
            field=field,
            message=message,
            value=value,
            node_id=node_id
        ))
        self.valid = False

    def add_warning(self, message: str) -> None:
        """Add validation warning."""
        self.warnings.append(message)


# ============================================================================
# SIMPLIFIED API RESPONSE SCHEMAS
# ============================================================================

class SimpleNodeResult(BaseModel):
    """Simplified node execution result for API responses."""
    
    node_id: str = Field(..., description="ID of the executed node")
    node_name: str = Field(..., description="Human-readable name of the node")
    node_type: str = Field(..., description="Type of the node")
    status: str = Field(..., description="Execution status (success, failed, etc.)")
    response: Optional[str] = Field(None, description="Simple text response from the node")
    structured_output: Optional[Dict[str, Any]] = Field(None, description="JSON object of the response structured according to node definition")
    error: Optional[str] = Field(None, description="Error message if failed")


class SimpleWorkflowExecutionResponse(BaseModel):
    """Simplified workflow execution response with clean node array and per-node structured output."""
    
    run_id: str = Field(..., description="Unique execution run ID")
    workflow_id: str = Field(..., description="Workflow definition ID")
    status: str = Field(..., description="Overall execution status")
    success: bool = Field(..., description="Whether execution was successful")
    started_at: str = Field(..., description="ISO timestamp when execution started")
    finished_at: Optional[str] = Field(None, description="ISO timestamp when execution finished")
    duration_seconds: Optional[float] = Field(None, description="Total execution time in seconds")
    nodes: List[SimpleNodeResult] = Field(
        default_factory=list,
        description="Array of node execution results in execution order with structured outputs"
    )