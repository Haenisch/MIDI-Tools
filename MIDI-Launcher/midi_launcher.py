#!/usr/bin/env python3

"""Monitor MIDI messages and launch commands based on the messages received.

Written by Christoph Hänisch
Last changed on 2024-11-17
Version 1.0
"""

# The entire code base is intentionally kept in a single file for simplicity.
#
# Overall structure of the program:
#
# - First the command-line arguments are parsed in the main function.
#
# - A MIDILauncher class instance is created and run. Within the MIDILauncher
#   class instance, the configuration file is read and parsed. The configuration
#   file contains a list of commands to be launched when specific MIDI events
#   are received; these commands are stored in Command objects (see below).
#
#   Within a loop, the MIDI input ports are polled for MIDI messages, and the
#   commands are launched when the corresponding MIDI events are received. This
#   is done by passing the MIDI messages to the Command objects which in turn
#   check if the message matches the criteria specified in the config file.
#
#   Also, within the loop, the list of input ports is renewed every 5 seconds to
#   handle cases where a new MIDI device is connected or disconnected while the
#   program is running.
#
# - The Command class represents a command to launch when a specific MIDI event
#   is received. The Command objects are created based on the configuration
#   file. The Command objects have an execute method that checks if the MIDI
#   message matches the criteria specified in the configuration file and
#   launches the command if it does. The Command objects also have methods to
#   parse the channels, controls, notes, and ports fields in the configuration
#   file (see below).
#
# TODO: Refactor the code such that the Command class only holds the command
#       details/data and the MIDILauncher class is responsible for the parsing
#       and the execution logic.
#
# TODO: Add a feature to log the MIDI messages to a file.


import argparse
import re
import subprocess
import sys
import time


# Python 3.11 or later is required to run this script.
# Check the Python version before proceeding.

if sys.version_info < (3, 11):
    print("Python 3.11 or later is required to run this script.")
    sys.exit(1)

import tomllib

try:
    import mido
    from rtmidi import InvalidPortError
    mido.set_backend('mido.backends.rtmidi', load=True)
except ImportError:
    print("Please install the required dependencies by running:")
    print("pip install python-rtmidi mido[ports-rtmidi]")
    sys.exit(1)


MAJOR_VERSION_NUMBER = 1
MINOR_VERSION_NUMBER = 0
VERSION_NUMBER = f"{MAJOR_VERSION_NUMBER}.{MINOR_VERSION_NUMBER}"


###############################################################################
# Helper functions                                                            #
###############################################################################

def list_input_ports():
    """List the available MIDI input ports."""
    print("Available input ports:")
    for i, port in enumerate(mido.get_input_names()):
        print(f"{i}. {port}")


def parse_user_input(user_input:int|str|list,
                     default_range= (0, 127),
                     header_text='',
                     print_error=print,
                     print_warning=print,
                     range_separator='-'
                    ) -> list:
    """
    Parse the user input from the TOML configuration file and convert it to a
    list of numbers.
    
    Parameters:
    
      - user_input:         The user input to parse. See below for more details
                            on the supported formats.
      - default_range:      A tuple of two numbers specifying the default range
                            of numbers.
      - header_text:        A string to print before the error or warning
                            message.
      - print_error:        The function used to print the error messages.
      - print_warning:      The function used to print the warning messages.
      - range_separator:    The character used to separate the start and end of
                            a range (4..8, 4-8, 4:8, etc.).
                    
    The user input can be of type int, str, or list. The user input can contain
    single numbers, ranges of numbers, and the keyword "all". If specified as a
    string, the numbers can be separated by commas or whitespace. An empty
    string is converted to an empty list. The keyword "all" is converted to a
    list of all numbers in the range specified by the default_range parameter.
    The range_separator parameter specifies the character used to separate the
    start and end of a range.
    
    A string of the form "<start>:<end>:<step>" is interpreted as a range of
    numbers starting at <start>, ending at <end>, and increasing by <step> in
    each step. The step parameter is optional and defaults to 1. The start and
    end parameters are required.
    
    The user input can also be a mixed list of numbers and strings. The strings
    are parsed individually and the resulting lists are concatenated.
    
    Nested lists are supported and are parsed recursively.

    Examples:
    
    - 1:                [1]
    - "1, 2, 3":        [1, 2, 3]
    - "1 2 3":          [1, 2, 3]
    - "1-3":            [1, 2, 3]
    - "1-3, 5, 7-9":    [1, 2, 3, 5, 7, 8, 9]
    - "1:5:2":          [1, 3, 5]
    - "all":            [0, 1, 2, ..., 127]
    - [1]:              [1]
    - [1, 2, 3]:        [1, 2, 3]
    - [1, 2, "3-5"]:    [1, 2, 3, 4, 5]
    """

    # Check if the user input is of the correct type.
    if not isinstance(user_input, int|str|list):
        if header_text: print_error(header_text)
        print_error(f"Error parsing the input. Expected a number, a string, or a list, but got '{type(user_input)}'. Ignoring the input.\n")
        return []

    # Case: Single number
    if isinstance(user_input, int):
        # Check if the input is in the default range. Print a warning if it is not.
        if user_input < default_range[0] or user_input > default_range[1]:
            if header_text: print_warning(header_text)
            print_warning(f"Warning: Input value '{user_input}' is outside the expected range {default_range}.")
        return [user_input]

    # Case: String
    if isinstance(user_input, str):
        # Empty input string: return an empty list.
        if not user_input:
            return []

        # Input string is the keyword "all": return a list of all numbers in the
        # range specified by the default_range parameter.
        if user_input == 'all':
            return list(range(default_range[0], default_range[1] + 1))

        # Check if the input string is a comma-separated list of items. If so,
        # split the string by commas and whitespace and parse the individual
        # items by recursively calling the parse_user_input function.
        # Concatenate the resulting lists.
        resulting_list = []
        items = re.split(r',\s*|\s+', user_input)
        if len(items) > 1:
            for item in items:
                resulting_list.extend(parse_user_input(item, default_range, header_text, print_error, print_warning, range_separator))
            return resulting_list

        # Input string is a single number: convert it to an integer.
        if user_input.isdigit():
            number = int(user_input)
            # Check if the number is within the default range.
            if number < default_range[0] or number > default_range[1]:
                if header_text: print_warning(header_text)
                print_warning(f"Warning: Input value '{number}' is outside the expected range {default_range}.")
            return [number]

        # Range written in the form "<start>:<end>:<step>"
        # Regular expression to match the range where the step is optional.
        pattern = re.compile(r'(?P<start>-?\d+)\s*:\s*(?P<end>-?\d+)\s*(:\s*(?P<step>-?\d+))?')
        match = pattern.match(user_input.lower())
        if match:
            start = match.group('start')
            end = match.group('end')
            step = match.group('step')
            if step is None:
                step = 1
            # Check if the step value is zero.
            if step == 0:
                if header_text: print_error(header_text)
                print_error("Error: Step value cannot be zero. Ignoring the range.")
                return []
            # Check if the start value is greater than the end value.
            if int(start) > int(end):
                if header_text: print_error(header_text)
                print_error("Error: Start value is greater than the end value. Ignoring the range.")
                return []
            # Check if the step value is negative and reverse the start and end values.
            if int(step) < 0:
                start, end = end, start
            # Check if the start and end values are within the default range.
            if int(start) < default_range[0] or int(end) > default_range[1]:
                if header_text: print_warning(header_text)
                print_warning(f"Warning: Range '{user_input}' is outside the expected range {default_range}.")
            # Convert the start, end, and step values to integers and return the range.
            return list(range(int(start), int(end) + 1, int(step)))
        
        # Input string is a range written in the form "start-end" (or any other
        # separator): convert it to a list of numbers.
        if range_separator in user_input:
            try:
                start, end = user_input.split(range_separator)
                start = int(start)
                end = int(end)
            except ValueError:
                if header_text: print_error(header_text)
                print_error(f"Error parsing the range: '{user_input}'. Ignoring the range.")
                return []
            # Check if the start value is greater than the end value.
            if start > end:
                if header_text: print_error(header_text)
                print_error("Error: Start value is greater than the end value. Ignoring the range.")
                return []
            # Check if the start and end values are within the default range.
            if start < default_range[0] or end > default_range[1]:
                if header_text: print_warning(header_text)
                print_warning(f"Warning: Range '{start}{range_separator}{end}' is outside the expected range {default_range}.")
            return list(range(start, end + 1))

        # Could not match the input string to any of the supported formats.
        if header_text: print_error(header_text)
        print_error(f"Error parsing the input: '{user_input}'. Ignoring the input.")
        return []

    # Case: List
    # Check if the list contains strings and parse them individually.
    if isinstance(user_input, list):
        resulting_list = []
        for item in user_input:
            if isinstance(item, int):
                # Check if the item is within the default range.
                if item < default_range[0] or item > default_range[1]:
                    if header_text: print_warning(header_text)
                    print_warning(f"Warning: Input value {item} is outside the expected range {default_range}.")
                resulting_list.append(item)
            elif isinstance(item, str):
                resulting_list.extend(parse_user_input(item, default_range, header_text, print_error, print_warning, range_separator))
            elif isinstance(item, list):
                resulting_list.extend(parse_user_input(item, default_range, header_text, print_error, print_warning, range_separator))
        return resulting_list


###############################################################################
# MIDILauncher class                                                          #
###############################################################################

class MIDILauncher:
    """Monitor MIDI messages and launch commands based on the messages received."""

    def __init__(self, config_file='config.toml', verbosity_level=0, ignore_clock=False):
        self.verbosity_level = verbosity_level
        self.commands = []
        self.config_file = config_file
        self.ignore_clock = ignore_clock
        self.open_ports = self.get_input_ports()

        self.parse_config_file()


    def get_input_ports(self) -> list:
        """Get the available input ports and open them."""

        # Check for any available input ports and exit if no ports are available
        input_ports = mido.get_input_names()
        if not input_ports:
            print("No input ports available.")
            sys.exit(1)

        # Print the available input ports
        if self.verbosity_level:
            print("Available input ports:\n")
            for i, port in enumerate(input_ports):
                print(f"{i}. {port.split(':')[0]}")
            print()

        # Open all input ports
        return [mido.open_input(port_name) for port_name in input_ports]


    def parse_config_file(self):
        """Parse the configuration file."""
        if self.verbosity_level:
            print(f"Reading configuration file: {self.config_file}\n")
        try:
            with open(self.config_file, 'rb') as file:
                config = tomllib.load(file)
        except FileNotFoundError:
            print("Configuration file not found.")
            sys.exit(1)
        except tomllib.TOMLDecodeError as error:
            print(f"Error decoding configuration file: {error}")
            sys.exit(1)

        config_version = config.get('version')
        if not config_version:
            print("Error: Configuration file does not contain a version field.")
            print("Please add a version field to the configuration file.")
            sys.exit(1)
        if config_version != 1:
            print(f"Error: Unsupported configuration file version {config_version}.\n")
            print("Please update MIDI-Launcher or adapt the configuration file to\n"
                  "the version supported by this specific version of MIDI-Launcher.\n"
                  "See the help text for more information.\n"
                  "Supported version: 1.\n")
            sys.exit(1)

        # Parse the "commands" section of the configuration file and create
        # Command objects for each table in the array. If a table is empty
        # it is skipped.

        for cmd in config.get('commands', []):
            if not cmd:
                continue
            command = Command(cmd)
            self.commands.append(command)

        if self.verbosity_level:
            print(f"Found {len(self.commands)} command(s) in the configuration file.\n")
            for i, command in enumerate(self.commands, start=1):
                print(f"{i}: {command.name}")
                command.print_command_details()
                print()
            print()


    def run(self):
        print("Listening for MIDI messages...\n")

        # Poll for MIDI messages and launch the commands.

        try:
            last_update = time.time()
            while True:
                # Renew the list of input ports every 5 seconds. If any new
                # ports are added or removed, notify the user and update the
                # list of open ports. This is useful when a new MIDI device is
                # connected or disconnected while the program is running. Handle
                # InvalidPortError exceptions when updating the list of open
                # ports.
                if time.time() - last_update > 5:
                    try:
                        input_ports = mido.get_input_names()
                    except InvalidPortError as error:
                        print(f"\nError updating the list of input ports: {error}")
                        continue
                    if input_ports != [port.name for port in self.open_ports]:
                        print("\nInput ports have changed. Updating the list of open ports.")
                        self.open_ports = self.get_input_ports()
                        last_update = time.time()

                # Poll the open ports for MIDI messages and launch the commands.
                for port in self.open_ports:
                    for message in port.iter_pending():
                        if self.ignore_clock and message.type == 'clock':
                            continue
                        if self.verbosity_level >= 2:
                            print(f"\n{port.name.split(':')[0]}: {message}")
                        for command in self.commands:
                            command.execute(message, port.name,
                            verbosity_level=self.verbosity_level)

                # Sleep for a short time to avoid using too much CPU time.
                time.sleep(0.01)
        except KeyboardInterrupt:
            time.sleep(0.1)


###############################################################################
# Command class                                                               #
###############################################################################

class Command:
    """A class to represent a command to launch when a specific MIDI event is received."""

    def __init__(self, config):
        self.active = config.get('active', True)
        self.channels = config.get('channels', 'all')
        self.command = config.get('command')
        self.control = config.get('control', 'all')
        self.event = config.get('event')
        self.mapping = config.get('mapping', [0, 127])
        self.name = config.get('name')
        self.note = config.get('note', 'all')
        self.ports = config.get('ports', 'all')
        self.values = config.get('values', 'all')
        self.velocities = config.get('velocities', 'all')

        # Check for valid event type.
        try:
            event_type = str(self.event)
        except ValueError:
            print(f"Error: Invalid event type '{self.event}'. Ignoring the command.")
            self.active = False
            return
        if event_type.lower() not in ('note_on', 'note_off', 'control_change'):
            print("Error: Invalid event type '{self.event}'. Ignoring the command.")
            self.active = False
            return

        self.parse_channels()
        self.parse_controls()
        self.parse_mapping()
        self.parse_notes()
        self.parse_ports()
        self.parse_values()
        self.parse_velocities()


    def execute(self, message, port_name, verbosity_level=0):
        """Execute the command if the message matches the command criteria.
        
        Parameters:
          - message: The MIDI message to check against the command criteria.
          - port_name: The name of the port that received the message.
          - verbose: A boolean flag to print debug messages to the console.
        """

        if not self.active:
            if verbosity_level >= 2:
                print(f"Command '{self.name}' is not active.")
            return

        if self.event != message.type:
            if verbosity_level >= 2:
                print(f"Command '{self.name}' does not match the message type.")
            return

        # Check if the current port name matches the stored port field. Matching
        # is done partially and case-insensitively.
        port_name_matches = [port in port_name.lower() for port in self.ports]
        if self.ports != ['all'] and not any(port_name_matches):
            if verbosity_level >= 2:
                print(f"Command '{self.name}' does not match the port.")
            return

        channel = message.channel + 1  # MIDI channels are numbered from 0 to 15.
        if channel not in self.channels:
            if verbosity_level >= 2:
                print(f"Command '{self.name}' does not match the channel.")
            return

        value = 0
        if self.event in ('note_on', 'note_off'):
            if self.note != 'all' and message.note not in self.note:
                if verbosity_level >= 2:
                    print(f"Command '{self.name}' does not match the note.")
                return
            if message.velocity not in self.velocities:
                if verbosity_level >= 2:
                    print(f"Command '{self.name}' does not match the velocity.")
                return
            value = message.velocity
        elif self.event == 'control_change':
            if message.control not in self.control:
                if verbosity_level >= 2:
                    print(f"Command '{self.name}' does not match the control.")
                return
            if message.value not in self.values:
                if verbosity_level >= 2:
                    print(f"Command '{self.name}' does not match the value.")
                return
            value = message.value
        percentage = round(value / 127 * 100)  # Convert the value to a percentage between 0 and 100.
        decimal = round(self.mapping[0] + value / 127 * (self.mapping[1] - self.mapping[0]), 2)  # Map the value to the range specified in the mapping field.

        # Subsitute the placeholders $VELOCITY, $VALUE, $PERCENTAGE, and $DECIMAL with the above values.
        command = self.command.replace('$VELOCITY', str(value))
        command = command.replace('$VALUE', str(value))
        command = command.replace('$PERCENTAGE', str(percentage))
        command = command.replace('$DECIMAL', str(decimal))

        # Launch the command
        if verbosity_level:
            print(f"Executing command '{self.name}': {command}")
        subprocess.run(command, shell=True, check=False)


    def parse_channels(self):
        """ Parse the channels field and overwrite it with a list of channel numbers."""
        self.channels = parse_user_input(self.channels, default_range=(1, 16), header_text=f"Command (channels field): {self.name}\n")


    def parse_controls(self):
        """ Parse the control field and overwrite it with a list of control numbers."""
        self.control = parse_user_input(self.control, default_range=(0, 127), header_text=f"Command (controls field): {self.name}\n")


    def parse_mapping(self):
        """ Parse the mapping field and overwrite it with a list of two numbers."""

        # Parsing is done according to the following rules:
        # - A list of two numbers is left as is; all other lists are ignored
        #   and the mapping field is set to [0, 127].
        # - A string is converted to a list of two numbers; an invalid string
        #   is ignored and the mapping field is set to [0, 127].
        # - The keyword "all" is converted to [0, 127].

        if isinstance(self.mapping, list):
            if len(self.mapping) == 2:
                return
            else:
                print(f"Command: {self.name}")
                print(f"Error parsing the mapping field: '{self.mapping}'. Ignoring the mapping field.\n")
                self.mapping = [0, 127]
                return
        elif isinstance(self.mapping, str):
            if self.mapping == 'all':
                self.mapping = [0, 127]
                return
            try:
                self.mapping = [float(item) for item in self.mapping.split(',')]
            except ValueError:
                print(f"Command: {self.name}")
                print(f"Error parsing the mapping field: '{self.mapping}'. Ignoring the mapping field.\n")
                return
            if len(self.mapping) != 2:
                self.mapping = [0, 127]
                print(f"Command: {self.name}")
                print(f"Error parsing the mapping field: '{self.mapping}'. Ignoring the mapping field.\n")
                return

            
    def parse_notes(self):
        """ Parse the note field and overwrite it with a list of note numbers."""
        self.note = parse_user_input(self.note, default_range=(0, 127), header_text=f"Command (note field): {self.name}\n")


    def parse_ports(self):
        """ Parse the ports field and overwrite it with a list of port names."""

        # Port names are stored lowercase to make matching case-insensitive.
        # Parsing is done according to the following rules:
        # - The keyword "all" is converted to a list.
        # - A single port name (string) is converted to a list containing that name.
        # - A list of port names is left as is.

        if self.ports == '':
            print(f"Command: {self.name}")
            print("Warning: Empty 'ports' field matches all ports.\n")
        if self.ports == 'all':
            self.ports = ['all']
        if isinstance(self.ports, str):
            self.ports = [self.ports.lower()]
        if isinstance(self.ports, list):
            self.ports = [port.lower() for port in self.ports]


    def parse_values(self):
        """ Parse the values field and overwrite it with a list of values."""
        self.values = parse_user_input(self.values, default_range=(0, 127), header_text=f"Command (values field): {self.name}\n")


    def parse_velocities(self):
        """ Parse the velocities field and overwrite it with a list of velocities."""
        self.velocities = parse_user_input(self.velocities, default_range=(0, 127), header_text=f"Command (velocities field): {self.name}\n")

    def print_command_details(self):
        """Print the details of the command."""
        print(f"   Active: {self.active}")
        print(f"   Channels: {self.channels}")
        print(f"   Command: {self.command}")
        if self.event == 'control_change':
            # Control numbers
            if len(self.control) > 16:
                print(f"   Controls: {self.control[:16]} (truncated)")
            else:  
                print(f"   Controls: {self.control[:16]}")
            print(f"   Event: {self.event}")
            # Values
            if len(self.values) > 16:
                print(f"   Values: {self.values[:16]} (truncated)")
            else:
                print(f"   Values: {self.values[:16]}")
        if self.event == 'note_on' or self.event == 'note_off':
            # Notes
            if len(self.note) > 16:
                print(f"   Notes: {self.note[:16]} (truncated)")
            else:
                print(f"   Notes: {self.note[:16]}")
            # Velocities
            if len(self.velocities) > 16:
                print(f"   Velocities: {self.velocities[:16]} (truncated)")
            else:
                print(f"   Velocities: {self.velocities[:16]}")
        print(f"   Ports: {self.ports}")


###############################################################################
# Configuration file parsing                                                  #
############################################################################### 

config_file_help_text = """
The configuration file uses the TOML format. The configuration file consists of
a version field that specifies the version of the configuration file format and
one or more command sections that define the commands to launch when specific
MIDI events are received.

The command sections are launched in the order they appear in the configuration
file. They must be given as an array of tables called "commands".

The command sections contain the following fields:

    active:     A boolean value that specifies whether the command is active. If
                this field is set to false, the command will not be launched.
                This field is optional and defaults to true.

    channels:   The MIDI channels (1-16) to listen for. This field is optional
                and defaults to "all". The syntax of this field is the same as
                for the values field (see below).

    command:    The command to be launched when the specified MIDI event is
                received. It must be given as a string. The command string can
                contain one or more of the following placeholders which will be
                replaced before the command is executed:
                
                  - $VALUE: The value of the MIDI message.
                  - $VELOCITY: The velocity of the MIDI message.
                  - $PERCENTAGE: The value of the MIDI message as a percentage
                    between 0 and 100 as an integer number.
                  - $DECIMAL: The value of the MIDI message as a decimal number
                    with two decimal places between 0 and 1. If the mapping
                    field is present, the value will be mapped to the range
                    specified in the mapping field.
                                    
                This field is required.

    control:    The control number to listen for when the event field is set to
                "control_change". This field is optional and defaults to "all".
                The syntax of this field is the same as for the values field
                (see below).

    event:      The type of MIDI event to listen for. Valid values are
                note_on", "note_off", and "control_change". This field is
                required.

    mapping:    A list of two numbers [start, end] that specify the range to map
                the value of the MIDI message to. This only affects the $DECIMAL
                placeholder in the command field. This field is optional.

    name:       A descriptive name for the command. This field is optional.

    note:       The note number to listen for when the event field is set to
                "note_on" or "note_off". This field is optional and defaults to
                "all". The syntax of this field is the same as for the values
                field (see below).

    ports:      The MIDI input ports to listen for. Valid values are a single
                port name, a list of port names, or the keyword "all". Port
                names are matched partially, so a substring of the full port
                name can be used. For example, "nanoPAD" will match "nanoPAD2"
                and "nanoPAD4". Matching is also case-insensitive. If the
                keyword "all" is used, the command will listen to all available
                input ports which is the default behavior.
                
                Examples:
                  - "nanoPAD"
                  - ["nanoPAD", "nanoKEY"]
              
    values:     A set of values that the MIDI message must match in order for
                the command to be launched. This field is optional and defaults
                to "all". This field is only used for the "control_change" event
                type.
                
                Syntax of this field
                
                The field can be provided as a single value, a list of values, a
                range of values, the keyword "all", or combinations of these. If
                specified as a string, the numbers can be separated by commas or
                whitespace. An empty string is converted to an empty set of
                values. The keyword "all" is a shortcut for all values in the
                range 0 to 127.
    
                A string of the form "<start>:<end>:<step>" is interpreted as a
                range of numbers starting at <start>, ending at <end>, and
                increasing by <step> in each step. The step parameter is
                optional and defaults to 1. The start and end parameters are
                required.

                Examples:
                  - 1                   [1]
                  - "1, 2, 3"           [1, 2, 3]
                  - "1 2 3"             [1, 2, 3]
                  - "1-3"               [1, 2, 3]
                  - "1-3, 5, 7:9"       [1, 2, 3, 5, 7, 8, 9]
                  - "1:5:2"             [1, 3, 5]
                  - "all"               [0, 1, 2, ..., 127]
                  - [1]                 [1]
                  - [1, 2, 3]           [1, 2, 3]
                  - [1, 2, "3-5"]       [1, 2, 3, 4, 5]

    velocities: A single velocity or a list of velocities that the MIDI message
                must match in order for the command to be launched. This field
                is optional and defaults to "all". This field is only used for
                the "note_on" and "note_off" event types. For the syntax of this
                field, see the values field above.


Example configuration file:

# MIDI Launcher - Configuration File

version = 1

[[commands]]
name = "example"
event = "note_on"
note = [64, 65, 66]
command = "echo 'Note on received: $VALUE'"

[[commands]]
name = "set volume"
command = "pactl set-sink-volume @DEFAULT_SINK@ $VALUE"
event = "control_change"
control = 70
ports = "LPD8"
"""


class CustomHelpFormatter(argparse.HelpFormatter):
    def __init__(self, *args, **kwargs):
        # Set the width of the options column
        kwargs['max_help_position'] = 35
        super().__init__(*args, **kwargs)


def parse_arguments():
    """Parse the command-line arguments."""
    parser = argparse.ArgumentParser(description="Monitor MIDI messages and launch commands based on the messages received.",
                                     add_help=False,
                                     formatter_class=CustomHelpFormatter)

    parser.add_argument("-c", "--config-file",
                        nargs=1,
                        default="config.toml",
                        help="Specify the configuration file to use.",
                        metavar="FILE")
    parser.add_argument("-h", "--help",
                        action="help",
                        help="Show this help message and exit.")
    parser.add_argument("-H", "--config-file-help",
                        action="store_true",
                        help="Show help for the configuration file.")
    parser.add_argument("-i", "--ignore-clock",
                        action="store_true",
                        help="Ignore MIDI clock messages.")
    parser.add_argument("-l", "--list-ports",
                        action="store_true",
                        help="List the available MIDI input ports and exit.")
    parser.add_argument("-V", "--verbose",
                        action="count",
                        default=0,
                        help="Print status and debug messages to the console. "
                             "Use multiple times for more verbosity.")
    parser.add_argument("-v", "--version",
                        action="version",
                        version="",  # f"MIDI Launcher v{VERSION_NUMBER}",
                        help="Show the version number and exit.")

    return parser.parse_args()



###############################################################################
# Main function                                                               #
###############################################################################

def main():
    print(f"MIDI Launcher v{VERSION_NUMBER}\n")

    # Parse the command-line arguments
    if len(sys.argv) == 1:
        print("No arguments provided. Use the --help option for more information.\n")
    args = parse_arguments()
    if args.config_file_help:
        print(config_file_help_text)
        sys.exit(0)
    if args.list_ports:
        list_input_ports()
        sys.exit(0)
    if isinstance(args.config_file, list):
        args.config_file = args.config_file[0]

    # Create the MIDILauncher object and run it
    executor = MIDILauncher(config_file=args.config_file,
                            verbosity_level=args.verbose,
                            ignore_clock=args.ignore_clock)
    executor.run()


if __name__ == "__main__":
    main()
