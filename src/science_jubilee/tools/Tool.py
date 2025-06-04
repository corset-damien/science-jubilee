from science_jubilee.utils.exceptions import (ToolConfigurationError, ToolStateError)
from science_jubilee.utils.logger_utils import setup_logging

logger = setup_logging(logger_name="Tool")

# ═══════════════════════════════════════════════════════════════════════════════
# CLASS Tool (BASE FOR ALL TOOLS)
# ═══════════════════════════════════════════════════════════════════════════════
class Tool:
    """
    Base class for all tools used with the Jubilee machine.
    Provides a common interface and initialization for all tool types (pipette, camera, etc).
    Extend this class to implement custom tool logic.
    """
    # ───────────────────────────────────────────────────────────────────────────
    # INITIALIZATION
    # ───────────────────────────────────────────────────────────────────────────
    def __init__(self, index: int, name: str, **kwargs):
        """
        Initialize a Tool instance.
        Args:
            index (int): Tool index (unique per tool on the machine).
            name (str): Tool name (e.g. 'pipette', 'camera').
            **kwargs: Additional configuration parameters for specialized tools.
        Raises:
            ToolConfigurationError: If arguments are invalid.
        """
        if not isinstance(index, int) or not isinstance(name, str):
            logger.error(f"Tool initialization failed: index={index}, name={name}")
            raise ToolConfigurationError("Incorrect usage: Tool(index: int, name: str, **kwargs)")
        self.index = index
        self.name = name
        self._machine = None  # Optionally set by the manager when loaded
        # Store any extra configuration for subclasses
        
        for k, v in kwargs.items():
            setattr(self, k, v)
            logger.debug(f"Set attribute {k}={v} for tool {self.name}")
        logger.info(f"Tool '{self.name}' (index {self.index}) initialized.")

    # ───────────────────────────────────────────────────────────────────────────
    # MACHINE ATTACHMENT HOOKS
    # ───────────────────────────────────────────────────────────────────────────
    def attach_to_machine(self, machine):
        """
        Called by the manager when the tool is loaded onto the machine.
        Args:
            machine: Reference to the parent machine/manager.
        """
        self._machine = machine
        logger.debug(f"Tool '{self.name}' attached to machine.")

    def detach_from_machine(self):
        """
        Called by the manager when the tool is unloaded from the machine.
        """
        self._machine = None
        logger.debug(f"Tool '{self.name}' detached from machine.")

    # ───────────────────────────────────────────────────────────────────────────
    # LIFECYCLE HOOKS FOR SUBCLASSES
    # ───────────────────────────────────────────────────────────────────────────
    def post_load(self):
        """
        Optional hook for subclasses: called after the tool is loaded.
        Override in subclasses if needed.
        """
        logger.debug(f"post_load called for tool {self.name}")
        pass

    def pre_unload(self):
        """
        Optional hook for subclasses: called before the tool is unloaded.
        Override in subclasses if needed.
        """
        logger.debug(f"pre_unload called for tool {self.name}")
        pass

    # ───────────────────────────────────────────────────────────────────────────
    # TOOL INFO & REPRESENTATION
    # ───────────────────────────────────────────────────────────────────────────
    def info(self) -> dict:
        """
        Return a summary of the tool's configuration and state.
        Returns:
            dict: Tool info (index, name, class, extra attributes).
        """
        d = {
            'index': self.index,
            'name': self.name,
            'class': self.__class__.__name__,
        }
        # Add extra attributes (excluding private and built-in)
        extras = {k: v for k, v in self.__dict__.items() if not k.startswith('_') and k not in d}
        d.update(extras)
        return d

    def __repr__(self):
        return f"<{self.__class__.__name__} name='{self.name}' index={self.index}>"

# ═══════════════════════════════════════════════════════════════════════════════
# DECORATORS (OPTIONAL)
# ═══════════════════════════════════════════════════════════════════════════════
def requires_active_tool(func):
    """
    Decorator to ensure that a tool cannot complete an action unless it is the current active tool.
    Raises ToolStateError if not active (requires manager to set is_active_tool if used).
    """
    def wrapper(self, *args, **kwargs):
        if hasattr(self, 'is_active_tool') and not self.is_active_tool:
            logger.error(
                f"Attempted to use inactive tool '{self.name}' for action '{func.__name__}'"
            )
            raise ToolStateError(
                f"Error: Tool {self.name} is not the current `Active Tool`. Cannot perform this action"
            )
        logger.debug(
            f"Tool '{self.name}' is active. Proceeding with '{func.__name__}'"
        )
        return func(self, *args, **kwargs)
    return wrapper

