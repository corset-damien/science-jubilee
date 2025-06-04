import json
import time
import logging
from functools import wraps

import requests
from requests.adapters import HTTPAdapter, Retry

# ═══════════════════════════════════════════════════════════════════════════════
# EXCEPTIONS
# ═══════════════════════════════════════════════════════════════════════════════

class MachineConfigurationError(Exception):
    """Raise this error if there is something wrong with how the machine is configured"""
    pass


class MachineStateError(Exception):
    """Raise this error if the machine is in the wrong state to perform the requested action."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# DECORATORS
# ═══════════════════════════════════════════════════════════════════════════════

def machine_homed(func):
    """Decorator used to check if the machine is homed before performing certain actions."""

    @wraps(func)
    def homing_check(self, *args, **kwds):
        if self.simulated:
            return func(self, *args, **kwds)
        if self.axes_homed and all(self.axes_homed):
            return func(self, *args, **kwds)
        self.axes_homed = json.loads(self.gcode('M409 K"move.axes[].homed"'))["result"]
        if not all(self.axes_homed):
            raise MachineStateError("Error: machine must first be homed.")
        return func(self, *args, **kwds)

    return homing_check

def safe_homing(func):
    """
    Decorator to always prompt before homing.
    If a tool is mounted, asks if the user is ready to remove it.
    If not, aborts the homing. Otherwise, ensures the deck is clear.
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):

        response = input("Is there a tool currently mounted? [y/n] ")
        if response.lower() in ["y", "Y", "yes"]:
            confirm = input("Are you ready to remove it now? [y/n] ")
            if confirm.lower() not in ["y", "Y", "yes"]:
                print("Homing aborted. Please remove the tool first.")
                return
            else:
                self.tool_unlock()
                print("Waiting 5 seconds before next action...")
                self.dwell(t=5,millis=False)
                print("Resuming homing process")
        else:
            response = input("Is the deck free of obstacles? [y/n] ")
            if response.lower() not in ["y", "Y", "yes"]:
                print("Please clear the deck before homing the Z axis.")

        return func(self, *args, **kwargs)

    return wrapper


# ═══════════════════════════════════════════════════════════════════════════════
# CLASS JubileeController 
# ═══════════════════════════════════════════════════════════════════════════════

class JubileeController:
    """
    Low-level controller for a Jubilee machine. Provides direct G-code communication,
    status polling, and machine configuration.
    """

    LOCALHOST = "192.168.1.2"

    def __init__(
        self,
        port: str = None,
        baudrate: int = 115200,
        address: str = LOCALHOST,
        simulated: bool = False,
        crash_detection: bool = False,
        crash_handler=None,
    ):
        """
        Initialize the JubileeController.

        :param port: Optional serial port for future use.
        :param baudrate: Baudrate for serial connection (unused).
        :param address: IP address of the machine (default: LOCALHOST).
        :param simulated: If True, G-code commands are printed instead of sent.
        :param crash_detection: If True, detects and handles tool crash events.
        :param crash_handler: Callback to invoke on crash.
        """
        self.ser = None
        self.port = port
        self.baudrate = baudrate
        self.address = address
        self.simulated = simulated

        self.crash_detection = crash_detection
        self.crash_handler = crash_handler

        self._absolute_positioning = True
        self._configured_axes = None
        self._axis_limits = None
        self.axes_homed = [False] * 4  # Default: X/Y/Z/U axes
        
        # PAS ENCORE FAIT
        self._active_tool_index = None
        self._tool_z_offsets = None

        self.session = self._create_requests_session()

        if self.address != self.LOCALHOST:
            print("Warning: disconnecting this application from the network will halt connection to Jubilee.")

        if not self.simulated:
            self.connect()
            self._set_absolute_positioning()

    def _create_requests_session(self):
        session = requests.Session()
        retries = Retry(total=5, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])
        session.mount("http://", HTTPAdapter(max_retries=retries))
        session.headers["Connection"] = "close"
        return session

    def _retry_json(self, func, max_tries=50):
        """Retry a function returning JSON until success or max tries."""
        for _ in range(max_tries):
            try:
                result = json.loads(func())
                if result.get("result"):
                    return result
            except Exception:
                time.sleep(0.1)
        raise TimeoutError("Max retries exceeded for JSON command.")

    def _delay_time(self, n):
        if n < 10:
            return 0.1
        elif n < 20:
            return 0.2
        elif n < 30:
            return 0.3
        else:
            return 1.0

    def connect(self):
        """Attempt to connect to the machine and cache state values."""
        try:
            self.axes_homed = self._retry_json(lambda: self.gcode("M409 K\"move.axes[].homed\""))["result"][:4]
            self._configured_axes = None
            self._axis_limits = None
            self._active_tool_index = None
            self._tool_z_offsets = None
            _ = self.configured_axes
            _ = self.axis_limits
            self._set_absolute_positioning()
        except Exception as e:
            raise RuntimeError("Failed to connect to Jubilee.") from e

    def disconnect(self):
        """Close the connection."""
        # Nothing to do?
        pass

    def reset(self):
        """Issue a software reset."""
        # End the subscribe thread first.
        self.gcode("M999")  # Issue a board reset. Assumes we are already connected
        self.axes_homed = [False] * 4
        self.disconnect()
        print("Reconnecting...")
        for i in range(10):
            time.sleep(1)
            try:
                self.connect()
                return
            except MachineStateError as e:
                pass
        raise MachineStateError("Reconnecting failed.")
   
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.disconnect()

    def download_file(self, filepath: str = None, timeout: float = None):
        """Download a file into a file object. Full machine filepath must be specified.
        Example: /sys/tfree0.g

        :param filepath: The full filepath of the file to download, defaults to None
        :type filepath: str, optional
        :param timeout: The time to wait for a response from the machine, defaults to None
        :type timeout: float, optional
        :return: The file contents
        :rtype: file object
        """
        # RRF3 Only
        file_contents = requests.get(f"http://{self.address}/rr_download?name={filepath}", timeout=timeout)
        return file_contents

        
# ═══════════════════════════════════════════════════════════════════════════════
# PROPERTIES (STATE ACCESSORS)
# ═══════════════════════════════════════════════════════════════════════════════    

    @property
    def configured_axes(self):
        """Return list of configured axis letters, e.g., ['X', 'Y', 'Z', 'U']"""
        if self._configured_axes is None:
            axes_data = self._retry_json(lambda: self.gcode("M409 K\"move.axes[]\""))["result"]
            self._configured_axes = [axis["letter"] for axis in axes_data]
        return self._configured_axes

    @property
    def axis_limits(self):
        """Return list of (min, max) tuples for each axis."""
        if self._axis_limits is None:
            axes_data = self._retry_json(lambda: self.gcode("M409 K\"move.axes\""))["result"]
            self._axis_limits = [(axis["min"], axis["max"]) for axis in axes_data]
        return self._axis_limits

    @property
    def position(self):
        return self.get_position()
  
    @property
    def endstops(self):
        return self.get_endstops()


# ═══════════════════════════════════════════════════════════════════════════════
# COMMUNICATION METHODS (G-CODE SEND/RECEIVE)
# ═══════════════════════════════════════════════════════════════════════════════

    def gcode(self, cmd: str, timeout: float = None, response_wait: float = 60) -> str:
        """Send a G-code command and return the response."""
        if self.simulated:
            print(f"[SIMULATED] G-code: {cmd}")
            return ""

        try:
            response = requests.post(f"http://{self.address}/machine/code", data=cmd, timeout=timeout).text
            if "rejected" not in response:
                return response
        except requests.RequestException:
            pass  # Fallback to rr_gcode method below

        try:
            reply_count = self.session.get(f"http://{self.address}/rr_model?key=seqs").json()["result"]["reply"]
            self.session.get(f"http://{self.address}/rr_gcode?gcode={cmd}", timeout=timeout)
            tic = time.time()
            while True:
                new_count = self.session.get(f"http://{self.address}/rr_model?key=seqs").json()["result"]["reply"]
                if new_count != reply_count:
                    response = self.session.get(f"http://{self.address}/rr_reply").text
                    if self.crash_detection and "crash detected" in response:
                        logging.error("Crash detected")
                        if self.crash_handler:
                            self.crash_handler.handle_crash()
                    return response
                if time.time() - tic > response_wait:
                    return ""
                time.sleep(self._delay_time(int((time.time() - tic) * 10)))
        except Exception as e:
            logging.warning(f"G-code communication failed: {e}")
            return ""

    def push_machine_state(self):
        """Push machine state onto a stack"""
        self.gcode("M120")

    def pop_machine_state(self):
        """Recover previous machine state"""
        self.gcode("M121")


# ═══════════════════════════════════════════════════════════════════════════════
# POSITIONING MODES (ABSOLUTE / RELATIVE)
# ═══════════════════════════════════════════════════════════════════════════════

    def _set_absolute_positioning(self):
        """Set machine to absolute positioning mode (G90)."""
        self.gcode("G90")
        self._absolute_positioning = True

    def _set_relative_positioning(self):
        """Set relative positioning mode for all axes except extrusion (G91)."""
        self.gcode("G91")
        self._absolute_positioning = False

# ═══════════════════════════════════════════════════════════════════════════════
# HOMING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

    def _home_x(self):
        """Home the X axis (G28 X)."""
        self.gcode("G28 X")

    def _home_y(self):
        """Home the Y axis (G28 Y)."""
        self.gcode("G28 Y")
        
    def _home_u(self):
        """Home the U (tool) axis (G28 U)."""
        self.gcode("G28 U")

    def home_xyu(self):
        """
        Home the XYU axes.
        Home U and Y before X to avoid potential collisions with the tool rack.
        """
        self._home_u()
        self._home_y()
        self._home_x()
        self._set_absolute_positioning()

        # Update homing status from Duet object model (avoids race condition)
        homed_status = json.loads(self.gcode('M409 K"move.axes[].homed"'))["result"]
        self.axes_homed = [True, True, homed_status[2], True]

    def _home_z(self, force=False):
        """Home the Z axis (G28 Z)."""
        self.gcode("G28 Z")

    @safe_homing
    def home_all(self):
        """Home all axes (XYUZ)."""
        self.home_xyu()
        self._home_z()
        self.axes_homed = [True, True, True, True]  # X, Y, Z, U

    def fake_home(self, *args: str, confirm=False):
        """
        Dangerously set given axis positions to 0 without physical movement.
        Use with extreme caution and only if you know what you're doing.
        """
        if not confirm:
            raise RuntimeError("Dangerous operation: set confirm=True to override.")
        for axis in args:
            if axis.upper() not in ["X", "Y", "Z", "U"]:
                raise TypeError(f"Unknown axis: {axis}")
            self.gcode(f"G92 {axis.upper()}0")

# ═══════════════════════════════════════════════════════════════════════════════
# LOW-LEVEL MOTION CONTROL
# ═══════════════════════════════════════════════════════════════════════════════

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
    ):
        """
        Move X, Y, Z, and U axes. Use G0 motion command.
        Positioning mode (absolute/relative) must be set beforehand.
        """
        axes = {"X": x, "Y": y, "Z": z, "U": u, "F": s}
        cmd_parts = [f"{axis}{value:.2f}" for axis, value in axes.items() if value is not None]

        if param:
            cmd_parts.append(param)

        self.gcode(f"G0 {' '.join(cmd_parts)}")

        if wait:
            self.gcode("M400")  # Wait for moves to complete

    def _check_axis_limits(self, target: dict, relative=False):
        """
        Check if target positions are within allowed axis limits.
        Works in both absolute and relative positioning.
        """
        if not any(self._axis_limits):
            return  # No limits defined

        limits = dict(zip(("X", "Y", "Z"), self._axis_limits[:3]))
        pos = self.get_position() if relative else {}

        for axis, value in target.items():
            if value is None or axis not in limits or limits[axis] is None:
                continue

            test_value = float(pos[axis]) + value if relative else value
            if not limits[axis][0] <= test_value <= limits[axis][1]:
                kind = "Relative" if relative else "Absolute"
                raise MachineStateError(
                    f"{kind} move exceeds {axis} axis limit ({limits[axis][0]}–{limits[axis][1]} mm)"
                )

    def move_to(self, x=None, y=None, z=None, u=None, s=6000, param=None, wait=False):
        """Perform an absolute move to the specified X, Y, Z, U coordinates."""
        self._set_absolute_positioning()
        self._check_axis_limits({"X": x, "Y": y, "Z": z}, relative=False)
        self._move_xyzu(x=x, y=y, z=z, u=u, s=s, param=param, wait=wait)

    def move(self, dx=None, dy=None, dz=None, du=None, s=6000, param=None, wait=False):
        """Perform a relative move by the specified deltas (ΔX, ΔY, etc.)."""
        self._set_relative_positioning()
        self._check_axis_limits({"X": dx, "Y": dy, "Z": dz}, relative=True)
        self._move_xyzu(x=dx, y=dy, z=dz, u=du, s=s, param=param, wait=wait)

    def dwell(self, t: float, millis: bool = True):
        """Pauses the machine for a period of time.
        :param t: time to pause, in milliseconds by default
        :type t: float
        :param millis: boolean, set to false to use seconds. default unit is milliseconds.
        :type millis: bool, optional
        """
        param = "P" if millis else "S"
        cmd = f"G4 {param}{t}"
        self.gcode(cmd)


# ═══════════════════════════════════════════════════════════════════════════════
# MACHINE STATUS READERS
# ═══════════════════════════════════════════════════════════════════════════════

    def get_position(self):
        """
        Get the current position of the machine control point in millimeters.
        :return: A dictionary with axis names as keys (e.g. 'X') and positions as floats.
        :rtype: dict
        """
        max_tries = 50
        response = ""
        for _ in range(max_tries):
            response = self.gcode("M114")
            if "Count" in response:
                break
            time.sleep(0.05)  # Small delay to avoid spamming the machine with requests
        else:
            # If after max_tries the valid response is not received, raise an error
            raise TimeoutError("Failed to get valid position response after max retries.")

        keyword = " Count "
        keyword_index = response.find(keyword)

        if keyword_index == -1:
            raise ValueError("Unexpected response format, missing 'Count' keyword.")

        # Trim the response up to the keyword
        response = response[:keyword_index]
        position_elements = response.split()

        positions = {}
        for element in position_elements:
            if ":" in element:
                axis, pos_str = element.split(":", 1)
                try:
                    positions[axis] = float(pos_str)
                except ValueError:
                    positions[axis] = None  # Handle or log invalid values as needed

        return positions

    def get_endstops(self):
        """
        Get the state of all endstops (limit switches).
        :return: Dict with endstop names and their states (e.g. 'open', 'triggered').
        """
        response = self.gcode("M119")
        states = {}
        for line in response.splitlines():
            if ":" in line:
                name, state = line.split(":", 1)
                states[name.strip()] = state.strip()
        return states

   
# ═══════════════════════════════════════════════════════════════════════════════
# MACROS:
# ═══════════════════════════════════════════════════════════════════════════════

    def tool_lock(self):
        """Runs Jubilee tool lock macro. Assumes tool_lock.g macro exists."""
        cmd = 'M98 P"0:/macros/tool_manager/tool_lock.g"'
        self.gcode(cmd)

    def tool_unlock(self):
        """Runs Jubilee tool unlock macro. Assumes tool_unlock.g macro exists."""
        cmd = 'M98 P"0:/macros/tool_manager/tool_unlock.g"'
        self.gcode(cmd)
    
    def pickup_tool(self, index: int):
        """Runs Jubilee tool unlock macro for tool index between 0 and 3."""
        if not 0 <= index <= 3:
            raise ValueError("Tool index must be between 0 and 3.")
        cmd = f'M98 P"0:/macros/tool_manager/pickup_tool/pickup_tool{index}.g"'
        self.gcode(cmd)

    def park_tool(self, index: int):
        """Runs Jubilee tool lock macro for tool index between 0 and 3."""
        if not 0 <= index <= 3:
            raise ValueError("Tool index must be between 0 and 3.")
        cmd = f'M98 P"0:/macros/tool_manager/park_tool/park_tool{index}.g"'
        self.gcode(cmd)
