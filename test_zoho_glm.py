"""
Test Zoho QuickML GLM — raw API + LangChain ChatModel + LangGraph smoke test.

Endpoint : https://api.catalyst.zoho.in/quickml/v1/project/<id>/glm/chat
Headers  : Authorization: Zoho-oauthtoken <token>
           CATALYST-ORG: <org_id>
           Content-Type: application/json
Format   : OpenAI-compatible (messages, tools, tool_choice, stream)
Model    : crm-di-glm47b_30b_it
"""
import os, json, time, requests
from typing import Any, Iterator, List, Optional, Sequence

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool

load_dotenv()

# ---------------------------------------------------------------------------
# Token refresh — auto-refreshes from refresh token
# ---------------------------------------------------------------------------
_token_cache: dict = {"token": None, "expires_at": 0.0}

def _get_access_token() -> str:
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    resp = requests.post(
        f"{os.environ.get('ZOHO_CATALYST_AUTH_DOMAIN', 'https://accounts.zohoportal.in')}/oauth/v2/token",
        data={
            "grant_type":    "refresh_token",
            "client_id":     os.environ["ZOHO_CATALYST_CLIENT_ID"],
            "client_secret": os.environ["ZOHO_CATALYST_CLIENT_SECRET"],
            "refresh_token": os.environ["ZOHO_CATALYST_REFRESH_TOKEN"],
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"Token refresh failed: {data}")
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + data.get("expires_in", 3600)
    return _token_cache["token"]


def _glm_headers() -> dict:
    return {
        "Authorization": f"Zoho-oauthtoken {_get_access_token()}",
        "CATALYST-ORG":  os.environ["ZOHO_QUICKML_CATALYST_ORG"],
        "Content-Type":  "application/json",
    }


# ---------------------------------------------------------------------------
# Part 1 — Raw REST API
# ---------------------------------------------------------------------------
def test_raw_api() -> str:
    url     = os.environ["ZOHO_QUICKML_ENDPOINT_URL"]
    model   = os.environ.get("ZOHO_QUICKML_MODEL_NAME", "crm-di-glm47b_30b_it")
    payload = {
        "model":       model,
        "messages":    [
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user",   "content": "In one sentence, what is cyber fraud?"},
        ],
        "max_tokens":  100,
        "temperature": 0.3,
        "stream":      False,
    }

    t0   = time.perf_counter()
    resp = requests.post(url, headers=_glm_headers(), json=payload, timeout=60)
    elapsed = (time.perf_counter() - t0) * 1000

    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    data    = resp.json()
    # Real shape: {"response": "...", "tool_calls": [], "usage": {...}, "model": "...", "created_time": ...}
    content = data.get("response") or data.get("choices", [{}])[0].get("message", {}).get("content", str(data))
    tokens  = data.get("usage", {})
    print(f"[raw API]  {elapsed:.0f}ms  |  tokens: {tokens}")
    print(f"  → {content[:300]}")
    return content


# ---------------------------------------------------------------------------
# Part 2 — LangChain ChatModel wrapper
# ---------------------------------------------------------------------------
def _to_openai_messages(messages: List[BaseMessage]) -> list:
    role_map = {
        HumanMessage:  "user",
        AIMessage:     "assistant",
        SystemMessage: "system",
        ToolMessage:   "tool",
    }
    out = []
    for m in messages:
        role = role_map.get(type(m), "user")
        entry: dict = {"role": role, "content": m.content}
        # pass tool_call_id for tool results
        if isinstance(m, ToolMessage):
            entry["tool_call_id"] = m.tool_call_id
        # pass tool_calls for assistant messages
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            entry["tool_calls"] = [
                {
                    "id":       tc["id"],
                    "type":     "function",
                    "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])},
                }
                for tc in m.tool_calls
            ]
        out.append(entry)
    return out


def _parse_tool_calls(raw_calls: list) -> list:
    result = []
    for tc in raw_calls:
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments", "{}"))
        except json.JSONDecodeError:
            args = {}
        result.append({"id": tc["id"], "name": fn["name"], "args": args, "type": "tool_call"})
    return result


class ChatZohoGLM(BaseChatModel):
    """LangChain ChatModel for Zoho QuickML GLM (OpenAI-compatible endpoint)."""

    endpoint_url: str  = ""
    catalyst_org: str  = ""
    model_name: str    = "crm-di-glm47b_30b_it"
    temperature: float = 0.3
    max_tokens: int    = 512
    stream_output: bool = False

    def model_post_init(self, __context: Any) -> None:
        if not self.endpoint_url:
            object.__setattr__(self, "endpoint_url", os.environ.get("ZOHO_QUICKML_ENDPOINT_URL", ""))
        if not self.catalyst_org:
            object.__setattr__(self, "catalyst_org", os.environ.get("ZOHO_QUICKML_CATALYST_ORG", ""))

    @property
    def _llm_type(self) -> str:
        return "zoho-quickml-glm"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Zoho-oauthtoken {_get_access_token()}",
            "CATALYST-ORG":  self.catalyst_org,
            "Content-Type":  "application/json",
        }

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        payload: dict = {
            "model":       self.model_name,
            "messages":    _to_openai_messages(messages),
            "temperature": self.temperature,
            "max_tokens":  self.max_tokens,
            "stream":      False,
        }
        if stop:
            payload["stop"] = stop
        # tool definitions forwarded via bind_tools / kwargs
        if "tools" in kwargs:
            payload["tools"]       = kwargs["tools"]
            payload["tool_choice"] = kwargs.get("tool_choice", "auto")

        resp = requests.post(self.endpoint_url, headers=self._headers(), json=payload, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"GLM API error {resp.status_code}: {resp.text[:300]}")

        data    = resp.json()
        # Real shape: {"response": "...", "tool_calls": [...], "usage": {...}}
        content = data.get("response") or data.get("choices", [{}])[0].get("message", {}).get("content", "")
        raw_tcs = data.get("tool_calls") or []

        ai_msg = AIMessage(
            content=content,
            tool_calls=_parse_tool_calls(raw_tcs) if raw_tcs else [],
            response_metadata={
                "model":   data.get("model"),
                "usage":   data.get("usage", {}),
            },
        )
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    def bind_tools(self, tools: Sequence, **kwargs) -> "ChatZohoGLM":
        """Convert LangChain tools to OpenAI function-call schema and bind them."""
        from langchain_core.utils.function_calling import convert_to_openai_tool
        openai_tools = [convert_to_openai_tool(t) for t in tools]
        return self.bind(tools=openai_tools, **kwargs)


# ---------------------------------------------------------------------------
# Part 3 — LangGraph smoke test
# ---------------------------------------------------------------------------
def test_langgraph(llm: ChatZohoGLM) -> str:
    from langgraph.graph import StateGraph, END
    from typing import TypedDict

    class State(TypedDict):
        messages: List[BaseMessage]

    def chat_node(state: State) -> State:
        return {"messages": state["messages"] + [llm.invoke(state["messages"])]}

    g = StateGraph(State)
    g.add_node("chat", chat_node)
    g.set_entry_point("chat")
    g.add_edge("chat", END)
    app = g.compile()

    t0     = time.perf_counter()
    result = app.invoke({"messages": [
        SystemMessage(content="Be extremely brief."),
        HumanMessage(content="Reply with exactly: GLM is live in LangGraph"),
    ]})
    elapsed = (time.perf_counter() - t0) * 1000
    reply   = result["messages"][-1].content
    print(f"[langgraph] {elapsed:.0f}ms  →  {reply}")
    return reply


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for k in ("ZOHO_QUICKML_ENDPOINT_URL", "ZOHO_QUICKML_CATALYST_ORG"):
        if not os.environ.get(k):
            raise SystemExit(f"Missing env var: {k}")

    print("=" * 60)
    print("1. Raw REST API")
    print("=" * 60)
    test_raw_api()

    print("\n" + "=" * 60)
    print("2. LangChain ChatModel")
    print("=" * 60)
    llm      = ChatZohoGLM()
    response = llm.invoke([
        SystemMessage(content="Be concise."),
        HumanMessage(content="Name three common types of cyber fraud in Karnataka, one line each."),
    ])
    print(f"[langchain] → {response.content[:300]}")
    usage = response.response_metadata.get("usage", {})
    print(f"  tokens: {usage}")

    print("\n" + "=" * 60)
    print("3. LangGraph single-node graph")
    print("=" * 60)
    test_langgraph(llm)

    print("\n✓ All three tests passed.")
