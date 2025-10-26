"""AI Workflow Engine - Pydantic Schema Models

Comprehensive schema definitions for workflow validation with support for:
- Multi-provider AI agents (OpenAI, Anthropic, Azure)
- Tools and MCP server integrations
- Conditional branching and triggers
- DAG validation and dependency management
"""

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
# NODE CONFIGURATION SCHEMAS
# ============================================================================

class AgentNodeConfig(BaseModel):
    """Configuration schema for AI agent nodes with multi-provider support."""

    # Core configuration
    provider: AIProvider = Field(..., description="AI provider (openai, anthropic, azure)")
    model: str = Field(..., description="Model name (e.g., gpt-4, claude-3-sonnet)")
    prompt: str = Field(..., description="Prompt template with variable substitution")

    # Generation parameters
    max_tokens: int = Field(1000, ge=1, le=100000, description="Maximum tokens to generate")
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="Sampling temperature")
    system_prompt: Optional[str] = Field(None, description="System instructions")

    # Azure-specific configuration
    azure_endpoint: Optional[str] = Field(None, description="Azure OpenAI endpoint URL")
    azure_deployment: Optional[str] = Field(None, description="Azure deployment name")
    api_version: Optional[str] = Field(None, description="Azure API version")

    # Execution configuration
    timeout: int = Field(120, ge=1, le=3600, description="Request timeout in seconds")
    retry_attempts: int = Field(3, ge=0, le=10, description="Number of retry attempts")

    @model_validator(mode='after')
    def validate_provider_config(self) -> 'AgentNodeConfig':
        """Validate provider-specific configuration requirements."""
        if self.provider == AIProvider.AZURE:
            required_azure_fields = {
                'azure_endpoint': self.azure_endpoint,
                'azure_deployment': self.azure_deployment,
                'api_version': self.api_version
            }

            missing_fields = [
                field_name for field_name, field_value in required_azure_fields.items()
                if not field_value
            ]

            if missing_fields:
                raise ValueError(
                    f"Azure provider requires the following fields: {', '.join(missing_fields)}"
                )

            # Validate Azure endpoint format
            if self.azure_endpoint and not self.azure_endpoint.startswith(('http://', 'https://')):
                raise ValueError("azure_endpoint must be a valid HTTP/HTTPS URL")

        return self


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
    """Configuration for MCP server connection."""
    
    type: Literal["http", "stdio"] = Field("http", description="MCP server connection type")
    url: Optional[str] = Field(None, description="HTTP server URL (for http type)")
    command: Optional[str] = Field(None, description="Command to start stdio server")
    args: Optional[List[str]] = Field(None, description="Arguments for stdio server command")
    timeout: int = Field(30, ge=1, le=300, description="Connection timeout in seconds")
    
    @model_validator(mode='after')
    def validate_server_config(self) -> 'MCPServerConfig':
        """Validate server configuration based on type."""
        if self.type == "http":
            if not self.url:
                raise ValueError("HTTP MCP server requires 'url' field")
            if not self.url.startswith(('http://', 'https://')):
                raise ValueError("MCP server url must be a valid HTTP/HTTPS URL")
        elif self.type == "stdio":
            if not self.command:
                raise ValueError("stdio MCP server requires 'command' field")
        return self


class MCPToolNodeConfig(BaseModel):
    """Configuration schema for MCP (Model Context Protocol) tool nodes."""

    server: MCPServerConfig = Field(..., description="Embedded MCP server configuration")
    tool_name: str = Field(..., description="Name of the tool to execute on MCP server")
    tool_arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments with template support")
    output_format: Optional[str] = Field("auto", description="Output format: 'auto', 'text', 'json', 'json_object'")
    timeout: int = Field(300, ge=1, le=3600, description="Tool execution timeout in seconds")
    retry_attempts: int = Field(3, ge=0, le=10, description="Number of retry attempts on failure")

    @field_validator('tool_name')
    @classmethod
    def validate_tool_name(cls, v: str) -> str:
        """Validate MCP tool name format."""
        if not v or len(v.strip()) == 0:
            raise ValueError("tool_name cannot be empty")
        # Allow more flexible tool names for MCP
        return v.strip()


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