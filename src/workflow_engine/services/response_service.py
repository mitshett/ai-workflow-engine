"""
Response transformation service for the AI Workflow Engine.

This service contains the CENTRALIZED response transformation logic that
ELIMINATES the ~150 lines of duplicate code scattered throughout the API layer.

This is the SINGLE IMPLEMENTATION that replaces all duplicate conversion functions:
- _convert_to_simple_execution_response()
- _convert_to_execution_response() 
- _extract_simple_response()
- _create_structured_output()

Author: AI Workflow Engine Team
"""

import logging
from typing import Dict, List, Optional, Any

from ..domain.models import NodeResult
from ..domain.enums.node_types import NodeType
from ..shared.schemas.responses.execution import NodeData


class ResponseService:
    """
    Centralized response transformation service.
    
    This service eliminates code duplication by providing a single,
    comprehensive implementation for converting domain objects to
    API response formats. All response conversion logic is centralized
    here to ensure consistency and maintainability.
    """
    
    def __init__(self):
        """Initialize the response service."""
        self.logger = logging.getLogger(__name__)
    
    @staticmethod
    def convert_node_results_to_api_format(
        node_results: List[NodeResult],
        workflow_input: Dict[str, Any] = None
    ) -> List[NodeData]:
        """
        Convert domain NodeResult objects to API NodeData format.
        
        This is the **SINGLE IMPLEMENTATION** that replaces all duplicate
        node result conversion functions throughout the codebase.
        
        Args:
            node_results: List of domain NodeResult objects
            workflow_input: Optional workflow input data for context
            
        Returns:
            List of NodeData objects for API responses
        """
        if not node_results:
            return []
        
        api_nodes = []
        for node_result in node_results:
            try:
                node_data = ResponseService._convert_single_node_result(
                    node_result, 
                    workflow_input or {}
                )
                api_nodes.append(node_data)
                
            except Exception as e:
                # Log error but continue processing other nodes
                logging.getLogger(__name__).error(
                    f"Failed to convert node result {node_result.node_id}: {str(e)}"
                )
                
                # Create minimal error node data
                api_nodes.append(NodeData(
                    node_id=node_result.node_id,
                    node_name=node_result.node_id,
                    node_type=node_result.node_type.value,
                    status="error",
                    error=f"Response conversion failed: {str(e)}",
                    response="Error processing node result",
                    structured_output={},
                    has_output=False
                ))
        
        return api_nodes
    
    @staticmethod
    def _convert_single_node_result(
        node_result: NodeResult, 
        workflow_input: Dict[str, Any]
    ) -> NodeData:
        """
        Convert a single NodeResult to NodeData.
        
        Args:
            node_result: Domain NodeResult object
            workflow_input: Workflow input data for context
            
        Returns:
            NodeData object for API response
        """
        # Extract simple response text - CENTRALIZED LOGIC
        simple_response = ResponseService.extract_simple_response(node_result)
        
        # Extract structured output - CENTRALIZED LOGIC  
        structured_output = ResponseService.extract_structured_output(node_result)
        
        # Create NodeData with all timing and metadata
        return NodeData(
            node_id=node_result.node_id,
            node_name=ResponseService._get_node_display_name(node_result),
            node_type=node_result.node_type.value,
            status=node_result.status.value,
            started_at=node_result.started_at.isoformat() if node_result.started_at else None,
            finished_at=node_result.finished_at.isoformat() if node_result.finished_at else None,
            duration_seconds=node_result.duration_seconds,
            response=simple_response,
            structured_output=structured_output,
            error=node_result.error.message if node_result.error else None,
            attempts=node_result.attempts,
            has_output=node_result.has_output
        )
    
    @staticmethod
    def extract_simple_response(node_result: NodeResult) -> str:
        """
        Extract simple text response from node result.
        
        This **SINGLE IMPLEMENTATION** replaces all the duplicate
        _extract_simple_response functions with consistent logic
        for all node types.
        
        Args:
            node_result: Domain NodeResult object
            
        Returns:
            Simple text response extracted from node output
        """
        if not node_result:
            return ""
        
        node_type = node_result.node_type
        data = node_result.data
        output = node_result.output
        
        # Handle different node types with centralized logic
        if node_type == NodeType.START:
            return ResponseService._extract_start_node_response(node_result, data)
        
        elif node_type == NodeType.END:
            return ResponseService._extract_end_node_response(node_result, data)
        
        elif node_type == NodeType.AGENT:
            return ResponseService._extract_agent_response(node_result, data, output)
        
        elif node_type == NodeType.TOOL:
            return ResponseService._extract_tool_response(node_result, data, output)
        
        elif node_type == NodeType.MCP_TOOL:
            return ResponseService._extract_mcp_tool_response(node_result, data, output)
        
        elif node_type == NodeType.CONDITION:
            return ResponseService._extract_condition_response(node_result, data, output)
        
        else:
            # Default fallback for unknown node types
            return ResponseService._extract_default_response(node_result, data, output)
    
    @staticmethod
    def extract_structured_output(node_result: NodeResult) -> Dict[str, Any]:
        """
        Extract structured output from node result based on node configuration.
        
        This **SINGLE IMPLEMENTATION** replaces all duplicate structured
        output extraction logic with consistent handling for all node types.
        
        Args:
            node_result: Domain NodeResult object
            
        Returns:
            Structured output dictionary when available
        """
        if not node_result or not node_result.has_output:
            return {}
        
        node_type = node_result.node_type
        data = node_result.data
        output = node_result.output
        
        # Handle structured output extraction by node type
        if node_type == NodeType.AGENT:
            return ResponseService._extract_agent_structured_output(data, output)
        
        elif node_type == NodeType.MCP_TOOL:
            return ResponseService._extract_mcp_structured_output(data, output)
        
        elif node_type == NodeType.TOOL:
            return ResponseService._extract_tool_structured_output(data, output)
        
        elif node_type == NodeType.CONDITION:
            return ResponseService._extract_condition_structured_output(data, output)
        
        else:
            # START, END, and other nodes typically don't have structured output
            return {}
    
    # Private helper methods for different node types
    
    @staticmethod
    def _extract_start_node_response(
        node_result: NodeResult, 
        data: Dict[str, Any]
    ) -> str:
        """Extract response text from START node."""
        node_name = ResponseService._get_node_display_name(node_result)
        if isinstance(data, dict) and 'message' in data:
            return data['message']
        return f"Workflow started at {node_name}"
    
    @staticmethod
    def _extract_end_node_response(
        node_result: NodeResult, 
        data: Dict[str, Any]
    ) -> str:
        """Extract response text from END node."""
        node_name = ResponseService._get_node_display_name(node_result)
        if isinstance(data, dict) and 'message' in data:
            return data['message']
        return f"Workflow completed at {node_name}"
    
    @staticmethod
    def _extract_agent_response(
        node_result: NodeResult, 
        data: Dict[str, Any], 
        output: Any
    ) -> str:
        """Extract response text from AGENT node."""
        # Priority order for agent responses:
        # 1. Direct response field in data
        # 2. Response in full sub-object
        # 3. Direct output
        # 4. Fallback message
        
        if isinstance(data, dict):
            # Check for direct response
            if 'response' in data:
                response = data['response']
                return ResponseService._truncate_response(str(response))
            
            # Check for response in full object
            if 'full' in data and isinstance(data['full'], dict):
                full_data = data['full']
                if 'response' in full_data:
                    response = full_data['response']
                    return ResponseService._truncate_response(str(response))
        
        # Check direct output
        if output is not None:
            return ResponseService._truncate_response(str(output))
        
        # Fallback
        return "AI agent executed successfully"
    
    @staticmethod
    def _extract_tool_response(
        node_result: NodeResult, 
        data: Dict[str, Any], 
        output: Any
    ) -> str:
        """Extract response text from TOOL node."""
        if isinstance(data, dict):
            # Check for result field
            if 'result' in data:
                result = data['result']
                return ResponseService._truncate_response(str(result))
            
            # Check for output field
            if 'output' in data:
                tool_output = data['output']
                return ResponseService._truncate_response(str(tool_output))
        
        # Check direct output
        if output is not None:
            return ResponseService._truncate_response(str(output))
        
        # Fallback
        return "Tool executed successfully"
    
    @staticmethod
    def _extract_mcp_tool_response(
        node_result: NodeResult, 
        data: Dict[str, Any], 
        output: Any
    ) -> str:
        """Extract response text from MCP_TOOL node."""
        if isinstance(data, dict):
            # Check for result field (common in MCP responses)
            if 'result' in data:
                result = data['result']
                return ResponseService._truncate_response(str(result))
            
            # Check for content field
            if 'content' in data:
                content = data['content']
                return ResponseService._truncate_response(str(content))
            
            # Check for response field
            if 'response' in data:
                response = data['response']
                return ResponseService._truncate_response(str(response))
        
        # Check direct output
        if output is not None:
            return ResponseService._truncate_response(str(output))
        
        # Fallback
        return "MCP tool executed successfully"
    
    @staticmethod
    def _extract_condition_response(
        node_result: NodeResult, 
        data: Dict[str, Any], 
        output: Any
    ) -> str:
        """Extract response text from CONDITION node."""
        if isinstance(data, dict):
            # Check for selected target/branch
            if 'selected_target' in data:
                target = data['selected_target']
                return f"Condition evaluated, selected: {target}"
            
            if 'selected_branch' in data:
                branch = data['selected_branch']
                return f"Condition evaluated, selected branch: {branch}"
            
            # Check for evaluation result
            if 'evaluation_result' in data:
                result = data['evaluation_result']
                return f"Condition evaluated to: {result}"
        
        # Check direct output
        if output is not None:
            return f"Condition evaluated: {output}"
        
        # Fallback
        return "Condition evaluated successfully"
    
    @staticmethod
    def _extract_default_response(
        node_result: NodeResult, 
        data: Dict[str, Any], 
        output: Any
    ) -> str:
        """Extract response text from unknown node types."""
        if isinstance(data, dict) and 'message' in data:
            return str(data['message'])
        
        if output is not None:
            return ResponseService._truncate_response(str(output))
        
        return f"{node_result.node_type.value} node executed successfully"
    
    @staticmethod
    def _extract_agent_structured_output(
        data: Dict[str, Any], 
        output: Any
    ) -> Dict[str, Any]:
        """Extract structured output from AGENT node when available."""
        if not isinstance(data, dict):
            return {}
        
        # Check for parsed structured response (JSON schema output)
        if 'parsed' in data:
            parsed = data['parsed']
            if isinstance(parsed, dict):
                return parsed
        
        # Check for structured response in full object
        if 'full' in data and isinstance(data['full'], dict):
            full_data = data['full']
            if 'parsed' in full_data and isinstance(full_data['parsed'], dict):
                return full_data['parsed']
        
        # If output is structured, return it
        if isinstance(output, dict):
            return output
        
        return {}
    
    @staticmethod
    def _extract_mcp_structured_output(
        data: Dict[str, Any], 
        output: Any
    ) -> Dict[str, Any]:
        """Extract structured output from MCP_TOOL node when available."""
        if not isinstance(data, dict):
            return {}
        
        # Priority 1: Check for parsed JSON data (contains actual MCP response data)
        if 'parsed' in data:
            parsed = data['parsed']
            if isinstance(parsed, dict):
                return parsed
        
        # Priority 2: Check for structured result
        if 'result' in data:
            result = data['result']
            if isinstance(result, dict):
                return result
        
        # Priority 3: Check for structured content
        if 'content' in data:
            content = data['content']
            if isinstance(content, dict):
                return content
        
        # Priority 4: If output is structured, return it
        if isinstance(output, dict):
            return output
        
        return {}
    
    @staticmethod
    def _extract_tool_structured_output(
        data: Dict[str, Any], 
        output: Any
    ) -> Dict[str, Any]:
        """Extract structured output from TOOL node when available."""
        if not isinstance(data, dict):
            return {}
        
        # Check for structured result
        if 'result' in data:
            result = data['result']
            if isinstance(result, dict):
                return result
        
        # Check for structured output
        if 'output' in data:
            tool_output = data['output']
            if isinstance(tool_output, dict):
                return tool_output
        
        # If output is structured, return it
        if isinstance(output, dict):
            return output
        
        return {}
    
    @staticmethod
    def _extract_condition_structured_output(
        data: Dict[str, Any], 
        output: Any
    ) -> Dict[str, Any]:
        """Extract structured output from CONDITION node when available."""
        if not isinstance(data, dict):
            return {}
        
        # Condition nodes can have evaluation details
        structured = {}
        
        if 'evaluation_result' in data:
            structured['evaluation_result'] = data['evaluation_result']
        
        if 'selected_target' in data:
            structured['selected_target'] = data['selected_target']
        
        if 'selected_branch' in data:
            structured['selected_branch'] = data['selected_branch']
        
        if 'expression' in data:
            structured['expression'] = data['expression']
        
        # If output is structured, merge it
        if isinstance(output, dict):
            structured.update(output)
        
        return structured if structured else {}
    
    @staticmethod
    def _get_node_display_name(node_result: NodeResult) -> str:
        """
        Get display name for a node from various possible sources.
        
        Args:
            node_result: Domain NodeResult object
            
        Returns:
            Human-readable node name
        """
        # Try to get name from data
        if isinstance(node_result.data, dict):
            # Check for node_name field
            if 'node_name' in node_result.data:
                return str(node_result.data['node_name'])
            
            # Check for name field
            if 'name' in node_result.data:
                return str(node_result.data['name'])
        
        # Fallback to node ID
        return node_result.node_id
    
    @staticmethod
    def _truncate_response(response: str, max_length: int = 0) -> str:
        """
        Optionally truncate response text if max_length is set.
        
        Args:
            response: Response text to truncate
            max_length: Maximum length before truncation (0 = no limit)
            
        Returns:
            Response text, truncated with ellipsis only if max_length > 0
        """
        if not isinstance(response, str):
            response = str(response)
        
        if max_length <= 0 or len(response) <= max_length:
            return response
        
        return response[:max_length] + "..."
    
    @staticmethod
    def create_error_node_data(
        node_id: str,
        node_type: str,
        error_message: str,
        node_name: Optional[str] = None
    ) -> NodeData:
        """
        Create NodeData for a node that failed to process.
        
        Args:
            node_id: Node identifier
            node_type: Node type string
            error_message: Error description
            node_name: Optional node display name
            
        Returns:
            NodeData representing the error state
        """
        return NodeData(
            node_id=node_id,
            node_name=node_name or node_id,
            node_type=node_type,
            status="failed",
            error=error_message,
            response=f"Node processing failed: {error_message}",
            structured_output={},
            has_output=False
        )
    
    @staticmethod
    def validate_response_data(node_data: NodeData) -> bool:
        """
        Validate that NodeData contains required fields and reasonable values.
        
        Args:
            node_data: NodeData to validate
            
        Returns:
            True if data is valid, False otherwise
        """
        try:
            # Check required fields
            if not node_data.node_id or not node_data.node_type:
                return False
            
            # Check status is reasonable
            valid_statuses = ["pending", "running", "success", "failed", "skipped", "timeout"]
            if node_data.status not in valid_statuses:
                return False
            
            # Check timing consistency
            if (node_data.started_at and node_data.finished_at and 
                node_data.duration_seconds is not None):
                # Basic sanity check - duration should be reasonable
                if node_data.duration_seconds < 0 or node_data.duration_seconds > 86400:  # 24 hours
                    return False
            
            return True
            
        except Exception:
            return False