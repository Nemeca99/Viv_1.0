#!/usr/bin/env python3
# Copyright (c) Streamlit Inc. (2018-2022) Snowflake Inc. (2022-2025)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# CRITICAL: Import Unicode safety layer FIRST to prevent encoding errors
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
from utils.unicode_safe_output import setup_unicode_safe_output
setup_unicode_safe_output()


"""
Functions used in ../exception_test.py.

These functions live here because when they throw an exception the stack trace
needs to arise from a separate folder.
"""

import streamlit as st


def st_call_with_arguments_missing():
    """Throws an exception that comes from Streamlit."""
    st.text()  # type: ignore


def st_call_with_bad_arguments():
    """Throws an exception that doesn't come from Streamlit."""
    st.image("does not exist")


def pandas_call_with_bad_arguments():
    """Throws an exception from Pandas."""
    import pandas as pd

    pd.DataFrame("nope!")  # type: ignore


def internal_python_call_with_bad_arguments():
    """Throws an exception from an internal Python thing."""
    import os

    os.path.realpath(42)  # type: ignore
