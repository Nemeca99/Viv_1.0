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


import streamlit as st
from streamlit.proto.Empty_pb2 import Empty as EmptyProto
from tests.delta_generator_test_case import DeltaGeneratorTestCase


class StEmptyAPITest(DeltaGeneratorTestCase):
    """Test Public Streamlit Public APIs."""

    def test_st_empty(self):
        """Test st.empty."""
        st.empty()

        el = self.get_delta_from_queue().new_element
        assert el.empty == EmptyProto()
