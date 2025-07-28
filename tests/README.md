# ToolProcessor Test Suite

This directory contains comprehensive, behavior-driven specifications for the `ToolProcessor` class using pytest and a Given-When-Then approach.

## Test Structure

The test suite is organized into behavioral specifications that clearly describe what the `ToolProcessor` should do in various scenarios:

### Test Classes

- **`TestToolProcessorInitialization`**: Specifications for how the ToolProcessor initializes with different parameters
- **`TestSessionManagement`**: Specifications for HTTP session lifecycle management  
- **`TestCentralToolCalling`**: Specifications for calling Central API tools with various scenarios
- **`TestFrameProcessing`**: Specifications for processing Pipecat frames and tool calls
- **`TestIntegrationScenarios`**: Specifications for complex integration scenarios and edge cases

## Running Tests

### Prerequisites

Install test dependencies:

```bash
pip install -r requirements-dev.txt
```

### Basic Test Execution

Run all tests:
```bash
pytest
```

Run with verbose output:
```bash
pytest -v
```

Run specific test class:
```bash
pytest tests/test_tool_processor.py::TestToolProcessorInitialization -v
```

Run specific test:
```bash
pytest tests/test_tool_processor.py::TestToolProcessorInitialization::test_given_no_parameters_when_initializing_then_uses_defaults -v
```

### Test Coverage

Run tests with coverage report:
```bash
pytest --cov=tool_processor --cov-report=html
```

View coverage in browser:
```bash
open htmlcov/index.html
```

### Test Filtering

Run only unit tests:
```bash
pytest -m unit
```

Run only integration tests:
```bash
pytest -m integration
```

Skip slow tests:
```bash
pytest -m "not slow"
```

### Parallel Execution

Run tests in parallel (faster execution):
```bash
pytest -n auto
```

## Test Style and Philosophy

### Behavior-Driven Development (BDD)

These tests follow BDD principles with clear Given-When-Then structure:

```python
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
```

### Test Naming Convention

Test names follow the pattern: `test_given_[condition]_when_[action]_then_[expected_result]`

This makes it clear:
- **Given**: The initial state or preconditions
- **When**: The action being performed
- **Then**: The expected outcome

### Fixtures and Mocking

The test suite uses comprehensive fixtures for:
- Mock HTTP sessions and responses
- Sample data generation
- ToolProcessor instances with different configurations
- Pipecat frame objects

## Test Coverage Areas

### Core Functionality
- ✅ Initialization with various parameters
- ✅ HTTP session management and lifecycle
- ✅ Central API tool calling (success and error cases)
- ✅ Frame processing and tool execution
- ✅ Authentication token handling
- ✅ Learning context integration

### Error Handling
- ✅ Network errors and timeouts
- ✅ API error responses (4xx, 5xx)
- ✅ Missing authentication tokens
- ✅ Invalid tool arguments
- ✅ Session cleanup errors

### Edge Cases
- ✅ Special characters in tool arguments
- ✅ Multiple sequential tool calls
- ✅ Session reuse after cleanup
- ✅ Bearer token prefix handling
- ✅ Learning component context injection

## Continuous Integration

The test suite is designed to run in CI/CD environments with:
- Coverage reporting (XML format for CI)
- JUnit XML output for test result parsing
- Strict configuration to catch issues early
- Parallel execution support for faster builds

## Adding New Tests

When adding new tests:

1. **Follow the BDD pattern** with clear Given-When-Then structure
2. **Use descriptive test names** that explain the scenario
3. **Add appropriate fixtures** for test data and mocks
4. **Include both success and failure scenarios**
5. **Test edge cases and error conditions**
6. **Maintain high test coverage** (target: 90%+)

### Example Template

```python
@pytest.mark.asyncio
async def test_given_[condition]_when_[action]_then_[expected_result](self, fixture1, fixture2):
    """
    Given: Clear description of initial state
    When: Clear description of action
    Then: Clear description of expected outcome
    """
    # Given
    # Setup test conditions
    
    # When  
    # Perform the action
    
    # Then
    # Assert expected outcomes
    assert expected_condition
```

## Test Data Management

The test suite uses factories and fixtures to generate test data:
- **Fixtures**: For reusable test objects and mocks
- **Factory Boy**: For generating complex test data (when needed)
- **Faker**: For realistic fake data (when needed)

This ensures tests are maintainable and don't rely on hardcoded values that might become outdated. 