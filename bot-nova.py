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
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi import RTVIConfig, RTVIObserver, RTVIProcessor
from pipecat.services.aws_nova_sonic import AWSNovaSonicLLMService
from pipecat.transports.services.daily import DailyParams, DailyTransport

from tool_processor import ToolProcessor

load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

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
    bearer_token = None
    if args.custom:
        try:
            custom_data = json.loads(args.custom)
            logger.info(f"🔍 Received custom_data: {custom_data}")
            system_prompt = custom_data.get("system_prompt")
            tools = custom_data.get("tools")
            logger.info(f"🔍 Extracted tools: {tools}")
            bearer_token = custom_data.get("bearer_token")
            if bearer_token:
                logger.info(f"🔑 Pipecat: Using proxied bearer token from Central (length: {len(bearer_token)})")
            else:
                logger.warning("⚠️  Pipecat: No bearer token provided from Central - tool calls will fail")
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

        if not system_prompt:
            raise ValueError(
                "system_prompt is required for bot initialization. "
                "Please provide a system prompt that defines the bot's behavior."
            )

        system_instruction = system_prompt.rstrip()
        logger.info(f"🔍 Pipecat using provided system_prompt")
        
        llm = AWSNovaSonicLLMService(
            secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            region="us-east-1",
            voice_id="tiffany",  # matthew, tiffany, amy
            tools=tools
        )

        # Create tool processor BEFORE callbacks (so callbacks can reference it)
        tool_processor = ToolProcessor(auth_token=bearer_token)

        # Register dynamic function callback with LLM service
        async def generic_tool_callback(function_name, tool_call_id, arguments, llm, context, result_callback):
            """Generic callback for all tool calls from LLM."""
            logger.info(f"🔧 LLM callback: {function_name} with args: {arguments}")
            
            # Use ToolProcessor to execute the actual API call with the exact tool name from LLM
            result = await tool_processor._call_central_tool(function_name, arguments)
            await result_callback(result)

        # Register the generic callback for all available tools
        if tools:
            logger.info(f"🔧 Processing {len(tools)} tools for registration")
            for i, tool in enumerate(tools):
                logger.info(f"🔧 Tool {i}: {tool}")
                
                # Extract tool name from tool definition or use string directly
                if isinstance(tool, str):
                    tool_name = tool
                elif isinstance(tool, dict) and 'toolSpec' in tool:
                    tool_name = tool['toolSpec']['name']
                    logger.info(f"🔧 Extracted tool name '{tool_name}' from tool definition")
                else:
                    raise ValueError(f"Tool must be a string or tool definition dict with 'toolSpec', got {type(tool)}: {tool}")

                llm.register_function(tool_name, generic_tool_callback)
                logger.info(f"🔧 ✅ Registered tool callback: {tool_name}")
            logger.info("🔧 All tool callbacks registered with LLM service")
        else:
            raise ValueError(
                "No tools provided for bot initialization. "
                "Tools are required for the bot to function properly. "
                "Please provide a list of tools in the bot configuration."
            )

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
                tool_processor,
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

        # Run the pipeline task
        await task.run()


if __name__ == "__main__":
    asyncio.run(main())
