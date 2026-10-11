"""Smoke test of the deployed app: `pytest -m cloud` (~30 s).

Talks to the Streamlit websocket like a browser would. Read-only: no login and
no account changes. Set EZDRAFT_URL to test another deployment.
"""
import asyncio
import datetime
import os
import re
import urllib.request

import pyarrow as pa
import pytest
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from tornado.httpclient import HTTPRequest
from tornado.websocket import websocket_connect

pytestmark = pytest.mark.cloud

URL = os.environ.get("EZDRAFT_URL", "https://ezdraft-k43yu4qsya-ew.a.run.app")
ERROR, INFO, SUCCESS = 1, 3, 4  # Alert.Format


class Session:
    """One browser tab: each run() sends a rerun and collects what the script rendered."""

    def __init__(self, ws):
        self.ws, self.cache, self.widgets = ws, {}, {}

    async def run(self, widget_states=()):
        msg = BackMsg()
        msg.rerun_script.query_string = ""
        for widget, field, value in widget_states:
            state = msg.rerun_script.widget_states.widgets.add()
            state.id = self.widgets[widget].id
            setattr(state, field, value)
        await self.ws.write_message(msg.SerializeToString(), binary=True)

        elements, tabs = [], []
        while True:
            raw = await asyncio.wait_for(self.ws.read_message(), timeout=300)
            assert raw is not None, "websocket closed by the server"
            fm = ForwardMsg.FromString(raw)
            if fm.WhichOneof("type") == "ref_hash":
                fm = self.cache[fm.ref_hash]
            elif fm.hash:
                self.cache[fm.hash] = fm
            if fm.WhichOneof("type") == "script_finished":
                return Rendered(elements, tabs)
            if fm.WhichOneof("type") != "delta":
                continue
            if fm.delta.WhichOneof("type") == "add_block" and fm.delta.add_block.WhichOneof("type") == "tab":
                tabs.append(fm.delta.add_block.tab.label)
            elif fm.delta.WhichOneof("type") == "new_element":
                element = fm.delta.new_element
                elements.append(element)
                kind = element.WhichOneof("type")
                proto = getattr(element, kind)
                if getattr(proto, "id", None) and hasattr(proto, "label"):
                    self.widgets[(kind, proto.label)] = proto


class Rendered:
    def __init__(self, elements, tabs):
        self.elements, self.tabs = elements, tabs

    def of(self, kind):
        return [getattr(e, kind) for e in self.elements if e.WhichOneof("type") == kind]

    def alerts(self, fmt):
        return [a.body for a in self.of("alert") if a.format == fmt]

    def problems(self):
        return [f"{x.type}: {x.message}" for x in self.of("exception")] + self.alerts(ERROR)

    def dataframe_columns(self, index=0):
        return pa.ipc.open_stream(self.of("dataframe")[index].arrow_data.data).read_all().column_names


async def scenario():
    request = HTTPRequest(URL.replace("https://", "wss://") + "/_stcore/stream",
                          headers={"Origin": URL}, request_timeout=120)
    ws = await websocket_connect(request, subprotocols=["streamlit"], max_message_size=64 * 2**20)
    try:
        s = Session(ws)

        # Startup reads the accounts from the private bucket
        page = await s.run()
        assert not page.problems()
        assert page.tabs == ["Draft", "My Hero Lists", "Pro Meta"]
        assert ("button", "Login") in s.widgets
        # The daily job keeps the data fresh
        using = next(i for i in page.alerts(INFO) if i.startswith("Using "))
        date = datetime.date.fromisoformat(re.search(r"\d{4}-\d{2}-\d{2}", using).group())
        assert (datetime.date.today() - date).days <= 2, f"latest data is from {date}"

        page = await s.run([
            (("text_input", "Enemy heroes (separated by commas)"), "string_value", "am,pudge"),
            (("text_input", "Ally heroes (separated by commas)"), "string_value", "Lion"),
        ])
        assert not page.problems()
        assert {"Anti-Mage", "Pudge", "Lion"} <= set(page.dataframe_columns())

        # Pro Meta: OpenDota for the league list, Stratz for the matches
        page = await s.run([(("button", "Load recent tournaments"), "trigger_value", True)])
        assert not page.problems()
        assert s.widgets[("selectbox", "Select tournament")].options
        page = await s.run([(("button", "Fetch tournament data"), "trigger_value", True)])
        assert not page.problems()
        assert any(a.startswith("Fetched") for a in page.alerts(SUCCESS))
        assert len(page.of("dataframe")) >= 2 and page.of("html")
    finally:
        ws.close()


def test_health():
    assert urllib.request.urlopen(f"{URL}/_stcore/health", timeout=120).read() == b"ok"


def test_app():
    asyncio.run(scenario())
