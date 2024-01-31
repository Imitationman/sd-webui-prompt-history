import importlib
from lib_history import hijacker, global_state
from modules import script_callbacks, processing, shared
import uuid

# Added for Development
from core.dependencies import Settings
from core.logger import get_logger

logger = get_logger(__name__)

process_images_inner_hijacker = hijacker.ModuleHijacker.install_or_get(
    module=processing,
    hijacker_attribute="__process_images_inner_hijacker",
    on_uninstall=script_callbacks.on_script_unloaded,
)

importlib.reload(global_state)  # Reload the global_state module


@process_images_inner_hijacker.hijack("process_images")
def process_images(p: processing.StableDiffusionProcessing, original_function):
    # if prompt history is not enable then call original function

    if not global_state.is_enabled:
        return original_function(p)

    # mark old state of return_grid
    # we set it to True to make sure it return grid image in case of multi images
    old_state = shared.opts.return_grid
    shared.opts.return_grid = True
    res = original_function(p)
    shared.opts.return_grid = old_state

    # add result to history
    logger.info(f"global_State: {global_state}")
    global_state.add_config(
        uuid.uuid4().hex,
        res.prompt,
        shared.opts.sd_model_checkpoint,
        res.infotexts[0],
        res.images[0],
    )
    return res
