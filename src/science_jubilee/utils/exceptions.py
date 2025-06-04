"""
Exception hierarchy for the Jubilee project.

All exceptions in this project inherit from `JubileeError`, which allows for broad or fine-grained error handling.

- Each subsystem (Deck, Tool, Labware, Controller, Manager, UI, Experiment) has its own base exception (e.g., DeckError, ToolError, LabwareError, etc.),
  from which more specific exceptions inherit (e.g., DeckConfigurationError, ToolStateError, LabwareNotFoundError).
- Always raise the most specific exception possible in your code.
- Catch the base exception of a subsystem if you want to handle all errors from that subsystem in a generic way.
- Use the `context` argument (where available) to provide additional information for debugging.

Example usage:
    try:
        deck.load_labware(...)
    except DeckConfigurationError as e:
        logger.error(f"Deck configuration failed: {e}")
        raise
    except DeckError as e:
        logger.error(f"Deck error: {e}")
        raise JubileeManagerError("Deck operation failed") from e

This structure ensures robust, modular, and maintainable error handling across the entire Jubilee automation codebase.
"""

# ═══════════════════════════════════════════════════════════════════════════════
# BASE EXCEPTION (JUBILEE)
# ═══════════════════════════════════════════════════════════════════════════════
class JubileeError(Exception):
    """Base class for all exceptions in the Jubilee project."""
    pass

# ============================================================================== 
# JUBILEE MANAGER EXCEPTIONS
# ============================================================================== 
class JubileeManagerError(JubileeError):
    """Base exception for manager-related errors."""
    pass

# ============================================================================== 
# JUBILEE CONTROLLER EXCEPTIONS
# ============================================================================== 
class JubileeControllerError(JubileeError):
    """Base exception for all Jubilee controller errors."""
    def __init__(self, message=None, *, context=None):
        self.context = context
        full_message = f"{message}"
        if context:
            full_message += f" | Context: {context}"
        super().__init__(full_message)

class JubileeStateError(JubileeControllerError):
    """Raised when the Jubilee is in an unexpected state."""

class JubileeConfigurationError(JubileeControllerError):
    """Raised for issues with configuration (axes, offsets, etc.)."""

class JubileeCommunicationError(JubileeControllerError):
    """Raised for communication-related issues."""

class JubileeHomingError(JubileeControllerError):
    """Raised when homing fails or is unsafe."""

class JubileeCollisionError(JubileeControllerError):
    """Raised when a collision is detected."""
    pass

# ============================================================================== 
# DECK EXCEPTIONS
# ============================================================================== 
class DeckError(JubileeError):
    """Base exception for deck-related errors."""
    pass

class DeckConfigurationError(DeckError):
    """Raised when the deck configuration is missing, invalid, or cannot be loaded."""
    pass

class DeckNotFoundError(DeckError):
    """Raised when a requested Deck is not found or not registered."""
    pass

class DeckStateError(DeckError):
    """Raised when an operation is attempted on a deck in an invalid state."""
    pass

class DeckOccupiedError(DeckStateError):
    """Raised when trying to load labware into an already occupied slot."""
    pass

class DeckEmptyError(DeckStateError):
    """Raised when trying to unload or access labware from an empty slot."""
    pass

# ============================================================================== 
# LABWARE EXCEPTIONS
# ============================================================================== 
class LabwareError(JubileeError):
    """Base exception for labware-related errors."""
    pass

class LabwareConfigurationError(LabwareError):
    """Raised when the labware configuration is missing or invalid."""
    pass

class LabwareNotFoundError(LabwareError):
    """Raised when a requested labware is not found or not registered."""
    pass

class LabwareStateError(LabwareError):
    """Raised when the labware is in the wrong state for the requested action."""
    pass

class LabwareAlreadyLoadedError(LabwareStateError):
    """Raised when trying to load labware into a slot that already has labware."""
    pass

class LabwareNotCompatibleError(LabwareStateError):
    """Raised when trying to load incompatible labware into a slot."""
    pass

# ═══════════════════════════════════════════════════════════════════════════════
# EXCEPTIONS TOOLS
# ═══════════════════════════════════════════════════════════════════════════════
class ToolError(JubileeError):
    """Base exception for tool-related errors."""
    pass

class ToolConfigurationError(ToolError):
    """Raised when the tool configuration is missing or invalid."""
    pass

class ToolNotFoundError(ToolError):
    """Raised when a requested tool is not found or not registered."""
    pass

class ToolStateError(ToolError):
    """Raised when the tool is in the wrong state for the requested action."""
    pass

class ToolAlreadyLoadedError(ToolStateError):
    """Raised when trying to load a tool that is already present."""
    pass

class ToolNotActiveError(ToolStateError):
    """Raised when trying to use a tool that is not currently active."""
    pass

class ToolAttachmentError(ToolError):
    """Raised when attaching or detaching a tool fails."""
    pass

class ToolCommunicationError(ToolError):
    """Raised when communication with a smart tool fails."""
    pass

# ============================================================================== 
# UI (IHM) EXCEPTIONS
# ============================================================================== 
class UIError(JubileeError):
    """Base exception for UI-related errors."""
    pass

class UINotificationError(UIError):
    """Raised when a notification to the user fails."""
    pass

class UIInputError(UIError):
    """Raised when user input is invalid or unexpected."""
    pass

class UIDisplayError(UIError):
    """Raised when a display or refresh problem occurs in the UI."""
    pass

# ============================================================================== 
# EXPERIMENT/PROTOCOL EXCEPTIONS
# ============================================================================== 
class ExperimentError(JubileeError):
    """Base exception for experiment/protocol errors."""
    pass

class ExperimentConfigurationError(ExperimentError):
    """Raised when an experiment is misconfigured."""
    pass

class ExperimentNotFoundError(ExperimentError):
    """Raised when a requested experiment is not found or not registered."""
    pass

class ExperimentStateError(ExperimentError):
    """Raised when an experiment cannot proceed due to state."""
    pass

class ExperimentTimeoutError(ExperimentError):
    """Raised when an experiment takes too long or is blocked."""
    pass

class ExperimentInterruptionError(ExperimentError):
    """Raised when an experiment is interrupted by the user or a critical error."""
    pass