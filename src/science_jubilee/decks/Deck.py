import json
import os
from dataclasses import dataclass
from typing import Dict, Tuple, Optional, Any

from science_jubilee.labware.Labware import Labware
from science_jubilee.utils.exceptions import (DeckError, DeckStateError, DeckConfigurationError, DeckNotFoundError, DeckOccupiedError, DeckEmptyError)
from science_jubilee.utils.logger_utils import setup_logging

logger = setup_logging(logger_name="Deck")

# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class Slot:
    """
    Represents a slot on the deck. Supports flexible shapes and coordinates.
    :param slot_index: Unique index of the slot (int or str)
    :param coordinates: (x, y) coordinates of the slot (relative to deck origin)
    :param shape: Shape of the slot (e.g. 'rectangle', 'circle')
    :param width: Width (for rectangle)
    :param length: Length (for rectangle)
    :param diameter: Diameter (for circle)
    :param has_labware: Whether a labware is loaded
    :param labware: Labware object or None
    """
    slot_index: str
    coordinates: Tuple[float, float]
    shape: str
    width: Optional[float] = None
    length: Optional[float] = None
    diameter: Optional[float] = None
    has_labware: bool = False
    labware: Optional[Any] = None

# ═══════════════════════════════════════════════════════════════════════════════
# SLOT SET
# ═══════════════════════════════════════════════════════════════════════════════
class SlotSet:
    """
    Represents a set of slots on the deck.
    :param slots: Dict of Slot objects, keyed by slot index (as str)
    """
    def __init__(self, slots: Dict[str, Slot]):
        self.slots = slots

    def __repr__(self):
        return f"<SlotSet: {len(self.slots)} slots>"
 
    def __getitem__(self, id_):
        try:
            return self.slots[str(id_)]
        except KeyError:
            raise DeckStateError(f"Slot '{id_}' not found in deck.")

    def __iter__(self):
        return iter(self.slots.values())

# ═══════════════════════════════════════════════════════════════════════════════
# DECK CLASS
# ═══════════════════════════════════════════════════════════════════════════════
class Deck(SlotSet):
    """
    Represents a deck configuration for the Jubilee machine.

    Loads from a JSON file with flexible slot definitions.
    """
    def __init__(self, deck_filename: str, path: Optional[str] = None):
        """
        Initialize the Deck from a JSON configuration file.
        Args:
            deck_filename (str): Name of the deck JSON file
            path (Optional[str]): Optional path to the deck file (default: deck_definition/)
        Raises:
            DeckNotFoundError: If the deck file does not exist.
            DeckConfigurationError: If the file or its content is invalid.
        """
        # Determine path
        if path is None:
            path = os.path.join(os.path.dirname(__file__), "deck_definition")
        elif not os.path.isabs(path):
            path = os.path.abspath(os.path.join(os.path.dirname(__file__), path))
        else:
            path = os.path.abspath(path)
        if not deck_filename.endswith(".json"):
            deck_filename += ".json"
        config_path = os.path.join(path, deck_filename)
        logger.info(f"Loading deck configuration from: {config_path}")
        if not os.path.exists(config_path):
            logger.error(f"Deck file not found: {config_path}")
            raise DeckNotFoundError(f"Deck file not found: {config_path}")
        try:
            with open(config_path, "r") as f:
                deck_config = json.load(f)
        except DeckNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to load deck config: {e}")
            raise DeckConfigurationError(f"Failed to load deck config: {e}")

        self.path = path
        self.config_path = config_path
        self.deck_config = deck_config
        
        self.deck_filename = deck_filename
        self.name = deck_config.get("name", os.path.splitext(deck_filename)[0])
        self.description = deck_config.get("description", "")
        self.deck_type = deck_config.get("type", "")
        
        self.deck_offset = tuple(deck_config.get("deck_offset", [0.0, 0.0]))
        self.material = deck_config.get("material", {})
        self.slot_reference_corner = deck_config.get("slot_reference_corner", "bottom_left")
        self.safe_z_clearance = deck_config.get("safe_z_clearance", 10.0)
        self.slots_data = deck_config.get("slots", {})
        self.slots = self._parse_slots()
        
        super().__init__(self.slots)
        
        logger.info(f"Deck '{self.name}' loaded with {len(self.slots)} slots.")

    def _parse_slots(self) -> Dict[str, Slot]:
        """
        Parse the slots from the deck configuration.
        Returns:
            Dict[str, Slot]: Dictionary of slot objects.
        Raises:
            DeckConfigurationError: If a slot is malformed or missing required fields.
        """
        slots = {}
        for s, sv in self.slots_data.items():
            try:
                slot_kwargs = dict(sv)
                slot_kwargs.setdefault("slot_index", s)
                # Ensure coordinates are tuple and present
                coords = slot_kwargs.get("coordinates")
                if coords is None:
                    raise DeckConfigurationError(f"Slot '{s}' missing 'coordinates'.")
                slot_kwargs["coordinates"] = tuple(coords)
                # Robustness: check shape and required fields
                shape = slot_kwargs.get("shape")
                if shape == "rectangle":
                    if slot_kwargs.get("width") is None or slot_kwargs.get("length") is None:
                        raise DeckConfigurationError(f"Rectangle slot '{s}' missing 'width' or 'length'.")
                elif shape == "circle":
                    if slot_kwargs.get("diameter") is None:
                        raise DeckConfigurationError(f"Circle slot '{s}' missing 'diameter'.")
                slots[s] = Slot(**slot_kwargs)
            except Exception as e:
                logger.error(f"Error parsing slot '{s}': {e}")
                raise DeckConfigurationError(f"Error parsing slot '{s}': {e}")
        return slots

    def __repr__(self) -> str:
        """
        Return a string representation of the deck.
        Returns:
            str: Human-readable summary of the deck.
        """
        return f"<Deck name='{self.name}', type='{self.deck_type}', slots={len(self.slots)}>"

    # ═══════════════════════════════════════════════════════════════════════════
    # PROPERTIES
    # ═══════════════════════════════════════════════════════════════════════════
    @property
    def safe_z(self) -> float:
        """
        Return the safe Z clearance for the deck.
        Returns:
            float: Safe Z clearance value.
        """
        return self.safe_z_clearance

    @safe_z.setter
    def safe_z(self, val: float) -> None:
        """
        Update the safe Z clearance if the new value is greater.
        Args:
            val (float): New safe Z value.
        """
        if val > self.safe_z_clearance:
            self.safe_z_clearance = val



    def get_slot(self, slot_index: str) -> Slot:
        """
        Get a slot by its index (as string).
        Args:
            slot_index (str): Index of the slot.
        Returns:
            Slot: The slot object.
        Raises:
            DeckStateError: If the slot does not exist.
            DeckError: For unexpected errors.
        """
        try:
            return self.slots[str(slot_index)]
        except KeyError:
            raise DeckStateError(f"Slot '{slot_index}' not found in deck.")
        except Exception as e:
            logger.error(f"Unexpected error when accessing slot '{slot_index}': {e}")
            raise DeckError(f"Unexpected error when accessing slot '{slot_index}': {e}")

    def list_slots(self) -> list:
        """
        Return a list of all slot indices.
        Returns:
            list: List of slot indices (as strings).
        """
        return list(self.slots.keys())

    # ═══════════════════════════════════════════════════════════════════════════
    # SLOT ACCESSORS & HELPERS
    # ═══════════════════════════════════════════════════════════════════════════
    def get_slot_info(self, slot_index: str) -> dict:
        """
        Return all information for a given slot index.
        Args:
            slot_index (str): The slot index as a string.
        Returns:
            dict: All slot attributes as a dictionary.
        Raises:
            DeckStateError: If the slot does not exist.
        """
        try:
            slot = self.get_slot(slot_index)
            return slot.__dict__
        except DeckStateError as e:
            logger.error(f"Error in get_slot_info: {e}")
            raise

    def get_slot_coordinates(self, slot_index: str) -> Tuple[float, float]:
        """
        Return the (x, y) coordinates of a given slot.
        Args:
            slot_index (str): The slot index as a string.
        Returns:
            Tuple[float, float]: The coordinates of the slot.
        Raises:
            DeckStateError: If the slot does not exist.
        """
        try:
            return self.get_slot(slot_index).coordinates
        except DeckStateError as e:
            logger.error(f"Error in get_slot_coordinates: {e}")
            raise

    def get_slot_shape(self, slot_index: str) -> str:
        """
        Return the shape of a given slot.
        Args:
            slot_index (str): The slot index as a string.
        Returns:
            str: The shape of the slot (e.g. 'rectangle', 'circle').
        Raises:
            DeckStateError: If the slot does not exist.
        """
        try:
            return self.get_slot(slot_index).shape
        except DeckStateError as e:
            logger.error(f"Error in get_slot_shape: {e}")
            raise

    def get_slot_dimensions(self, slot_index: str) -> dict:
        """
        Return the dimensions of a given slot (width/length/diameter).
        Args:
            slot_index (str): The slot index as a string.
        Returns:
            dict: Dictionary of dimensions (width, length, diameter as available).
        Raises:
            DeckStateError: If the slot does not exist.
        """
        try:
            slot = self.get_slot(slot_index)
            return {
                "width": slot.width,
                "length": slot.length,
                "diameter": slot.diameter
            }
        except DeckStateError as e:
            logger.error(f"Error in get_slot_dimensions: {e}")
            raise

    def get_summary(self) -> dict:
        """
        Return a summary of the loaded deck and all its slots.
        Returns:
            dict: Deck info and all slot details.
        """
        return {
            "name": self.name,
            "type": self.deck_type,
            "description": self.description,
            "offset": self.deck_offset,
            "material": self.material,
            "safe_z": self.safe_z,
            "slots": {idx: self.get_slot_info(idx) for idx in self.list_slots()}
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # LABWARE MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════
    def load_labware(self, slot: str, labware_filename: str, path: Optional[str] = None, order: str = "rows") -> Labware:
        """
        Load a labware and associate it with a specific slot on the deck.
        Args:
            slot (str): Slot index (as string)
            labware_filename (str): Name of the labware config file
            path (Optional[str]): Path to labware config files
            order (str): Order for labware arrangement
        Returns:
            Labware: The loaded labware object
        Raises:
            DeckOccupiedError: If the slot already contains a labware.
            DeckStateError: If the slot does not exist.
        """
        slot_obj = self.get_slot(slot)
        if slot_obj.has_labware:
            logger.error(f"Slot '{slot}' already has labware loaded.")
            raise DeckOccupiedError(f"Slot '{slot}' already has labware loaded.")
        labware = Labware(labware_filename, order=order)
        labware.add_slot(slot)
        offset = slot_obj.coordinates
        labware.offset = offset
        slot_obj.has_labware = True
        slot_obj.labware = labware
        self.safe_z = getattr(labware, "dimensions", {}).get("zDimension", self.safe_z)
        logger.info(f"Labware '{labware_filename}' loaded into slot {slot}.")
        return labware

    def change_labware(self, slot: str = None, labware_filename: str = None, path: Optional[str] = None, order: str = "rows") -> Labware:
        pass

    def unload_labware(self, slot: str) -> None:
        """
        Unload (remove) the labware from a specific slot.
        Args:
            slot (str): Slot index (as string)
        Raises:
            DeckEmptyError: If the slot does not contain any labware.
            DeckStateError: If the slot does not exist.
        """
        slot_obj = self.get_slot(slot)
        if not slot_obj.has_labware:
            logger.error(f"No labware to unload in slot '{slot}'.")
            raise DeckEmptyError(f"No labware to unload in slot '{slot}'.")
        slot_obj.has_labware = False
        slot_obj.labware = None
        logger.info(f"Labware unloaded from slot '{slot}'.")

    def unload_all_labware(self) -> None:
        """
        Unload (remove) all labware from all slots on the deck.
        Raises:
            DeckEmptyError: If no labware is loaded in any slot.
        """
        unloaded_any = False
        for slot_index in self.list_slots():
            slot_obj = self.get_slot(slot_index)
            if slot_obj.has_labware:
                slot_obj.has_labware = False
                slot_obj.labware = None
                logger.info(f"Labware unloaded from slot '{slot_index}'.")
                unloaded_any = True
        if not unloaded_any:
            logger.warning("No labware to unload in any slot.")
            raise DeckEmptyError("No labware to unload in any slot.")

    def is_labware_loaded(self, slot: str) -> bool:
        """
        Check if a labware is loaded in a specific slot.
        Args:
            slot (str): Slot index (as string)
        Returns:
            bool: True if labware is loaded, False otherwise.
        Raises:
            DeckStateError: If the slot does not exist.
        """
        try:
            return self.get_slot(slot).has_labware
        except DeckStateError as e:
            logger.error(f"Error in is_labware_loaded: {e}")
            raise

    # ═══════════════════════════════════════════════════════════════════════════
    # MACHINE COORDINATE HELPERS
    # ═══════════════════════════════════════════════════════════════════════════
    def get_slot_machine_coordinates(self, slot_index: str) -> Tuple[float, float]:
        """
        Return the machine coordinates (origin machine) of a slot, taking into account the deck_offset.
        Args:
            slot_index (str): The index of the slot.
        Returns:
            Tuple[float, float]: (x, y) coordinates of the slot in the machine reference frame.
        Raises:
            DeckStateError: If the slot does not exist.
        """
        try:
            slot_coords = self.get_slot_coordinates(slot_index)
            deck_offset = self.deck_offset
            return (slot_coords[0] + deck_offset[0], slot_coords[1] + deck_offset[1])
        except DeckStateError as e:
            logger.error(f"Error in get_slot_machine_coordinates: {e}")
            raise

    def get_all_slot_machine_coordinates(self) -> dict:
        """
        Return a dictionary of all slot machine positions.
        Returns:
            dict: {slot_index: (x, y)} for each slot.
        """
        return {idx: self.get_slot_machine_coordinates(idx) for idx in self.list_slots()}

    def get_well_machine_coordinates(self, slot_index: str, well_name: str) -> Optional[Tuple[float, float, float]]:
        """
        Return the machine coordinates of a well, if labware is loaded and the method is available.
        Args:
            slot_index (str): Slot index.
            well_name (str): Well name (e.g. 'A1').
        Returns:
            Tuple[float, float, float] or None: Machine coordinates of the well, or None if not available.
        Raises:
            DeckStateError: If the slot does not exist.
        """
        try:
            slot_obj = self.get_slot(slot_index)
            if not slot_obj.has_labware:
                logger.warning(f"No labware loaded in slot '{slot_index}' for well '{well_name}'.")
                return None
            well_coords = slot_obj.labware.get_well_coordinates(well_name)
            slot_machine_coords = self.get_slot_machine_coordinates(slot_index)
            return (slot_machine_coords[0] + well_coords[0], slot_machine_coords[1] + well_coords[1], well_coords[2])
        except DeckStateError as e:
            logger.error(f"Error in get_well_machine_coordinates: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in get_well_machine_coordinates: {e}")
            raise

    def get_all_well_machine_coordinates(self) -> dict:
        """
        Return a dictionary of all well machine coordinates for all loaded labware.
        Returns:
            dict: {slot_index: {well_name: (x, y, z)}} for each loaded labware.
        """
        all_coords = {}
        for slot_index in self.list_slots():
            try:
                slot = self.get_slot(slot_index)
                if slot.has_labware and slot.labware is not None:
                    wells = {}
                    for well_name in slot.labware.wells:
                        coords = self.get_well_machine_coordinates(slot_index, well_name)
                        if coords is not None:
                            wells[well_name] = coords
                    if wells:
                        all_coords[slot_index] = wells
            except DeckStateError as e:
                logger.error(f"Error in get_all_well_machine_coordinates for slot '{slot_index}': {e}")
        return all_coords

