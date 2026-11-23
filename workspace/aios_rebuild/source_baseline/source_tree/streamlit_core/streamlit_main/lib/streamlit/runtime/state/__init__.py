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


from streamlit.runtime.state.common import WidgetArgs, WidgetCallback, WidgetKwargs
from streamlit.runtime.state.query_params_proxy import QueryParamsProxy
from streamlit.runtime.state.safe_session_state import SafeSessionState
from streamlit.runtime.state.session_state import (
    SCRIPT_RUN_WITHOUT_ERRORS_KEY,
    SessionState,
    SessionStateStatProvider,
)
from streamlit.runtime.state.session_state_proxy import (
    SessionStateProxy,
    get_session_state,
)
from streamlit.runtime.state.widgets import register_widget

__all__ = [
    "SCRIPT_RUN_WITHOUT_ERRORS_KEY",
    "QueryParamsProxy",
    "SafeSessionState",
    "SessionState",
    "SessionStateProxy",
    "SessionStateStatProvider",
    "WidgetArgs",
    "WidgetCallback",
    "WidgetKwargs",
    "get_session_state",
    "register_widget",
]
