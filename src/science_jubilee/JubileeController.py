import json
import time
from functools import wraps
from typing import Optional

import requests
from requests.adapters import HTTPAdapter, Retry

from science_jubilee.utils.exceptions import JubileeControllerError, JubileeStateError, JubileeConfigurationError, JubileeCommunicationError, JubileeHomingError
from science_jubilee.utils.logger_utils import setup_logging

logger = setup_logging(logger_name="JubileeController")

###### LOGS AND ERROR CLASS Not Fully IMPLEMENTED #######

# ═══════════════════════════════════════════════════════════════════════════════
# DECORATORS (SAFETY & STATE CHECKS)
# ═══════════════════════════════════════════════════════════════════════════════

def machine_homed(func):
    """
    Decorator to ensure the machine is homed before executing an action.
    Raises an exception if the machine is not homed. In simulation mode, always passes.
    Only checks X, Y, Z, U axes (first 4 axes).
    """
    @wraps(func)
    def homing_check(self, *args, **kwds):
        if self.simulated:
            return func(self, *args, **kwds)
        try:
            axes_homed = json.loads(self.gcode('M409 K"move.axes[].homed"'))["result"]
        except Exception as e:
            logger.error(f"Unable to check homing state: {e}")
            raise JubileeStateError("Unable to check homing state.") from e
        if not all(axes_homed[:4]):
            logger.warning("Attempted to run a machine command before homing X, Y, Z, U.")
            raise JubileeStateError("Error: The machine must be homed (X, Y, Z, U) before this operation.")
        return func(self, *args, **kwds)
    return homing_check

def safe_homing(func):
    """
    Decorator to always ask for confirmation before homing.
    If a tool is mounted, asks the user to remove it, then always checks that the deck is clear.
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            response = input("Is a tool currently mounted? [y/n] ")
        except EOFError:
            logger.error("User input not available for safe_homing.")
            raise JubileeHomingError("User input not available for safe_homing.")
        if response.lower() in ["y", "yes"]:
            confirm = input("Are you ready to remove it now? [y/n] ")
            if confirm.lower() not in ["y", "yes"]:
                print("Homing cancelled. Please remove the tool first.")
                logger.info("Homing cancelled by user (tool not removed).")
                return
            else:
                self.tool_unlock()
                print("Resuming homing process.")
        # Always check deck clearance, regardless of tool status
        response = input("Is the deck clear of any obstacles? [y/n] ")
        if response.lower() not in ["y", "yes"]:
            print("Please clear the deck before homing the Z axis.")
            logger.info("Homing cancelled by user (deck not clear).")
            return
        return func(self, *args, **kwargs)
    return wrapper

# ═══════════════════════════════════════════════════════════════════════════════
# CLASS JubileeController 
# ═══════════════════════════════════════════════════════════════════════════════
class JubileeController:
    """
    Low-level controller for a Jubilee machine. Provides direct G-code communication,
    status polling, and machine configuration.

    Attributes:
        LOCALHOST (str): Default IP address for local connection.
        ser (Any): Serial connection object (future use, currently None).
        port (str): Serial port (unused).
        baudrate (int): Baudrate for serial connection (unused).
        address (str): IP address of the machine.
        simulated (bool): If True, runs in simulation mode (no hardware communication).
        crash_detection (bool): If True, enables crash detection logic.
        crash_handler (Callable): Optional callback for crash events.
        _absolute_positioning (bool): True if machine is in absolute positioning mode.
        _configured_axes (list[str] | None): List of configured axes.
        _axis_limits (list[tuple[float, float]] | None): Axis limits for each axis.
        axes_homed (list[bool]): Homing status for X, Y, Z, U axes.
        session (requests.Session | None): HTTP session for communication.
        tool_parking_positions (dict): Default parking positions for tools.
    """

    LOCALHOST: str = "192.168.1.2"
    ser: None = None
    port: Optional[str]
    baudrate: int
    address: str
    simulated: bool
    crash_detection: bool
    crash_handler: Optional[callable]
    _absolute_positioning: bool
    _configured_axes: Optional[list[str]]
    _axis_limits: Optional[list[tuple[float, float]]]
    axes_homed: list[bool]
    session: Optional[requests.Session]
    tool_parking_positions: dict

    def __init__(
        self,
        port: str = None,
        baudrate: int = 115200,
        address: str = LOCALHOST,
        simulated: bool = False,
        crash_detection: bool = False,
        crash_handler: callable = None,
    ) -> None:
        """
        Initialize the JubileeController.

        Args:
            port (str, optional): Serial port for future use.
            baudrate (int, optional): Baudrate for serial connection (unused).
            address (str, optional): IP address of the machine (default: LOCALHOST).
            simulated (bool, optional): If True, G-code commands are printed instead of sent.
            crash_detection (bool, optional): If True, detects and handles tool crash events.
            crash_handler (callable, optional): Callback to invoke on crash.
        Raises:
            JubileeControllerError: If connection or initialization fails.
        """
        logger.info(f"Initializing JubileeController (simulated={simulated}, address={address})")
             
        self.ser = None
        self.port = port
        self.baudrate = baudrate
        self.address = address
        self.simulated = simulated

        self.session = None  # HTTP session for communication, None if simulated

        self.crash_detection = crash_detection
        self.crash_handler = crash_handler

        self._absolute_positioning = True
        self._configured_axes = None
        self._axis_limits = None
        self.axes_homed = [False] * 4  # Default: X/Y/Z/U axes
        
        if self.address != self.LOCALHOST:
            logger.warning("Disconnecting this application from the network will halt connection to Jubilee.")
        else:
            logger.debug("Using local connection to Jubilee.")

        if not self.simulated:
            try:
                self.connect()
                self._set_absolute_positioning()
            except Exception as e:
                logger.error(f"Failed to connect or initialize Jubilee machine: {e}")
                raise JubileeControllerError("Initialization failed.") from e
        else:
            logger.info("Running in simulation mode. No connection established.")

        self.tool_parking_positions = {
            0: {"x_park": 277.0, "y_clear": 280.0, "y_park": 342.0, "z_park": 150.0},
            1: {"x_park": 191.0, "y_clear": 280.0, "y_park": 342.0, "z_park": 150.0},
            2: {"x_park": 105.0, "y_clear": 280.0, "y_park": 342.0, "z_park": 150.0},
            3: {"x_park": 19.0, "y_clear": 280.0, "y_park": 342.0, "z_park": 150.0},
        }

    def connect(self) -> None:
        """
        Attempt to connect to the machine and cache state values.
        In simulation mode, sets dummy values and logs the event.
        Raises:
            JubileeCommunicationError: If connection fails.
        """
        if self.simulated:
            logger.info("(SIMULATED) connect() called. Setting dummy state.")
            self.axes_homed = [True, True, True, True]
            self._configured_axes = ["X", "Y", "Z", "U"]
            self._axis_limits = [(0, 300), (0, 300), (0, 300), (0, 200)]
            self._active_tool_index = None
            self._tool_z_offsets = None
            return
        if self.session is not None:
            logger.info("Already connected. Skipping connect().")
            return
        try:
            logger.info("Connecting to Jubilee machine...")
            self.session = self._create_requests_session()  # Ensure session is (re)created
            self.axes_homed = self._retry_json(lambda: self.gcode("M409 K\"move.axes[].homed\""))["result"][:4]
            self._active_tool_index = None
            self._tool_z_offsets = None
            self._configured_axes = self.get_configured_axes()
            self._axis_limits = self.get_axis_limits()
            self._set_absolute_positioning()
            logger.info("Successfully connected and initialized Jubilee machine.")
        except Exception as e:
            logger.error(f"Failed to connect to Jubilee: {e}")
            raise JubileeCommunicationError("Failed to connect to Jubilee.") from e

    def disconnect(self) -> None:
        """
        Close the connection. For HTTP, closes the requests session if open.
        In simulation mode, just logs.
        """
        if self.simulated:
            logger.info("(SIMULATED) disconnect() called.")
            return
        if self.session is None:
            logger.info("Already disconnected. Skipping disconnect().")
            return
        logger.info("Disconnecting from Jubilee machine.")
        try:
            self.session.close()
            logger.info("HTTP session closed.")
        except Exception as e:
            logger.warning(f"Failed to close HTTP session: {e}")
        self.session = None
        return

    def reset(self) -> None:
        """
        Issue a software reset.
        In simulation mode, just logs and resets dummy state.
        Raises:
            JubileeStateError: If reset or reconnection fails.
        """
        if self.simulated:
            logger.info("(SIMULATED) reset() called. Resetting dummy state.")
            self.axes_homed = [False] * 4
            self.connect()
            logger.info("(SIMULATED) reset complete.")
            return
        try:
            logger.info("Issuing software reset (M999)...")
            self.gcode("M999")  # Issue a board reset. Assumes we are already connected
            self.axes_homed = [False] * 4
            self.disconnect()
            logger.info("Reconnecting after reset...")
            for retries in range(15):
                time.sleep(2)  # Wait 2 seconds before retrying
                try:
                    self.connect()
                    logger.info("Reconnected successfully after reset.")
                    return
                except JubileeStateError as e:
                    logger.warning(f"Reconnect attempt {retries+1} failed: {e}")
            logger.error("Reconnecting failed after reset.")
            raise JubileeStateError("Reconnecting failed.")
        except Exception as e:
            logger.error(f"Reset failed: {e}")
            raise JubileeStateError("Reset failed.") from e

    def __enter__(self) -> "JubileeController":
        """
        Enter context manager for JubileeController.
        Returns:
            JubileeController: The controller instance.
        """
        logger.debug("Entering context manager for JubileeController.")
        return self

    def __exit__(self, *args) -> None:
        """
        Exit context manager for JubileeController. Disconnects from the machine.
        """
        logger.debug("Exiting context manager for JubileeController.")
        self.disconnect()

    # ═══════════════════════════════════════════════════════════════════════════
    # SESSION & COMMUNICATION HELPERS
    # ═══════════════════════════════════════════════════════════════════════════
    def _create_requests_session(self) -> Optional[requests.Session]:
        """
        Create and configure a requests session with retry logic.
        In simulation mode, returns None.
        Returns:
            Optional[requests.Session]: Configured session or None if simulated.
        Raises:
            JubileeCommunicationError: If session creation fails.
        """
        if self.simulated:
            logger.debug("(SIMULATED) HTTP session not created.")
            return None
        try:
            session = requests.Session()
            retries = Retry(total=5, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])
            session.mount("http://", HTTPAdapter(max_retries=retries))
            session.headers["Connection"] = "close"
            logger.debug("HTTP session created with retry logic.")
            return session
        except Exception as e:
            logger.error(f"Failed to create HTTP session: {e}")
            raise JubileeCommunicationError("Failed to create HTTP session.") from e

    def _retry_json(self, func: callable, max_tries: int = 15) -> dict:
        """
        Retry a function returning JSON until success or max tries.
        In simulation mode, returns a dummy result.
        Args:
            func (callable): Function to call.
            max_tries (int): Maximum number of attempts.
        Returns:
            dict: JSON result.
        Raises:
            TimeoutError: If max retries exceeded.
        """
        if self.simulated:
            logger.debug("(SIMULATED) returning dummy JSON result.")
            return {"result": [True, True, True, True]}
        for attempt in range(max_tries):
            try:
                result = json.loads(func())
                if result.get("result"):
                    logger.debug(f"JSON command succeeded on attempt {attempt+1}.")
                    return result
            except Exception as e:
                logger.warning(f"JSON command failed on attempt {attempt+1}: {e}")
                time.sleep(2)  # Wait 2 seconds between retries for robustness
        logger.error("Max retries exceeded for JSON command.")
        raise TimeoutError("Max retries exceeded for JSON command.")
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # GCODE COMMUNICATION
    # ═══════════════════════════════════════════════════════════════════════════════
    def gcode(self, cmd: str = "", timeout: float = None, response_wait: float = 60) -> str:
        """
        Send a G-Code command to the Machine and return the response.

        Args:
            cmd (str): The G-Code command to send.
            timeout (float, optional): The time to wait for a response from the machine.
            response_wait (float, optional): The time to wait for a response from the machine.
        Returns:
            str: The response message from the machine.
        Raises:
            JubileeCommunicationError: If communication fails or if not connected.
        """
        if self.simulated:
            logger.debug(f"(SIMULATED) G-code: {cmd}")
            # Simulate some responses for common commands
            if cmd.startswith("M409"):
                return json.dumps({"result": [True, True, True, True]})
            if cmd.startswith("M114"):
                return "X:0.00 Y:0.00 Z:0.00 U:0.00 Count 0 0 0 0"
            if cmd.startswith("M119"):
                return "X: open\nY: open\nZ: open\nU: open"
            return ""
        if self.session is None:
            logger.error("Attempted to send G-code while not connected. Call connect() first.")
            raise JubileeCommunicationError("Not connected: call connect() before sending G-code commands.")
        try:
            logger.debug(f"Sending G-code via /machine/code: {cmd}")
            response = self.session.post(f"http://{self.address}/machine/code", data=cmd, timeout=timeout).text
            if "rejected" not in response:
                logger.debug(f"G-code response: {response}")
                return response
        except requests.RequestException as e:
            logger.warning(f"/machine/code endpoint failed: {e}")
            # Fallback to rr_gcode method below
        try:
            reply_count = self.session.get(f"http://{self.address}/rr_model?key=seqs").json()["result"]["reply"]
            self.session.get(f"http://{self.address}/rr_gcode?gcode={cmd}", timeout=timeout)
            tic = time.time()
            while True:
                new_count = self.session.get(f"http://{self.address}/rr_model?key=seqs").json()["result"]["reply"]
                if new_count != reply_count:
                    response = self.session.get(f"http://{self.address}/rr_reply").text
                    if self.crash_detection and "crash detected" in response:
                        logger.error("Crash detected during G-code execution!")
                        raise JubileeStateError("Crash detected during G-code execution!")
                    logger.debug(f"G-code reply: {response}")
                    return response
                if time.time() - tic > response_wait:
                    logger.error(f"Timeout waiting for G-code reply after {response_wait} seconds.")
                    raise JubileeCommunicationError("Timeout waiting for G-code reply.")
                time.sleep(self._delay_time(int((time.time() - tic) * 10)))
        except Exception as e:
            logger.warning(f"G-code communication failed: {e}")
            raise JubileeCommunicationError(f"G-code communication failed: {e}") from e
        
    def _delay_time(self, n: int) -> float:
        """
        Calculate delay time for next request. (Simple hardcoded backoff)
        Args:
            n (int): Number of attempts.
        Returns:
            float: Delay in seconds.
        """
        if n == 0:
            return 0
        if n < 10:
            return 0.1
        if n < 20:
            return 0.2
        if n < 30:
            return 0.3
        else:
            return 1

    def push_machine_state(self) -> None:
        """
        Push machine state onto a stack.
        In simulation mode, just logs.
        Raises:
            JubileeStateError: If push fails.
        """
        if self.simulated:
            logger.debug("(SIMULATED) push_machine_state() called.")
            return
        try:
            logger.debug("Pushing machine state (M120).")
            self.gcode("M120")
        except Exception as e:
            logger.error(f"Failed to push machine state: {e}")
            raise JubileeStateError("Failed to push machine state.") from e

    def pop_machine_state(self) -> None:
        """
        Recover previous machine state.
        In simulation mode, just logs.
        Raises:
            JubileeStateError: If pop fails.
        """
        if self.simulated:
            logger.debug("(SIMULATED) pop_machine_state() called.")
            return
        try:
            logger.debug("Popping machine state (M121).")
            self.gcode("M121")
        except Exception as e:
            logger.error(f"Failed to pop machine state: {e}")
            raise JubileeStateError("Failed to pop machine state.") from e

    # ═══════════════════════════════════════════════════════════════════════════════
    # HOMING
    # ═══════════════════════════════════════════════════════════════════════════════
    def _home_x(self) -> None:
        """
        Home the X axis (G28 X).
        In simulation mode, sets the X axis as homed and logs the action.
        Raises:
            JubileeHomingError: If homing the X axis fails.
        """
        if self.simulated:
            logger.debug("(SIMULATED) home X axis.")
            self.axes_homed[0] = True
            return
        try:
            self.gcode("G28 X")
            self.axes_homed[0] = True
        except Exception as e:
            logger.error(f"Homing X failed: {e}")
            raise JubileeHomingError("Failed to home X axis.") from e

    def _home_y(self) -> None:
        """
        Home the Y axis (G28 Y).
        In simulation mode, sets the Y axis as homed and logs the action.
        Raises:
            JubileeHomingError: If homing the Y axis fails.
        """
        if self.simulated:
            logger.debug("(SIMULATED) home Y axis.")
            self.axes_homed[1] = True
            return
        try:
            self.gcode("G28 Y")
            self.axes_homed[1] = True
        except Exception as e:
            logger.error(f"Homing Y failed: {e}")
            raise JubileeHomingError("Failed to home Y axis.") from e

    def _home_u(self) -> None:
        """
        Home the U (tool) axis (G28 U).
        In simulation mode, sets the U axis as homed and logs the action.
        Raises:
            JubileeHomingError: If homing the U axis fails.
        """
        if self.simulated:
            logger.debug("(SIMULATED) home U axis.")
            self.axes_homed[3] = True
            return
        try:
            self.gcode("G28 U")
            self.axes_homed[3] = True
        except Exception as e:
            logger.error(f"Homing U failed: {e}")
            raise JubileeHomingError("Failed to home U axis.") from e

    def _home_z(self) -> None:
        """
        Home the Z axis (G28 Z).
        In simulation mode, sets the Z axis as homed and logs the action.
        Raises:
            JubileeHomingError: If homing the Z axis fails.
        """
        if self.simulated:
            logger.debug("(SIMULATED) home Z axis.")
            self.axes_homed[2] = True
            return
        try:
            self.gcode("G28 Z")
            self.axes_homed[2] = True
        except Exception as e:
            logger.error(f"Homing Z failed: {e}")
            raise JubileeHomingError("Failed to home Z axis.") from e  

    def home_xyu(self) -> None:
        """
        Home the X, Y, and U axes. In simulation, just logs and sets dummy state.
        Raises:
            JubileeHomingError: If homing any axis fails.
        """
        if self.simulated:
            logger.debug("(SIMULATED) home XYU axes.")
            self.axes_homed = [True, True, True, True]
            return
        try:
            self._home_u()
            self._home_y()
            self._home_x()
            self._set_absolute_positioning()
            # Update homing status from Duet object model (avoids race condition)
            homed_status = json.loads(self.gcode('M409 K"move.axes[].homed"'))["result"]
            self.axes_homed = [True, True, homed_status[2], True]
        except Exception as e:
            logger.error(f"Homing XYU failed: {e}")
            raise JubileeHomingError("Failed to home XYU axes.") from e            
       
    @safe_homing
    def home_all(self) -> None:
        """
        Home all axes (X, Y, Z, U).
        In simulation, sets all axes as homed and logs the action.
        Raises:
            JubileeHomingError: If homing any axis fails.
        """
        if self.simulated:
            logger.debug("(SIMULATED) home all axes (XYUZ).")
            self.axes_homed = [True, True, True, True]
            return
        try:
            self.home_xyu()
            self._home_z()
            logger.info("All axes homed successfully.")
            self.axes_homed = [True, True, True, True]  # X, Y, Z, U
        except Exception as e:
            logger.error(f"Homing all axes failed: {e}")
            raise JubileeHomingError("Failed to home all axes.") from e

    def fake_home(self, *args: str, confirm: bool = False) -> None:
        """
        Dangerously set given axis positions to 0 without physical movement.
        In simulation, just logs.
        Args:
            *args (str): Axes to fake home (e.g., 'X', 'Y').
            confirm (bool): Must be True to allow this dangerous operation.
        Raises:
            RuntimeError: If confirm is not True.
        """
        if self.simulated:
            logger.debug(f"(SIMULATED) fake_home({args}, confirm={confirm}) called.")
            return
        if not confirm:
            raise RuntimeError("Dangerous operation: set confirm=True to override.")
        for axis in args:
            if axis.upper() not in ["X", "Y", "Z", "U"]:
                raise TypeError(f"Unknown axis: {axis}")
            self.gcode(f"G92 {axis.upper()}0")

    # ═══════════════════════════════════════════════════════════════════════════════
    # MOTION & POSITIONING
    # ═══════════════════════════════════════════════════════════════════════════════
    def _set_absolute_positioning(self) -> None:
        """
        Set machine to absolute positioning mode (G90). In simulation, just logs.
        """
        if self.simulated:
            logger.debug("(SIMULATED) set absolute positioning (G90).")
            self._absolute_positioning = True
            return
        self.gcode("G90")
        self._absolute_positioning = True

    def _set_relative_positioning(self) -> None:
        """
        Set relative positioning mode for all axes except extrusion (G91). In simulation, just logs.
        """
        if self.simulated:
            logger.debug("(SIMULATED) set relative positioning (G91).")
            self._absolute_positioning = False
            return
        self.gcode("G91")
        self._absolute_positioning = False

    @machine_homed
    def _move_xyzu(
        self,
        x: float = None,
        y: float = None,
        z: float = None,
        u: float = None,
        s: float = 6000,
        param: str = None,
        wait: bool = False,
    ) -> None:
        """
        Move the machine to the specified (x, y, z, u) position.
        Args:
            x (float, optional): Target X coordinate.
            y (float, optional): Target Y coordinate.
            z (float, optional): Target Z coordinate.
            u (float, optional): Target U coordinate.
            s (float, optional): Speed/feedrate.
            param (str, optional): Extra G-code parameters.
            wait (bool, optional): Wait for move to complete.
        Raises:
            JubileeStateError: If move fails or machine not homed.
        """
        if self.simulated:
            logger.debug(f"(SIMULATED) move XYZU (x={x}, y={y}, z={z}, u={u}, s={s}, param={param}, wait={wait})")
            self.gcode(f"G0 X{x} Y{y} Z{z} U{u} F{s}")
            if wait:
                self.gcode("M400")
            return
        axes = {"X": x, "Y": y, "Z": z, "U": u, "F": s}
        cmd_parts = [f"{axis}{value:.2f}" for axis, value in axes.items() if value is not None]
        if param:
            cmd_parts.append(param)
        self.gcode(f"G0 {' '.join(cmd_parts)}")
        if wait:
            self.gcode("M400")  # Wait for moves to complete

    def _check_axis_limits(self, target: dict, relative: bool = False) -> None:
        """
        Check if the target position is within axis limits.
        Args:
            target (dict): Target positions for axes.
            relative (bool): If True, target is relative to current position.
        Raises:
            JubileeConfigurationError: If target is out of bounds.
        """
        if self.simulated:
            logger.debug("(SIMULATED) _check_axis_limits() called.")
            return
        if not any(self._axis_limits):
            logger.error("Axis limits are not configured.")
            raise JubileeConfigurationError("Axis limits are not configured.")
        limits = dict(zip(("X", "Y", "Z"), self._axis_limits[:3]))
        pos = self.get_position() if relative else {}
        for axis, value in target.items():
            if value is None or axis not in limits or limits[axis] is None:
                continue
            test_value = float(pos[axis]) + value if relative else value
            if not limits[axis][0] <= test_value <= limits[axis][1]:
                kind = "Relative" if relative else "Absolute"
                logger.error(f"{kind} move exceeds {axis} axis limit ({limits[axis][0]}–{limits[axis][1]} mm)")
                raise JubileeStateError(
                    f"{kind} move exceeds {axis} axis limit ({limits[axis][0]}–{limits[axis][1]} mm)")

    def move_to(self, x=None, y=None, z=None, u=None, s=6000, param=None, wait=False):
        """Perform an absolute move to the specified X, Y, Z, U coordinates. In simulation, logs the simulated command."""
        if self.simulated:
            logger.info(f"(SIMULATED) move_to(x={x}, y={y}, z={z}, u={u}, s={s}, param={param}, wait={wait})")
            self._set_absolute_positioning()
            self._check_axis_limits({"X": x, "Y": y, "Z": z}, relative=False)
            self._move_xyzu(x=x, y=y, z=z, u=u, s=s, param=param, wait=wait)
            return
        try:
            self._set_absolute_positioning()
            self._check_axis_limits({"X": x, "Y": y, "Z": z}, relative=False)
            self._move_xyzu(x=x, y=y, z=z, u=u, s=s, param=param, wait=wait)
        except JubileeConfigurationError as e:
            logger.error(f"Configuration error during move_to: {e}")
            raise
        except JubileeStateError as e:
            logger.error(f"State error during move_to: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during move_to: {e}")
            raise

    def move(self, dx=None, dy=None, dz=None, du=None, s=6000, param=None, wait=False):
        """Perform a relative move by the specified deltas (ΔX, ΔY, etc.). In simulation, logs the simulated command."""
        if self.simulated:
            logger.info(f"(SIMULATED) move(dx={dx}, dy={dy}, dz={dz}, du={du}, s={s}, param={param}, wait={wait})")
            self._set_relative_positioning()
            self._check_axis_limits({"X": dx, "Y": dy, "Z": dz}, relative=True)
            self._move_xyzu(x=dx, y=dy, z=dz, u=du, s=s, param=param, wait=wait)
            return
        try:
            self._set_relative_positioning()
            self._check_axis_limits({"X": dx, "Y": dy, "Z": dz}, relative=True)
            self._move_xyzu(x=dx, y=dy, z=dz, u=du, s=s, param=param, wait=wait)
        except JubileeConfigurationError as e:
            logger.error(f"Configuration error during move: {e}")
            raise
        except JubileeStateError as e:
            logger.error(f"State error during move: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during move: {e}")
            raise

    def dwell(self, t: float, millis: bool = True):
        """Pauses the machine for a period of time. In simulation, just logs."""
        if self.simulated:
            logger.info(f"(SIMULATED) dwell(t={t}, millis={millis})")
            return
        param = "P" if millis else "S"
        cmd = f"G4 {param}{t}"
        self.gcode(cmd)

    # ═══════════════════════════════════════════════════════════════════════════════
    # TOOL LOCK/UNLOCK OPERATIONS (MACROS & GENERIC)
    # ═══════════════════════════════════════════════════════════════════════════════
    def tool_lock_macro(self) -> None:
        """
        Lock the currently mounted tool using the macro-based implementation.
        Raises:
            JubileeControllerError: If the macro fails or is not supported.
        """
        if self.simulated:
            logger.info(f"(SIMULATED) tool_lock_macro()")
            return
        cmd = 'M98 P"0:/macros/tool_manager/tool_lock.g"'
        self.gcode(cmd)

    def tool_unlock_macro(self) -> None:
        """
        Unlock the currently mounted tool using the macro-based implementation.
        Raises:
            JubileeControllerError: If the macro fails or is not supported.
        """
        if self.simulated:
            logger.info(f"(SIMULATED) tool_unlock_macro()")
            return
        cmd = 'M98 P"0:/macros/tool_manager/tool_unlock.g"'
        self.gcode(cmd)

    def pickup_tool_macro(self, index: int):
        """Runs Jubilee tool unlock macro for tool index between 0 and 3. In simulation, just logs."""
        if self.simulated:
            logger.info(f"(SIMULATED) pickup_tool(index={index})")
            return
        if not 0 <= index <= 3:
            logger.error(f"Invalid tool index {index} for pickup_tool_macro.")
            raise JubileeStateError("Tool index must be between 0 and 3.")
        cmd = f'M98 P"0:/macros/tool_manager/pickup_tool/pickup_tool{index}.g"'
        self.gcode(cmd)

    def park_tool_macro(self, index: int):
        """Runs Jubilee tool lock macro for tool index between 0 and 3. In simulation, just logs."""
        if self.simulated:
            logger.info(f"(SIMULATED) park_tool(index={index})")
            return
        if not 0 <= index <= 3:
            logger.error(f"Invalid tool index {index} for park_tool_macro.")
            raise JubileeStateError("Tool index must be between 0 and 3.")
        cmd = f'M98 P"0:/macros/tool_manager/park_tool/park_tool{index}.g"'
        self.gcode(cmd)
    

    def tool_lock(self) -> None:
        """
        Lock the currently mounted tool using the default implementation (macro or hardware).
        Raises:
            JubileeControllerError: If locking fails.
        """
        self.tool_lock_macro()

    def tool_unlock(self) -> None:
        """
        Unlock the currently mounted tool using the default implementation (macro or hardware).
        Raises:
            JubileeControllerError: If unlocking fails.
        """
        self.tool_unlock_macro()

    def pickup_tool_sequence(
        self,
        index: int,
        z_park: float = None,
        speed: float = 6000,
    ) -> None:
        """
        Execute the sequence to pick up a tool.
        Args:
            index (int): The ID of the tool to pick up.
            z_park (float, optional): Z position to use for parking. If None, uses default.
            speed (float, optional): Movement speed (default: 6000).
        Raises:
            JubileeControllerError: If the pickup sequence fails.
        """
        logger.info(f"Starting pickup_tool sequence for tool {index}.")
        if self.simulated:
            logger.info(f"(SIMULATED) pickup_tool_sequence(index={index}, z_park={z_park})")
            return
        if index not in self.tool_parking_positions:
            logger.error(f"No parking position defined for tool {index}.")
            raise JubileeStateError(f"No parking position defined for tool {index}.")
        pos = self.tool_parking_positions[index]
        z = z_park if z_park is not None else pos["z_park"]
        # 1. Move to approach position in front of the parking post
        self.move_to(x=pos["x_park"], y=pos["y_clear"], z=z, s=speed, wait=True)
        # 2. Move in Y to pick up the tool
        self.move_to(x=pos["x_park"], y=pos["y_park"], z=z, s=speed, wait=True)
        # 3. Mechanically lock the tool
        self.tool_lock()
        # 4. Retract to the approach position
        self.move_to(x=pos["x_park"], y=pos["y_clear"], z=z, s=speed, wait=True)
        logger.info(f"pickup_tool_sequence completed for tool {index}.")

    def park_tool_sequence(
        self,
        index: int,
        z_park: float = None,
        speed: float = 6000,
    ) -> None:
        """
        Execute the sequence to park a tool.
        Args:
            index (int): The ID of the tool to park.
            z_park (float, optional): Z position to use for parking. If None, uses default.
            speed (float, optional): Movement speed (default: 6000).
        Raises:
            JubileeControllerError: If the park sequence fails.
        """
        logger.info(f"Starting park_tool sequence for tool {index}.")
        if self.simulated:
            logger.info(f"(SIMULATED) park_tool_sequence(index={index}, z_park={z_park})")
            return
        if index not in self.tool_parking_positions:
            logger.error(f"No parking position defined for tool {index}.")
            raise JubileeStateError(f"No parking position defined for tool {index}.")
        pos = self.tool_parking_positions[index]
        z = z_park if z_park is not None else pos["z_park"]
        # 1. Move to approach position in front of the parking post
        self.move_to(x=pos["x_park"], y=pos["y_clear"], z=z, s=speed, wait=True)
        # 2. Move in Y to park the tool
        self.move_to(x=pos["x_park"], y=pos["y_park"], z=z, s=speed, wait=True)
        # 3. Mechanically unlock the tool
        self.tool_unlock()
        # 4. Retract to the approach position
        self.move_to(x=pos["x_park"], y=pos["y_clear"], z=z, s=speed, wait=True)
        logger.info(f"park_tool_sequence completed for tool {index}.")
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # STATUS READERS & PROPERTIES
    # ═══════════════════════════════════════════════════════════════════════════════
    def get_configured_axes(self):
        """Fetch and return the list of configured axis letters. In simulation, returns dummy axes."""
        if self.simulated:
            return ["X", "Y", "Z", "U"]
        axes_data = self._retry_json(lambda: self.gcode('M409 K"move.axes[]"'))["result"]
        return [axis["letter"] for axis in axes_data]

    def get_axis_limits(self):
        """Fetch and return list of (min, max) tuples for each axis. In simulation, returns dummy limits."""
        if self.simulated:
            return [(0, 200), (0, 200), (0, 200), (0, 200)]
        axes_data = self._retry_json(lambda: self.gcode('M409 K"move.axes"'))["result"]
        return [(axis["min"], axis["max"]) for axis in axes_data]

    def get_position(self):
        """
        Get the current position of the machine control point in millimeters.
        In simulation, returns dummy position.
        """
        if self.simulated:
            return {"X": 0.0, "Y": 0.0, "Z": 0.0, "U": 0.0}
        max_tries = 50
        for _ in range(max_tries):
            response = self.gcode("M114")
            if "Count" in response:
                break
            time.sleep(0.05)
        else:
            logger.error("Failed to get valid position response after max retries.")
            raise JubileeCommunicationError("Failed to get valid position response after max retries.")
        try:
            response = response.split(" Count ", 1)[0]
        except IndexError:
            logger.error("Unexpected response format, missing 'Count' keyword.")
            raise JubileeCommunicationError("Unexpected response format, missing 'Count' keyword.")
        positions = {}
        for element in response.split():
            if ":" in element:
                axis, pos_str = element.split(":", 1)
                try:
                    positions[axis] = float(pos_str)
                except ValueError:
                    logger.warning(f"Invalid position value for axis {axis}: {pos_str}")
                    positions[axis] = None
        return positions

    def get_endstops(self):
        """
        Get the state of all endstops (limit switches).
        In simulation, returns dummy states.
        """
        if self.simulated:
            return {"X": "open", "Y": "open", "Z": "open", "U": "open"}
        response = self.gcode("M119")
        states = {}
        for line in response.splitlines():
            if ":" in line:
                name, state = line.split(":", 1)
                states[name.strip()] = state.strip()
        return states

