"""Pytest configuration and shared fixtures for ToolProcessor tests."""

import asyncio
import pytest
import aiohttp
from unittest.mock import AsyncMock, Mock, patch
from pipecat.frames.frames import (
    Frame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    TextFrame,
)
from tool_processor import ToolProcessor


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_session():
    """Mock aiohttp ClientSession for testing HTTP interactions."""
    session = AsyncMock(spec=aiohttp.ClientSession)
    return session


@pytest.fixture
def mock_response():
    """Mock aiohttp response for testing API responses."""
    response = AsyncMock()
    response.status = 200
    response.json.return_value = {"success": True, "result": "test_result"}
    response.text.return_value = "Success"
    return response


@pytest.fixture
def sample_tool_arguments():
    """Sample tool arguments for testing."""
    return {"param1": "value1", "param2": {"nested": "value2"}, "param3": [1, 2, 3]}


@pytest.fixture
def function_call_frame(sample_tool_arguments):
    """Sample FunctionCallInProgressFrame for testing."""
    return FunctionCallInProgressFrame(
        tool_call_id="call_123",
        function_name="test_tool",
        arguments=sample_tool_arguments,
    )


@pytest.fixture
def tool_processor():
    """Basic ToolProcessor instance for testing."""
    return ToolProcessor()


@pytest.fixture
def configured_tool_processor():
    """Fully configured ToolProcessor instance for testing."""
    return ToolProcessor(
        central_base_url="https://test-central-api.com", auth_token="test_bearer_token"
    )
