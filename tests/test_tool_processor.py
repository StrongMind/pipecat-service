"""Behavior-driven specifications for ToolProcessor.

This module contains comprehensive tests that specify the behavior of the ToolProcessor
class using a Given-When-Then approach with pytest.
"""

import os
import pytest
import aiohttp
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from pipecat.frames.frames import (
    Frame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    TextFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from tool_processor import ToolProcessor


class TestToolProcessorInitialization:
    """Specifications for ToolProcessor initialization behavior."""

    def test_given_no_parameters_when_initializing_then_uses_defaults(self):
        """
        Given: No initialization parameters are provided
        When: A ToolProcessor is created
        Then: It should use default values for all configuration
        """
        # Given & When
        processor = ToolProcessor()
        
        # Then
        assert processor._central_base_url == "http://localhost:3001"
        assert processor._auth_token is None
        assert processor._session is None
        assert processor._learning_context == {}

    def test_given_custom_parameters_when_initializing_then_uses_provided_values(self):
        """
        Given: Custom parameters are provided
        When: A ToolProcessor is created
        Then: It should use the provided values
        """
        # Given
        base_url = "https://custom-api.com"
        auth_token = "custom_token"
        learning_context = {"course_id": "123"}
        
        # When
        processor = ToolProcessor(
            central_base_url=base_url,
            auth_token=auth_token,
            learning_context=learning_context
        )
        
        # Then
        assert processor._central_base_url == base_url
        assert processor._auth_token == auth_token
        assert processor._learning_context == learning_context

    @patch.dict(os.environ, {'CENTRAL_API_URL': 'https://env-api.com'})
    def test_given_environment_variable_when_no_base_url_provided_then_uses_env_value(self):
        """
        Given: CENTRAL_API_URL environment variable is set
        When: A ToolProcessor is created without base_url
        Then: It should use the environment variable value
        """
        # Given & When
        processor = ToolProcessor()
        
        # Then
        assert processor._central_base_url == "https://env-api.com"


class TestSessionManagement:
    """Specifications for HTTP session management behavior."""

    @pytest.mark.asyncio
    async def test_given_no_existing_session_when_getting_session_then_creates_new_session(self, tool_processor):
        """
        Given: No existing HTTP session
        When: _get_session is called
        Then: A new aiohttp ClientSession should be created
        """
        # Given
        assert tool_processor._session is None
        
        # When
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value = mock_session
            
            session = await tool_processor._get_session()
        
        # Then
        assert session == mock_session
        assert tool_processor._session == mock_session
        mock_session_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_given_existing_session_when_getting_session_then_returns_existing_session(self, tool_processor):
        """
        Given: An existing HTTP session
        When: _get_session is called
        Then: The existing session should be returned
        """
        # Given
        existing_session = AsyncMock()
        tool_processor._session = existing_session
        
        # When
        session = await tool_processor._get_session()
        
        # Then
        assert session == existing_session

    @pytest.mark.asyncio
    async def test_given_active_session_when_cleanup_called_then_closes_session(self, tool_processor):
        """
        Given: An active HTTP session
        When: cleanup is called
        Then: The session should be closed and set to None
        """
        # Given
        mock_session = AsyncMock()
        tool_processor._session = mock_session
        
        # When
        await tool_processor.cleanup()
        
        # Then
        mock_session.close.assert_called_once()
        assert tool_processor._session is None

    @pytest.mark.asyncio
    async def test_given_no_session_when_cleanup_called_then_does_nothing(self, tool_processor):
        """
        Given: No active session
        When: cleanup is called
        Then: No errors should occur
        """
        # Given
        assert tool_processor._session is None
        
        # When & Then (should not raise)
        await tool_processor.cleanup()


class TestCentralToolCalling:
    """Specifications for Central API tool calling behavior."""

    @pytest.mark.asyncio
    async def test_given_successful_tool_call_when_calling_central_tool_then_returns_result(
        self, configured_tool_processor, mock_session, mock_response, sample_tool_arguments
    ):
        """
        Given: A successful Central API response
        When: _call_central_tool is called
        Then: The tool result should be returned
        """
        # Given
        tool_name = "test_tool"
        mock_session.post.return_value.__aenter__.return_value = mock_response
        configured_tool_processor._session = mock_session
        
        # When
        result = await configured_tool_processor._call_central_tool(tool_name, sample_tool_arguments)
        
        # Then
        assert result == {"success": True, "result": "test_result"}
        mock_session.post.assert_called_once_with(
            "https://test-central-api.com/api/nova_sonic/tools/test_tool",
            json=sample_tool_arguments,
            headers={
                'Content-Type': 'application/json',
                'Authorization': 'Bearer test_bearer_token'
            }
        )

    @pytest.mark.asyncio
    async def test_given_bearer_token_prefix_when_calling_central_tool_then_uses_token_as_is(
        self, tool_processor, mock_session, mock_response, sample_tool_arguments
    ):
        """
        Given: An auth token with Bearer prefix
        When: _call_central_tool is called
        Then: The token should be used as-is in Authorization header
        """
        # Given
        tool_processor._auth_token = "Bearer already_prefixed_token"
        tool_processor._session = mock_session
        mock_session.post.return_value.__aenter__.return_value = mock_response
        
        # When
        await tool_processor._call_central_tool("test_tool", sample_tool_arguments)
        
        # Then
        call_args = mock_session.post.call_args
        assert call_args[1]['headers']['Authorization'] == "Bearer already_prefixed_token"

    @pytest.mark.asyncio
    async def test_given_learning_component_tool_when_calling_central_tool_then_adds_learning_context(
        self, configured_tool_processor, mock_session, mock_response
    ):
        """
        Given: A learning_component tool call with learning context
        When: _call_central_tool is called
        Then: Learning context should be added to arguments
        """
        # Given
        tool_name = "learning_component"
        tool_arguments = {"existing_param": "value"}
        configured_tool_processor._session = mock_session
        mock_session.post.return_value.__aenter__.return_value = mock_response
        
        # When
        await configured_tool_processor._call_central_tool(tool_name, tool_arguments)
        
        # Then
        expected_args = {
            "existing_param": "value",
            "course_id": "course_123",
            "component_id": "comp_456"
        }
        call_args = mock_session.post.call_args
        assert call_args[1]['json'] == expected_args

    @pytest.mark.asyncio
    async def test_given_api_error_response_when_calling_central_tool_then_returns_error_result(
        self, tool_processor, mock_session, sample_tool_arguments
    ):
        """
        Given: An API error response (non-200 status)
        When: _call_central_tool is called
        Then: An error result should be returned
        """
        # Given
        mock_response = AsyncMock()
        mock_response.status = 400
        mock_response.text.return_value = "Bad Request"
        mock_session.post.return_value.__aenter__.return_value = mock_response
        tool_processor._session = mock_session
        
        # When
        result = await tool_processor._call_central_tool("test_tool", sample_tool_arguments)
        
        # Then
        assert result == {"error": "Tool execution failed: Bad Request"}

    @pytest.mark.asyncio
    async def test_given_network_exception_when_calling_central_tool_then_returns_error_result(
        self, tool_processor, mock_session, sample_tool_arguments
    ):
        """
        Given: A network exception occurs
        When: _call_central_tool is called
        Then: An error result should be returned
        """
        # Given
        mock_session.post.side_effect = aiohttp.ClientError("Network error")
        tool_processor._session = mock_session
        
        # When
        result = await tool_processor._call_central_tool("test_tool", sample_tool_arguments)
        
        # Then
        assert result == {"error": "Tool execution error: Network error"}

    @pytest.mark.asyncio
    async def test_given_no_auth_token_when_calling_central_tool_then_logs_error_and_continues(
        self, tool_processor, mock_session, mock_response, sample_tool_arguments
    ):
        """
        Given: No authentication token is provided
        When: _call_central_tool is called
        Then: An error should be logged but the call should continue
        """
        # Given
        tool_processor._auth_token = None
        tool_processor._session = mock_session
        mock_session.post.return_value.__aenter__.return_value = mock_response
        
        # When
        with patch('tool_processor.logger') as mock_logger:
            await tool_processor._call_central_tool("test_tool", sample_tool_arguments)
        
        # Then
        mock_logger.error.assert_called_with(
            "No bearer token provided from Central - tool calls will fail"
        )
        call_args = mock_session.post.call_args
        assert 'Authorization' not in call_args[1]['headers']


class TestFrameProcessing:
    """Specifications for frame processing behavior."""

    @pytest.mark.asyncio
    async def test_given_function_call_frame_when_processing_then_executes_tool_and_returns_result(
        self, configured_tool_processor, function_call_frame, mock_session, mock_response
    ):
        """
        Given: A FunctionCallInProgressFrame is received
        When: process_frame is called
        Then: The tool should be executed and a result frame should be pushed
        """
        # Given
        configured_tool_processor._session = mock_session
        mock_session.post.return_value.__aenter__.return_value = mock_response
        
        # Setup mock for push_frame to capture calls
        configured_tool_processor.push_frame = AsyncMock()
        
        # When
        await configured_tool_processor.process_frame(function_call_frame, FrameDirection.DOWNSTREAM)
        
        # Then
        # Verify tool was called
        mock_session.post.assert_called_once()
        
        # Verify result frame was pushed
        configured_tool_processor.push_frame.assert_called_once()
        pushed_frame = configured_tool_processor.push_frame.call_args[0][0]
        
        assert isinstance(pushed_frame, FunctionCallResultFrame)
        assert pushed_frame.function_name == "test_tool"
        assert pushed_frame.tool_call_id == "call_123"
        assert pushed_frame.result == {"success": True, "result": "test_result"}

    @pytest.mark.asyncio
    async def test_given_non_function_call_frame_when_processing_then_passes_through(
        self, tool_processor
    ):
        """
        Given: A non-FunctionCallInProgressFrame is received
        When: process_frame is called
        Then: The frame should be passed through unchanged
        """
        # Given
        text_frame = TextFrame("Hello, world!")
        tool_processor.push_frame = AsyncMock()
        
        # When
        await tool_processor.process_frame(text_frame, FrameDirection.DOWNSTREAM)
        
        # Then
        tool_processor.push_frame.assert_called_once_with(text_frame, FrameDirection.DOWNSTREAM)

    @pytest.mark.asyncio
    async def test_given_function_call_frame_when_tool_execution_fails_then_returns_error_result(
        self, tool_processor, function_call_frame, mock_session
    ):
        """
        Given: A FunctionCallInProgressFrame with a failing tool
        When: process_frame is called
        Then: An error result frame should be returned
        """
        # Given
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.text.return_value = "Internal Server Error"
        mock_session.post.return_value.__aenter__.return_value = mock_response
        tool_processor._session = mock_session
        tool_processor.push_frame = AsyncMock()
        
        # When
        await tool_processor.process_frame(function_call_frame, FrameDirection.DOWNSTREAM)
        
        # Then
        pushed_frame = tool_processor.push_frame.call_args[0][0]
        assert isinstance(pushed_frame, FunctionCallResultFrame)
        assert "error" in pushed_frame.result
        assert "Tool execution failed" in pushed_frame.result["error"]


class TestIntegrationScenarios:
    """Specifications for integration scenarios and edge cases."""

    @pytest.mark.asyncio
    async def test_given_multiple_tool_calls_when_processing_sequentially_then_handles_each_correctly(
        self, configured_tool_processor, sample_tool_arguments, mock_session, mock_response
    ):
        """
        Given: Multiple tool calls are processed sequentially
        When: process_frame is called for each
        Then: Each tool should be executed correctly
        """
        # Given
        configured_tool_processor._session = mock_session
        mock_session.post.return_value.__aenter__.return_value = mock_response
        configured_tool_processor.push_frame = AsyncMock()
        
        frames = [
            FunctionCallInProgressFrame(tool_call_id="call_1", function_name="tool_1", arguments=sample_tool_arguments),
            FunctionCallInProgressFrame(tool_call_id="call_2", function_name="tool_2", arguments=sample_tool_arguments),
            FunctionCallInProgressFrame(tool_call_id="call_3", function_name="tool_3", arguments=sample_tool_arguments),
        ]
        
        # When
        for frame in frames:
            await configured_tool_processor.process_frame(frame, FrameDirection.DOWNSTREAM)
        
        # Then
        assert mock_session.post.call_count == 3
        assert configured_tool_processor.push_frame.call_count == 3
        
        # Verify each tool was called with correct name
        post_calls = mock_session.post.call_args_list
        expected_urls = [
            "https://test-central-api.com/api/nova_sonic/tools/tool_1",
            "https://test-central-api.com/api/nova_sonic/tools/tool_2", 
            "https://test-central-api.com/api/nova_sonic/tools/tool_3"
        ]
        
        for i, call in enumerate(post_calls):
            assert call[0][0] == expected_urls[i]

    @pytest.mark.asyncio
    async def test_given_processor_with_session_when_cleanup_called_then_can_be_reused(
        self, tool_processor, mock_session
    ):
        """
        Given: A processor with an active session
        When: cleanup is called and processor is reused
        Then: A new session should be created for subsequent calls
        """
        # Given
        tool_processor._session = mock_session
        
        # When
        await tool_processor.cleanup()
        
        # Then
        assert tool_processor._session is None
        
        # When reusing processor
        with patch('aiohttp.ClientSession') as mock_session_class:
            new_session = AsyncMock()
            mock_session_class.return_value = new_session
            
            session = await tool_processor._get_session()
            
            assert session == new_session
            assert tool_processor._session == new_session

    @pytest.mark.asyncio
    async def test_given_special_characters_in_tool_arguments_when_calling_central_tool_then_handles_correctly(
        self, tool_processor, mock_session, mock_response
    ):
        """
        Given: Tool arguments containing special characters
        When: _call_central_tool is called
        Then: Arguments should be properly JSON-encoded and sent
        """
        # Given
        special_args = {
            "text": "Hello \"world\" with 'quotes' and ñoñó special chars",
            "unicode": "🚀 emoji and unicode",
            "json": {"nested": {"deep": "value with \n newlines"}}
        }
        tool_processor._session = mock_session
        mock_session.post.return_value.__aenter__.return_value = mock_response
        
        # When
        await tool_processor._call_central_tool("special_tool", special_args)
        
        # Then
        call_args = mock_session.post.call_args
        assert call_args[1]['json'] == special_args 