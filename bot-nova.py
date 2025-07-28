#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Gemini Bot Implementation.

This module implements a chatbot using Google's Gemini Multimodal Live model.
It includes:
- Real-time audio/video interaction through Daily
- Animated robot avatar
- Speech-to-speech model

The bot runs as part of a pipeline that processes audio/video frames and manages
the conversation flow using Gemini's streaming capabilities.
"""

import asyncio
import os
import sys
import argparse
import json

import aiohttp
from dotenv import load_dotenv
from loguru import logger
from PIL import Image
from runner import configure

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    OutputImageRawFrame,
    SpriteFrame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi import RTVIConfig, RTVIObserver, RTVIProcessor
from pipecat.services.aws_nova_sonic import AWSNovaSonicLLMService
from pipecat.transports.services.daily import DailyParams, DailyTransport

load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")


# ToolProcessor class removed - using direct function callbacks with AWS Nova Sonic instead

sprites = []
script_dir = os.path.dirname(__file__)

for i in range(1, 26):
    # Build the full path to the image file
    full_path = os.path.join(script_dir, f"assets/robot0{i}.png")
    # Get the filename without the extension to use as the dictionary key
    # Open the image and convert it to bytes
    with Image.open(full_path) as img:
        sprites.append(OutputImageRawFrame(image=img.tobytes(), size=img.size, format=img.format))

# Create a smooth animation by adding reversed frames
flipped = sprites[::-1]
sprites.extend(flipped)

# Define static and animated states
quiet_frame = sprites[0]  # Static frame for when bot is listening
talking_frame = SpriteFrame(images=sprites)  # Animation sequence for when bot is talking


class TalkingAnimation(FrameProcessor):
    """Manages the bot's visual animation states.

    Switches between static (listening) and animated (talking) states based on
    the bot's current speaking status.
    """

    def __init__(self):
        super().__init__()
        self._is_talking = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Process incoming frames and update animation state.

        Args:
            frame: The incoming frame to process
            direction: The direction of frame flow in the pipeline
        """
        await super().process_frame(frame, direction)

        # Switch to talking animation when bot starts speaking
        if isinstance(frame, BotStartedSpeakingFrame):
            if not self._is_talking:
                await self.push_frame(talking_frame)
                self._is_talking = True
        # Return to static frame when bot stops speaking
        elif isinstance(frame, BotStoppedSpeakingFrame):
            await self.push_frame(quiet_frame)
            self._is_talking = False

        await self.push_frame(frame, direction)


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
        """Call Central API to execute a tool.
        
        Args:
            tool_name: Name of the tool to execute
            tool_arguments: Arguments for the tool
            
        Returns:
            Tool execution result from Central
        """
        session = await self._get_session()
        
        # Map tool names to Central endpoints
        endpoint_map = {
            'learning_component': '/api/nova_sonic/tools/learning_component',
            'show_whiteboard': '/api/nova_sonic/tools/show_whiteboard', 
            'show_video': '/api/nova_sonic/tools/show_video'
        }
        
        endpoint = endpoint_map.get(tool_name)
        if not endpoint:
            logger.error(f"Unknown tool: {tool_name}")
            return {"error": f"Unknown tool: {tool_name}"}
            
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
                tool_call_id=frame.tool_call_id,
                function_name=frame.function_name,
                result=json.dumps(result)
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


async def main():
    """Main bot execution function.

    Sets up and runs the bot pipeline including:
    - Daily video transport with specific audio parameters for Gemini
    - Gemini Live multimodal model integration
    - Voice activity detection
    - Tool processing for Central API integration
    - Animation processing
    - RTVI event handling
    """
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Nova Sonic Bot")
    parser.add_argument("-c", "--custom", type=str, help="Custom payload JSON string")
    args, unknown = parser.parse_known_args()

    # Parse custom payload if provided
    system_prompt = None
    tools = None
    learning_context = {}
    if args.custom:
        try:
            custom_data = json.loads(args.custom)
            logger.info(f"🔍 Pipecat received custom_data: {custom_data}")
            system_prompt = custom_data.get("system_prompt")
            logger.info(f"🔍 Pipecat extracted system_prompt: {system_prompt}")
            tools = custom_data.get("tools")
            learning_context = custom_data.get("learning_context", {})
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse custom payload: {e}")
    else:
        logger.warning("🔍 Pipecat: No custom data received")

    async with aiohttp.ClientSession() as session:
        (room_url, token) = await configure(session)

        # Set up Daily transport with specific audio/video parameters for Gemini
        transport = DailyTransport(
            room_url,
            token,
            "Chatbot",
            DailyParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                video_out_enabled=True,
                video_out_width=1024,
                video_out_height=576,
                vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.5)),
            ),
        )

        # Always append the response instruction string
        response_instruction = AWSNovaSonicLLMService.AWAIT_TRIGGER_ASSISTANT_RESPONSE_INSTRUCTION
        logger.info(f"🔍 Pipecat system_prompt check: {system_prompt}")
        if system_prompt:
            # Remove trailing whitespace and append the instruction
            system_instruction = system_prompt.rstrip() + "\n\n" + response_instruction
            logger.info(f"🔍 Pipecat using provided system_prompt")
        else:
            system_instruction = "You are a elementary school teacher named Lexi.\n\n" + response_instruction
            logger.info(f"🔍 Pipecat using fallback Lexi prompt")
        
        logger.info(f"🔍 Pipecat final system_instruction: {system_instruction[:100]}...")

        llm = AWSNovaSonicLLMService(
            secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            region="us-east-1",
            voice_id="tiffany",  # matthew, tiffany, amy
            tools=tools
        )

        # Register function callbacks with LLM service (inherited from LLMService)
        async def learning_component_callback(function_name, tool_call_id, arguments, llm, context, result_callback):
            """Callback for learning_component tool calls from LLM."""
            logger.info(f"🔧 LLM callback: {function_name} with args: {arguments}")
            # Inject learning context if available
            if learning_context and 'course_id' in learning_context:
                arguments['course_id'] = learning_context['course_id']
            if learning_context and 'component_id' in learning_context:
                arguments['component_id'] = learning_context['component_id']
            
            # Use ToolProcessor to execute the actual API call
            result = await tool_processor._call_central_tool('learning_component', arguments)
            logger.info(f"🔧 LLM callback result: {result}")
            await result_callback(result)

        async def show_whiteboard_callback(function_name, tool_call_id, arguments, llm, context, result_callback):
            """Callback for show_whiteboard tool calls from LLM."""
            logger.info(f"🔧 LLM callback: {function_name} with args: {arguments}")
            result = await tool_processor._call_central_tool('show_whiteboard', arguments)
            await result_callback(result)

        async def show_video_callback(function_name, tool_call_id, arguments, llm, context, result_callback):
            """Callback for show_video tool calls from LLM."""
            logger.info(f"🔧 LLM callback: {function_name} with args: {arguments}")
            result = await tool_processor._call_central_tool('show_video', arguments)
            await result_callback(result)

        # Register the callbacks with the LLM service using correct method
        if tools:
            llm.register_function("learning_component", learning_component_callback)
            llm.register_function("show_whiteboard", show_whiteboard_callback)
            llm.register_function("show_video", show_video_callback)
            logger.info("🔧 Tool callbacks registered with LLM service")

        # AWS Nova Sonic uses both registered callbacks AND frame-based tool processing via ToolProcessor

        messages = [
            {
                "role": "system",
                "content": system_instruction,
            },
        ]

        # Set up conversation context and management
        # The context_aggregator will automatically collect conversation context
        context = OpenAILLMContext(messages)
        context_aggregator = llm.create_context_aggregator(context)

        # Set up processors
        ta = TalkingAnimation()
        tool_processor = ToolProcessor(learning_context=learning_context)  # Context injection for learning_component

        #
        # RTVI events for Pipecat client UI
        #
        rtvi = RTVIProcessor(config=RTVIConfig(config=[]))

        # Pipeline with tool processor for proper AWS Nova Sonic integration
        pipeline = Pipeline(
            [
                transport.input(),
                rtvi,
                context_aggregator.user(),
                llm,
                tool_processor,  # RE-ENABLED: Required for AWS Nova Sonic tool response parsing
                ta,
                transport.output(),
                context_aggregator.assistant(),
            ]
        )

        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                allow_interruptions=True,
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
            observers=[RTVIObserver(rtvi)],
        )
        await task.queue_frame(quiet_frame)

        @rtvi.event_handler("on_client_ready")
        async def on_client_ready(rtvi):
            await rtvi.set_bot_ready()
            # Kick off the conversation
            await task.queue_frames([context_aggregator.user().get_context_frame()])

        @transport.event_handler("on_first_participant_joined")
        async def on_first_participant_joined(transport, participant):
            print(f"Participant joined: {participant}")
            await transport.capture_participant_transcription(participant["id"])
            # Kick off the conversation.
            await task.queue_frames([context_aggregator.user().get_context_frame()])
            # HACK: for now, we need this special way of triggering the first assistant response in AWS
            # Nova Sonic. Note that this trigger requires a special corresponding bit of text in the
            # system instruction. In the future, simply queueing the context frame should be sufficient.
            await llm.trigger_assistant_response()

        @transport.event_handler("on_participant_left")
        async def on_participant_left(transport, participant, reason):
            print(f"Participant left: {participant}")
            await task.cancel()

        # Run the pipeline
        try:
            runner = PipelineRunner()
            await runner.run(task)
        finally:
            # No cleanup needed - using direct function callbacks
            pass


if __name__ == "__main__":
    asyncio.run(main())
