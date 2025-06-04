from functools import wraps
from typing import Tuple, Optional

from science_jubilee.JubileeController import JubileeController
from science_jubilee.decks.Deck import Deck
from science_jubilee.tools.Tool import Tool


from science_jubilee.utils.exceptions import (
    JubileeError,
    JubileeManagerError,
    DeckError, DeckConfigurationError, DeckStateError,
    ToolError, ToolConfigurationError, ToolStateError,
    JubileeControllerError
)

from science_jubilee.utils.logger_utils import setup_logging

logger = setup_logging(logger_name="JubileeManager")

# ═══════════════════════════════════════════════════════════════════════════════
# CLASS JubileeManager
# ═══════════════════════════════════════════════════════════════════════════════
class JubileeManager:
    """
    High-level manager for the Jubilee machine.

    Responsibilities:
    - Manage the deck
    - Manage up to MAX_TOOLS tools and keep track of the active tool
    - Apply tool offsets automatically during movements
    """
    # ═══════════════════════════════════════════════════════════════════════════
    # INITIALIZATION
    # ═══════════════════════════════════════════════════════════════════════════
    def __init__(
        self,
        controller: JubileeController = None,
        address: str = None,
        simulated: bool = False,
        max_tools: int = 4
    ) -> None:
        """
        Initialize the JubileeManager.
        Args:
            controller (JubileeController, optional): Existing controller instance.
            address (str, optional): Address for controller creation if not provided.
            simulated (bool, optional): If True, runs in simulation mode.
            max_tools (int, optional): Maximum number of tool slots (default: 4).
        Attributes:
            controller (JubileeController): Low-level controller instance.
            deck (Deck | None): Loaded deck object.
            MAX_TOOLS (int): Maximum number of tool slots.
            tools_list (dict[int, Tool | None]): Tool slots.
            tool_offsets (dict[int, tuple[float, float, float]]): Tool offsets.
            active_tool_index (int | None): Index of the currently active tool.
            simulated (bool): Simulation mode flag.
        """
        if controller is not None:
            self.controller = controller
        elif address is not None:
            self.controller = JubileeController(address=address, simulated=simulated)
        else:
            logger.error("Either a controller or an address must be provided.")
            raise JubileeManagerError("Either a controller or an address must be provided.")

        self.simulated: bool = simulated
        self.deck: Optional[Deck] = None
        self.MAX_TOOLS: int = max_tools
        self.tools_list: dict[int, Optional[Tool]] = {i: None for i in range(self.MAX_TOOLS)}
        self.tool_offsets: dict[int, tuple[float, float, float]] = {}
        self.active_tool_index: Optional[int] = None
        logger.info(f"JubileeManager initialized (simulated={simulated}, max_tools={self.MAX_TOOLS}).")  

    # ═══════════════════════════════════════════════════════════════════════════
    # DECK MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════
    def load_deck(self, deck_filename: str, path: str = None) -> Deck:
        """
        Load a deck configuration file and store it in the manager.
        Args:
            deck_filename (str): The base name of the deck configuration file (with or without '.json').
            path (str, optional): Optional custom path to the deck configuration file.
        Raises:
            DeckStateError: If a deck is already loaded.
            DeckConfigurationError: If the Deck class fails to load the file.
        Returns:
            Deck: The loaded deck object.
        """
        if self.deck is not None:
            logger.error("Deck already loaded. Unload first.")
            raise DeckStateError("Deck already loaded. Unload first.")
        try:
            self.deck = Deck(deck_filename, path)
            logger.info(f"Deck '{self.deck.name}' loaded from '{self.deck.path}'.")
            return self.deck
        except Exception as e:
            logger.error(f"Failed to load deck '{deck_filename}': {e}")
            raise DeckConfigurationError(f"Failed to load deck: {e}")

    def change_deck(self, deck_filename: str, path: str = None) -> Deck:
        """
        Change the current deck to a new one. Only allowed if a deck is already loaded.
        Args:
            deck_filename (str): New deck filename (with or without '.json').
            path (str, optional): Optional path to look for the new deck file.
        Raises:
            DeckStateError: If no deck is currently loaded.
        Returns:
            Deck: The loaded deck object.
        """
        if self.deck is None:
            logger.error("No deck loaded. Cannot change deck.")
            raise DeckStateError("No deck loaded. Cannot change deck.")
        self.unload_deck()
        return self.load_deck(deck_filename, path)

    def unload_deck(self) -> None:
        """
        Unload the currently loaded deck.
        Raises:
            DeckStateError: If no deck is loaded.
        """
        if self.deck is None:
            logger.error("No deck loaded.")
            raise DeckStateError("No deck loaded.")
        logger.info(f"Unloading deck '{self.deck.name}'.")
        self.deck = None

    def is_deck_loaded(self) -> bool:
        """
        Return True if a deck is loaded.
        Returns:
            bool: True if a deck is loaded, False otherwise.
        """
        return self.deck is not None

    # ═══════════════════════════════════════════════════════════════════════════
    # TOOL MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════
    def load_tool(self, tool: Tool, index: int) -> None:
        """
        Load a tool at a fixed index on the machine.
        Args:
            tool (Tool): Tool instance to load.
            index (int): Fixed index (0 to MAX_TOOLS-1) where to place the tool.
        Raises:
            ToolStateError: If a tool is already loaded at this index or the tool is already loaded elsewhere.
            ToolConfigurationError: If the index is out of bounds or the tool limit is exceeded.
        """
        if not (0 <= index < self.MAX_TOOLS):
            logger.error(f"Tool index {index} out of bounds (0-{self.MAX_TOOLS-1}).")
            raise ToolConfigurationError(f"Tool index {index} out of bounds (0-{self.MAX_TOOLS-1}).")
        if index in self.tools_list and self.tools_list[index] is not None:
            logger.error(f"A tool is already loaded at index {index}.")
            raise ToolStateError(f"A tool is already loaded at index {index}.")
        if any(t is tool for t in self.tools_list.values() if t is not None):
            logger.error(f"This tool object is already loaded at another index.")
            raise ToolStateError("This tool object is already loaded at another index.")
        if len([t for t in self.tools_list.values() if t is not None]) >= self.MAX_TOOLS:
            logger.error(f"Cannot load more than {self.MAX_TOOLS} tools.")
            raise ToolConfigurationError(f"Cannot load more than {self.MAX_TOOLS} tools.")
        self.tools_list[index] = tool
        logger.info(f"Tool '{tool.name}' loaded at index {index}.")

    def change_tool(self, tool: Tool, index: int) -> None:
        """
        Replace the tool at the given index with a new tool instance.
        Only allowed if a tool is already loaded at this index.
        Args:
            tool (Tool): New tool instance to load.
            index (int): Fixed index (0 to MAX_TOOLS-1).
        Raises:
            ToolConfigurationError: If the index is out of bounds.
            ToolStateError: If no tool is loaded at this index, or if the tool is already loaded at any index.
        """
        if not (0 <= index < self.MAX_TOOLS):
            logger.error(f"Tool index {index} out of bounds (0-{self.MAX_TOOLS-1}).")
            raise ToolConfigurationError(f"Tool index {index} out of bounds (0-{self.MAX_TOOLS-1}).")
        if self.tools_list.get(index) is None:
            logger.error(f"No tool to replace at index {index}.")
            raise ToolStateError(f"No tool to replace at index {index}.")
        for idx, t in self.tools_list.items():
            if t is tool:
                logger.error(f"This tool object is already loaded at index {idx}. Cannot change tool at index {index}.")
                raise ToolStateError(f"This tool object is already loaded at index {idx}. Cannot change tool at index {index}.")
        old_tool_name = self.tools_list[index].name
        self.tools_list[index] = tool
        logger.info(f"Tool '{old_tool_name}' replaced by '{tool.name}' at index {index}.")

    def unload_tool(self, index: int) -> None:
        """
        Unload a tool from the specified index.
        Args:
            index (int): Tool index to unload.
        Raises:
            ToolStateError: If no tool is loaded at this index.
        """
        if not self.is_tool_loaded(index):
            logger.error(f"No tool loaded at index {index} to unload.")
            raise ToolStateError(f"No tool loaded at index {index} to unload.")
        tool_name = self.tools_list[index].name
        self.tools_list[index] = None
        if index in self.tool_offsets:
            del self.tool_offsets[index]
        if self.active_tool_index == index:
            self.active_tool_index = None
            logger.info(f"Active tool at index {index} was unloaded. No active tool now.")
        logger.info(f"Tool '{tool_name}' unloaded from index {index}.")

    def unload_all_tools(self) -> None:
        """
        Unload all tools from the machine.
        Raises:
            ToolStateError: If no tools are loaded.
        """
        unloaded_any = False
        for idx in list(self.tools_list.keys()):
            if self.tools_list[idx] is not None:
                tool_name = self.tools_list[idx].name
                self.tools_list[idx] = None
                if idx in self.tool_offsets:
                    del self.tool_offsets[idx]
                if self.active_tool_index == idx:
                    self.active_tool_index = None
                    logger.info(f"Active tool at index {idx} was unloaded. No active tool now.")
                logger.info(f"Tool '{tool_name}' unloaded from index {idx}.")
                unloaded_any = True
        if not unloaded_any:
            logger.warning("No tools to unload.")
            raise ToolStateError("No tools to unload.")

    def is_tool_loaded(self, index: int) -> bool:
        """
        Check if a tool is loaded at the given index.
        Args:
            index (int): Fixed index (0 to MAX_TOOLS-1).
        Returns:
            bool: True if a tool is loaded at this index, False otherwise.
        Raises:
            ToolConfigurationError: If the index is out of bounds.
        """
        if not (0 <= index < self.MAX_TOOLS):
            logger.error(f"Tool index {index} out of bounds (0-{self.MAX_TOOLS-1}).")
            raise ToolConfigurationError(f"Tool index {index} out of bounds (0-{self.MAX_TOOLS-1}).")
        return self.tools_list.get(index) is not None

    def get_loaded_tools(self) -> list[dict]:
        """
        Return a list of all loaded tools with their index and name.
        Returns:
            list: List of dicts with keys 'index' and 'name' for each loaded tool.
        """
        return [
            {'index': idx, 'name': tool.name}
            for idx, tool in self.tools_list.items() if tool is not None
        ]

    def get_tool(self, index: int) -> dict:
        """
        Get the tool info at a given index.
        Args:
            index (int): Tool index (0 to MAX_TOOLS-1).
        Returns:
            dict: {'index': index, 'name': tool.name, 'tool': tool} if loaded.
        Raises:
            ToolConfigurationError: If the index is out of bounds.
            ToolStateError: If no tool is loaded at this index.
        """
        if not (0 <= index < self.MAX_TOOLS):
            logger.error(f"Tool index {index} out of bounds (0-{self.MAX_TOOLS-1}).")
            raise ToolConfigurationError(f"Tool index {index} out of bounds (0-{self.MAX_TOOLS-1}).")
        tool = self.tools_list.get(index)
        if tool is not None:
            return {'index': index, 'name': tool.name, 'tool': tool}
        logger.error(f"No tool loaded at index {index}.")
        raise ToolStateError(f"No tool loaded at index {index}.")

    def get_tool_by_name(self, tool_name: str) -> dict:
        """
        Get the tool info by its name.
        Args:
            tool_name (str): Name of the tool to search for.
        Returns:
            dict: {'index': idx, 'name': tool.name, 'tool': tool} if found.
        Raises:
            ToolStateError: If no tool with this name is loaded.
        """
        for idx, tool in self.tools_list.items():
            if tool is not None and getattr(tool, 'name', None) == tool_name:
                return {'index': idx, 'name': tool.name, 'tool': tool}
        logger.error(f"No tool loaded with name '{tool_name}'.")
        raise ToolStateError(f"No tool loaded with name '{tool_name}'.")

    # ═══════════════════════════════════════════════════════════════════════════
    # TOOL OFFSETS
    # ═══════════════════════════════════════════════════════════════════════════
    def set_tool_offset(self, index: int, offset: tuple[float, float, float]) -> None:
        """
        Set the XYZ offset for a tool at a given index.
        Args:
            index (int): Tool index (0 to MAX_TOOLS-1).
            offset (tuple): (x, y, z) offset to set.
        Raises:
            ToolStateError: If no tool is loaded at this index.
        """
        if not self.is_tool_loaded(index):
            logger.error(f"No tool loaded at index {index} to set offset.")
            raise ToolStateError(f"No tool loaded at index {index} to set offset.")
        self.tool_offsets[index] = offset
        logger.info(f"Offset for tool at index {index} set to {offset}.")

    def get_tool_offset(self, index: int) -> tuple[float, float, float]:
        """
        Get the XYZ offset for a tool at a given index.
        Args:
            index (int): Tool index (0 to MAX_TOOLS-1).
        Returns:
            tuple: (x, y, z) offset for the tool.
        Raises:
            ToolStateError: If no tool is loaded at this index.
        """
        if not self.is_tool_loaded(index):
            logger.error(f"No tool loaded at index {index} to get offset.")
            raise ToolStateError(f"No tool loaded at index {index} to get offset.")
        return self.tool_offsets.get(index, (0.0, 0.0, 0.0))

    # ═══════════════════════════════════════════════════════════════════════════
    # ACTIVE TOOL MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════
    def set_active_tool(self, index: int) -> None:
        """
        Set the active tool by index.
        Args:
            index (int): Tool index to set as active.
        Raises:
            ToolStateError: If no tool is loaded at this index.
        """
        if not self.is_tool_loaded(index):
            logger.error(f"No tool loaded at index {index} to set as active.")
            raise ToolStateError(f"No tool loaded at index {index} to set as active.")
        self.active_tool_index = index
        logger.info(f"Tool at index {index} set as active tool.")

    def set_active_tool_by_name(self, tool_name: str) -> None:
        """
        Set the active tool by its name.
        Args:
            tool_name (str): Name of the tool to set as active.
        Raises:
            ToolStateError: If no tool with this name is loaded.
        """
        for idx, tool in self.tools_list.items():
            if tool is not None and getattr(tool, 'name', None) == tool_name:
                self.active_tool_index = idx
                logger.info(f"Tool '{tool_name}' at index {idx} set as active tool.")
                return
        logger.error(f"No tool loaded with name '{tool_name}' to set as active.")
        raise ToolStateError(f"No tool loaded with name '{tool_name}' to set as active.")

    def get_active_tool(self) -> tuple[Optional[int], Optional[object]]:
        """
        Get the active tool's index and object.
        Returns:
            tuple: (index, tool) if active tool is set, else (None, None)
        """
        idx = self.active_tool_index
        if idx is not None and self.is_tool_loaded(idx):
            return idx, self.tools_list[idx]
        return None, None

    def get_active_tool_position(self) -> tuple[float, float, float]:
        """
        Get the current position of the active tool (with offset applied).
        Returns:
            tuple: (x, y, z) position of the active tool in workspace coordinates.
        Raises:
            ToolStateError: If no active tool is set.
        """
        idx = self.active_tool_index
        if idx is None or not self.is_tool_loaded(idx):
            logger.error("No active tool to get position.")
            raise ToolStateError("No active tool to get position.")
        # Get the machine position as a dict and apply the tool offset
        machine_pos = self.controller.get_position()
        offset = self.get_tool_offset(idx)
        workspace_pos = (
            machine_pos.get("X", 0.0) - offset[0],
            machine_pos.get("Y", 0.0) - offset[1],
            machine_pos.get("Z", 0.0) - offset[2],
        )
        logger.info(f"Active tool at index {idx} workspace position: {workspace_pos} (machine: {machine_pos}, offset: {offset})")
        return workspace_pos

    # ═══════════════════════════════════════════════════════════════════════════
    # TOOL PICKUP AND PARKING
    # ═══════════════════════════════════════════════════════════════════════════
    def pickup_tool(self, index: int, speed: float = 6000) -> None:
        """
        Pick up a tool at the given index using the controller's sequence, with safety checks.
        Args:
            index (int): Tool index to pick up.
            speed (float): Movement speed.
        Raises:
            ToolStateError: If a tool is already loaded.
        """
        if self.active_tool_index is not None:
            logger.error(f"Cannot pick up tool {index}: another tool (index {self.active_tool_index}) is already loaded.")
            raise ToolStateError(f"A tool (index {self.active_tool_index}) is already loaded. Park it before picking up another.")
        if not self.is_tool_loaded(index):
            logger.error(f"Cannot pick up tool {index}: no tool loaded at this index.")
            raise ToolStateError(f"No tool loaded at index {index} to pick up.")
        # Calcul dynamique du Z pour la prise d'outil
        z_deck = self.deck.deck_offset[2] if self.deck and len(self.deck.deck_offset) > 2 else 0.0
        z_tool = self.get_tool_offset(index)[2] if index in self.tool_offsets else 0.0
        z_park = z_deck + z_tool
        logger.info(f"pickup_tool: Using Z={z_park} (deck offset {z_deck} + tool offset {z_tool}) for tool {index}.")
        # On suppose que la séquence du controller accepte un paramètre z_park (sinon il faut l'ajouter)
        self.controller.pickup_tool_sequence(index, speed=speed, z_park=z_park)
        self.active_tool_index = index
        logger.info(f"Tool at index {index} picked up and set as active.")

    def park_active_tool(self, speed: float = 6000) -> None:
        """
        Park the currently active tool using the controller's sequence, with safety checks.
        Args:
            speed (float): Movement speed.
        Raises:
            ToolStateError: If no tool is currently active.
        """
        if self.active_tool_index is None:
            logger.error("No active tool to park.")
            raise ToolStateError("No active tool to park.")
        index = self.active_tool_index
        z_deck = self.deck.deck_offset[2] if self.deck and len(self.deck.deck_offset) > 2 else 0.0
        z_tool = self.get_tool_offset(index)[2] if index in self.tool_offsets else 0.0
        z_park = z_deck + z_tool
        logger.info(f"park_active_tool: Using Z={z_park} (deck offset {z_deck} + tool offset {z_tool}) for tool {index}.")
        self.controller.park_tool_sequence(index, speed=speed, z_park=z_park)
        self.active_tool_index = None
        logger.info(f"Tool at index {index} parked and no longer active.")

    # ═══════════════════════════════════════════════════════════════════════════
    # HIGH-LEVEL MACHINE CONTROL
    # ═══════════════════════════════════════════════════════════════════════════
    def move_active_tool_effector_to(
        self,
        x: float = None,
        y: float = None,
        z: float = None,
        u: float = None,
        s: float = 6000,
        param: str = None,
        wait: bool = False
    ) -> None:
        """
        Move the active tool to the given (x, y, z, u) position, applying its offset.
        Args:
            x (float): Target X coordinate (in workspace coordinates).
            y (float): Target Y coordinate.
            z (float): Target Z coordinate.
            u (float): Target U coordinate (optional).
            s (float): Speed/feedrate (optional).
            param (str): Extra G-code parameters (optional).
            wait (bool): Wait for move to complete (optional).
        Raises:
            ToolStateError: If no active tool is set.
        """
        idx = self.active_tool_index
        if idx is None or not self.is_tool_loaded(idx):
            logger.error("No active tool to move.")
            raise ToolStateError("No active tool to move.")
        offset = self.get_tool_offset(idx)
        # Only add offset to axes that are not None
        target_x = x + offset[0] if x is not None else None
        target_y = y + offset[1] if y is not None else None
        target_z = z + offset[2] if z is not None else None
        # U is not offset by default, but you can adapt if needed
        logger.info(f"Moving active tool at index {idx} to (x={x}, y={y}, z={z}, u={u}) with offset {offset} (machine position: {target_x}, {target_y}, {target_z}, {u}).")
        self.controller.move_to(x=target_x, y=target_y, z=target_z, u=u, s=s, param=param, wait=wait)

    def move_active_tool_to_well(
        self,
        slot_index: str,
        well_name: str,
        x_offset: float = 0.0,
        y_offset: float = 0.0,
        z_offset: float = 0.0,
        s: float = 6000,
        wait: bool = True
    ) -> None:
        """
        Move the active tool to the machine coordinates above a given well, applying all offsets.
        Args:
            slot_index (str): Slot index on the deck.
            well_name (str): Well name in the labware (e.g. 'A1').
            x_offset, y_offset, z_offset (float): Optional extra offsets to apply.
            s (float): Speed/feedrate.
            wait (bool): Wait for move to complete.
        Raises:
            ToolStateError, DeckStateError: If required info is missing.
        """
        if self.deck is None:
            logger.error("No deck loaded to move to well.")
            raise DeckStateError("No deck loaded.")
        slot = self.deck.get_slot(slot_index)
        if not slot.has_labware or not hasattr(slot.labware, 'get_well_coordinates'):
            logger.error(f"No labware with well coordinates loaded in slot {slot_index}.")
            raise DeckStateError(f"No labware with well coordinates loaded in slot {slot_index}.")
        well_coords = slot.labware.get_well_coordinates(well_name)
        if well_coords is None or len(well_coords) < 2:
            logger.error(f"Well {well_name} not found in labware at slot {slot_index}.")
            raise DeckStateError(f"Well {well_name} not found in labware at slot {slot_index}.")
        x_slot, y_slot = self.deck.get_slot_machine_coordinates(slot_index)
        x = x_slot + well_coords[0] + x_offset
        y = y_slot + well_coords[1] + y_offset
        z = self.get_machine_z(slot_index, well_name) + z_offset
        logger.info(f"Moving active tool to slot {slot_index}, well {well_name} at machine position (x={x}, y={y}, z={z})")
        self.move_active_tool_effector_to(x=x, y=y, z=z, s=s, wait=wait)

    # ═══════════════════════════════════════════════════════════════════════════
    # MANAGER STATE & RESET
    # ═══════════════════════════════════════════════════════════════════════════
    def status(self) -> dict:
        """
        Return a summary of the current state of the manager.
        Returns:
            dict: Summary with deck, loaded tools, active tool, and offsets.
        """
        deck_info = self.deck.name if self.deck else None
        loaded_tools = self.get_loaded_tools()
        active_idx, active_tool = self.get_active_tool()
        return {
            'deck': deck_info,
            'tools': loaded_tools,
            'active_tool_index': active_idx,
            'active_tool_name': getattr(active_tool, 'name', None) if active_tool else None,
            'tool_offsets': self.tool_offsets.copy(),
        }

    def reset(self) -> None:
        """
        Reset the manager: unload all tools, unload deck, reset active tool and offsets.
        """
        self.unload_all_tools()
        if self.deck is not None:
            self.unload_deck()
        self.active_tool_index = None
        self.tool_offsets.clear()
        logger.info("JubileeManager reset: all tools and deck unloaded, offsets cleared.")
        
        
        
        