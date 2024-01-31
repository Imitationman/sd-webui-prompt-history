import asyncio
import contextvars
import functools
import json
import logging
import traceback
from datetime import datetime
from enum import Enum, auto

import aiofiles
import aiofiles.os
from rich.console import Console
from rich.logging import RichHandler

from core.dependencies import settings

# Initialize the console
console = Console(color_system="256", width=200, style="purple")

# Context variables
current_flow_trace_var = contextvars.ContextVar("current_flow_trace", default=None)
current_flow_depth_var = contextvars.ContextVar("current_flow_depth", default=0)


class FlowTraceHandler(RichHandler):
    def emit(self, record):
        current_flow_trace = current_flow_trace_var.get()
        if current_flow_trace is not None:
            current_flow_trace[-1].setdefault("log_messages", []).append(
                {
                    "message": record.getMessage(),
                    "level": record.levelname,
                    "timestamp": datetime.now().strftime("%Y_%m_%d-%H_%M_%S_%p_%f")[
                        :-3
                    ],
                }
            )
        super().emit(record)


def get_logger(module_name):
    """Get logger for module."""
    logger = logging.getLogger(module_name)
    handler = FlowTraceHandler(
        rich_tracebacks=True, console=console, tracebacks_show_locals=True
    )
    handler.setFormatter(
        logging.Formatter("[ %(threadName)s:%(funcName)s:%(lineno)d ] - %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    return logger


def truncate_complex(value, max_length=500, current_length=0):
    """Truncate complex data structures to a maximum length."""
    if isinstance(value, (list, tuple)):
        truncated = []
        for item in value:
            truncated_item, current_length = truncate_complex(
                item, max_length, current_length
            )
            if current_length < max_length:
                truncated.append(truncated_item)
            else:
                break
        return (truncated, current_length)

    if isinstance(value, dict):
        truncated = {}
        for k, v in value.items():
            truncated_key, current_length = truncate_complex(
                k, max_length, current_length
            )
            truncated_value, current_length = truncate_complex(
                v, max_length, current_length
            )

            if current_length < max_length:
                truncated[truncated_key] = truncated_value
            else:
                break
        return (truncated, current_length)

    value_str = str(value)
    current_length += len(value_str)
    if current_length > max_length:
        value_str = f"{value_str[:max_length - current_length]}...(truncated)"
    return (value_str, current_length)


def truncate_value(value, max_length=1200):
    """Truncate a value to a maximum length."""
    if isinstance(value):
        return None
    truncated, _ = truncate_complex(value, max_length)
    return truncated


def log_output():
    """Log output decorator."""

    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await async_logged_execution(func, *args, **kwargs)

        return async_wrapper

    return decorator


async def async_logged_execution(func, *args, **kwargs):
    """Log the execution of a function and its output for ASYNC Functions."""
    current_flow_trace = current_flow_trace_var.get()
    current_flow_depth = current_flow_depth_var.get()

    start_time = asyncio.get_running_loop().time()

    if current_flow_trace is None:
        current_flow_trace = []
        current_flow_trace_var.set(current_flow_trace)

    current_flow_depth += 1
    current_flow_depth_var.set(current_flow_depth)

    function_trace = {
        "function": func.__name__,
        "args": tuple(truncate_value(arg) for arg in args),
        "kwargs": {k: truncate_value(v) for k, v in kwargs.items()},
        "timestamp": datetime.now().strftime("%Y_%m_%d-%H_%M_%S_%p_%f")[:-3],
    }

    current_flow_trace.append(function_trace)
    result = None
    try:
        result = await func(*args, **kwargs)
        function_trace["return_value"] = truncate_value(result)
        function_trace["outcome"] = "SUCCESSFUL"
    except Exception as e:
        function_trace["exception"] = {
            "type": str(type(e)),
            "message": str(e),
            "traceback": traceback.format_exc(),
        }
        function_trace["outcome"] = "ERROR"
    finally:
        await handle_post_execution(start_time, function_trace)

    return result


async def handle_post_execution(start_time, function_trace):
    """Handle post execution of a function."""
    end_time = asyncio.get_running_loop().time()
    elapsed_time = end_time - start_time
    function_trace["elapsed_time"] = f"{elapsed_time:.4f} seconds"

    current_flow_depth = current_flow_depth_var.get()
    current_flow_depth -= 1
    current_flow_depth_var.set(current_flow_depth)

    if current_flow_depth == 0:
        current_flow_trace = current_flow_trace_var.get()
        total_flow_duration = end_time - start_time
        flow_trace = {
            "flow_duration": f"{total_flow_duration:.4f} seconds",
            "flow_trace": current_flow_trace,
        }

        # Determine if any part of the flow resulted in an error
        has_error = any(item.get("outcome") == "ERROR" for item in current_flow_trace)
        outcome_status = (
            "ERROR" if has_error else function_trace.get("outcome", "UNKNOWN")
        )
        function_name = function_trace.get("function", "UNKNOWN")

        timestamp = datetime.now().strftime("%Y_%m_%d-%H_%M_%S_%p_%f")[:-3]
        flow_filename = f"logs/{function_name}__{timestamp}_{outcome_status}.json"

        # Check if 'logs' directory exists; if not, create it.
        if not await aiofiles.os.path.exists("logs"):
            await aiofiles.os.mkdir("logs")

        async with aiofiles.open(flow_filename, "w") as json_file:
            await json_file.write(json.dumps(flow_trace, indent=4))

        current_flow_trace_var.set(None)
        current_flow_depth_var.set(0)
