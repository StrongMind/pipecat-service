"""Tool processing module for handling Central API tool calls.

This module provides the ToolProcessor class that handles tool execution
by communicating with Central's API endpoints.
"""

import os
import aiohttp
from loguru import logger

from pipecat.frames.frames import (
    Frame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class ToolProcessor(FrameProcessor):
    """Handles tool calls by communicating with Central API.
    
    This processor intercepts tool call frames from the LLM, executes them
    by calling Central's tool execution endpoints, and returns the results
    back to the conversation flow.
    """

    def __init__(self, central_base_url: str = None, auth_token: str = None, learning_context: dict = None):
        super().__init__()
        self._central_base_url = central_base_url or os.getenv('CENTRAL_API_URL', 'http://localhost:3001')
        self._auth_token = auth_token or os.getenv('CENTRAL_AUTH_TOKEN')
        self._session = None
        self._learning_context = learning_context or {}

    async def _get_session(self):
        """Get or create HTTP session."""
        if not self._session:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _call_central_tool(self, tool_name: str, tool_arguments: dict) -> dict:
        """Call Central unified API to execute a tool.
        
        Uses the RESTful endpoint POST /api/nova_sonic/tools/:tool_name
        
        Args:
            tool_name: Name of the tool to execute (learning_component, show_whiteboard, show_video)
            tool_arguments: Arguments for the tool
            
        Returns:
            Tool execution result from Central
        """
        session = await self._get_session()
        
        # Use unified RESTful endpoint for all tools
        endpoint = f"/api/nova_sonic/tools/{tool_name}"
        url = f"{self._central_base_url}{endpoint}"
        headers = {}
        if self._auth_token:
            headers['Authorization'] = f"Bearer {self._auth_token}"
        headers['Content-Type'] = 'application/json'
        
        if tool_name == 'learning_component':
            if 'course_id' in self._learning_context:
                tool_arguments['course_id'] = self._learning_context['course_id']
            if 'component_id' in self._learning_context:
                tool_arguments['component_id'] = self._learning_context['component_id']

        try:
            logger.info(f"Calling Central tool: {tool_name} with args: {tool_arguments}")
            async with session.post(url, json=tool_arguments, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Tool {tool_name} completed successfully")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(f"Tool {tool_name} failed with status {response.status}: {error_text}")
                    return {"error": f"Tool execution failed: {error_text}"}
                    
        except Exception as e:
            logger.error(f"Error calling Central tool {tool_name}: {e}")
            return {"error": f"Tool execution error: {str(e)}"}

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Process frames and handle tool calls.
        
        Args:
            frame: The incoming frame to process
            direction: The direction of frame flow in the pipeline
        """
        await super().process_frame(frame, direction)

        # Intercept tool call frames from the LLM
        if isinstance(frame, FunctionCallInProgressFrame):
            logger.info(f"Tool call intercepted: {frame.tool_call_id} - {frame.function_name}")
            
            # Execute the tool via Central API
            result = await self._call_central_tool(
                frame.function_name, 
                frame.arguments
            )
            
            # Create result frame to send back to LLM
            result_frame = FunctionCallResultFrame(
                function_name=frame.function_name,
                tool_call_id=frame.tool_call_id,
                arguments=frame.arguments,
                result=result
            )
            
            logger.info(f"Sending tool result back to LLM: {frame.tool_call_id}")
            await self.push_frame(result_frame, direction)
            return  # Don't pass the original frame through
            
        # Pass all other frames through normally
        await self.push_frame(frame, direction)

    async def cleanup(self):
        """Clean up HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None 