"""Unit test for MIDI-Launcher."""

import os
import sys

import unittest
from unittest import TestCase

# Add the parent directory to the path to allow importing the module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from midi_launcher import parse_user_input


class TestParseUserInput(TestCase):
    """Test the parse_user_input function for various inputs."""

    def test_string_input(self):
        """Test the parse_user_input function."""

        # A single number
        self.assertEqual(parse_user_input(1), [1])

        # Strings
        self.assertEqual(parse_user_input(''), [])
        self.assertEqual(parse_user_input('1'), [1])
        self.assertEqual(parse_user_input('1, 2, 3'), [1, 2, 3])
        self.assertEqual(parse_user_input('1 2 3'), [1, 2, 3])
        self.assertEqual(parse_user_input('1-4'), [1, 2, 3, 4])
        self.assertEqual(parse_user_input('1:4'), [1, 2, 3, 4])
        self.assertEqual(parse_user_input('1:4:1'), [1, 2, 3,4])
        self.assertEqual(parse_user_input('1:4:2'), [1, 3])
        self.assertEqual(parse_user_input('all', default_range=(1,4)), [1, 2, 3, 4])

        # Lists
        self.assertEqual(parse_user_input([1]), [1])
        self.assertEqual(parse_user_input([1, 2, 3]), [1, 2, 3])

        # Comninations
        self.assertEqual(parse_user_input([1, '2:4', 3]), [1, 2, 3, 4, 3])
        self.assertEqual(parse_user_input(['all'], default_range=(1,4)), [1, 2, 3, 4])
        self.assertEqual(parse_user_input([1, 'all', 3], default_range=(1,4)), [1, 1, 2, 3, 4, 3])

        # Nesting
        self.assertEqual(parse_user_input([1, [2, 3]]), [1, 2, 3])


if __name__ == '__main__':
    unittest.main()
