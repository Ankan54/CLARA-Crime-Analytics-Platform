"""
Test Bedrock Kannada model — raw API + LangChain ChatModel + LangGraph smoke test.

Model  : amazon.nova-pro-v1:0 (BEDROCK_MODEL_ID_KANNADA)
Region : us-east-1 (from AWS_DEFAULT_REGION)
Auth   : AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
Format : OpenAI-compatible (messages, tools, tool_choice, stream)
"""
import os, json, time, sys
from typing import Any, List, Optional, Sequence

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool

load_dotenv()

# Handle Unicode output on Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


# ---------------------------------------------------------------------------
# Part 1 — Raw Bedrock API via boto3
# ---------------------------------------------------------------------------
def test_raw_api() -> str:
    import boto3
    
    client = boto3.client(
        "bedrock-runtime",
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )
    
    model_id = os.environ.get("BEDROCK_MODEL_ID_KANNADA", "amazon.nova-pro-v1:0")
    
    t0 = time.perf_counter()
    resp = client.converse(
        modelId=model_id,
        messages=[
            {"role": "user", "content": [{"text": "ಸೈಬರ್ ಹಿಂಸೆ ಎಂದರೆ ಏನು? ಒಂದು ವಾಕ್ಯದಲ್ಲಿ ಉತ್ತರ ಕೊಡಿ."}]},
        ],
        system=[{"text": "You are a concise assistant. Respond in Kannada."}],
        inferenceConfig={
            "maxTokens": 100,
            "temperature": 0.3,
        },
    )
    elapsed = (time.perf_counter() - t0) * 1000
    
    content = resp.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", str(resp))
    usage = resp.get("usage", {})
    
    print(f"[raw API]  {elapsed:.0f}ms  |  tokens: {usage}")
    print(f"  > {content[:300]}")
    return content


# ---------------------------------------------------------------------------
# Part 2 — LangChain ChatModel wrapper
# ---------------------------------------------------------------------------
def _to_bedrock_messages(messages: List[BaseMessage]) -> list:
    """Convert LangChain messages to Bedrock format."""
    role_map = {
        HumanMessage:  "user",
        AIMessage:     "assistant",
        SystemMessage: "user",  # Bedrock uses system param, not role
        ToolMessage:   "user",
    }
    out = []
    for m in messages:
        if isinstance(m, SystemMessage):
            continue  # Handle separately
        role = role_map.get(type(m), "user")
        entry: dict = {"role": role, "content": m.content}
        out.append(entry)
    return out


def _parse_tool_calls(raw_calls: list) -> list:
    """Parse tool calls from Bedrock response."""
    result = []
    for tc in raw_calls:
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments", "{}"))
        except json.JSONDecodeError:
            args = {}
        result.append({"id": tc.get("id", ""), "name": fn["name"], "args": args, "type": "tool_call"})
    return result


class ChatBedrockKannada(BaseChatModel):
    """LangChain ChatModel for AWS Bedrock Kannada (Nova Pro)."""

    model_id: str = ""
    region_name: str = "us-east-1"
    temperature: float = 0.3
    max_tokens: int = 512
    stream_output: bool = False

    def model_post_init(self, __context: Any) -> None:
        if not self.model_id:
            object.__setattr__(self, "model_id", os.environ.get("BEDROCK_MODEL_ID_KANNADA", "amazon.nova-pro-v1:0"))
        if not self.region_name:
            object.__setattr__(self, "region_name", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

    @property
    def _llm_type(self) -> str:
        return "bedrock-kannada"

    def _get_client(self):
        import boto3
        return boto3.client("bedrock-runtime", region_name=self.region_name)

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        client = self._get_client()
        
        # Extract system message if present
        system_content = ""
        bedrock_messages = []
        for m in messages:
            if isinstance(m, SystemMessage):
                system_content = m.content
            else:
                bedrock_messages.append({
                    "role": "assistant" if isinstance(m, AIMessage) else "user",
                    "content": [{"text": m.content}],
                })
        
        converse_kwargs = {
            "modelId": self.model_id,
            "messages": bedrock_messages,
            "inferenceConfig": {
                "temperature": self.temperature,
                "maxTokens": self.max_tokens,
            },
        }
        
        if system_content:
            converse_kwargs["system"] = [{"text": system_content}]
        
        if stop:
            converse_kwargs["inferenceConfig"]["stopSequences"] = stop
        
        # Tool definitions forwarded via bind_tools / kwargs
        if "tools" in kwargs:
            converse_kwargs["toolConfig"] = {
                "tools": kwargs["tools"],
                "toolChoice": kwargs.get("tool_choice", {"type": "auto"}),
            }
        
        resp = client.converse(**converse_kwargs)
        
        # Extract content and tool calls
        content = ""
        raw_tcs = []
        
        for block in resp.get("output", {}).get("message", {}).get("content", []):
            if "text" in block:
                content = block["text"]
            elif "toolUse" in block:
                raw_tcs.append(block["toolUse"])
        
        ai_msg = AIMessage(
            content=content,
            tool_calls=_parse_tool_calls(raw_tcs) if raw_tcs else [],
            response_metadata={
                "model": self.model_id,
                "usage": resp.get("usage", {}),
            },
        )
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    def bind_tools(self, tools: Sequence, **kwargs) -> "ChatBedrockKannada":
        """Convert LangChain tools to Bedrock tool schema and bind them."""
        from langchain_core.utils.function_calling import convert_to_openai_tool
        bedrock_tools = [convert_to_openai_tool(t) for t in tools]
        return self.bind(tools=bedrock_tools, **kwargs)


# ---------------------------------------------------------------------------
# Part 3 — LangGraph smoke test
# ---------------------------------------------------------------------------
def test_langgraph(llm: ChatBedrockKannada) -> str:
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

    t0 = time.perf_counter()
    result = app.invoke({"messages": [
        SystemMessage(content="ನೀವು ಸಹಾಯಕ ಸಹಾಯಕ. ಬಹಳ ಸಂಕ್ಷಿಪ್ತವಾಗಿ ಉತ್ತರ ಕೊಡಿ."),
        HumanMessage(content="ಕರ್ನಾಟಕದಲ್ಲಿ ಸೈಬರ್ ಅಪರಾಧದ ಮೂರು ಸಾಮಾನ್ಯ ಪ್ರಕಾರಗಳನ್ನು ಹೆಸರಿಸಿ."),
    ]})
    elapsed = (time.perf_counter() - t0) * 1000
    reply = result["messages"][-1].content
    print(f"[langgraph] {elapsed:.0f}ms  >  {reply}")
    return reply


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        if not os.environ.get(k):
            raise SystemExit(f"Missing env var: {k}")

    print("=" * 60)
    print("1. Raw Bedrock API")
    print("=" * 60)
    test_raw_api()

    print("\n" + "=" * 60)
    print("2. LangChain ChatModel")
    print("=" * 60)
    llm = ChatBedrockKannada()
    response = llm.invoke([
        SystemMessage(content="ನೀವು ಸಹಾಯಕ. ಸಂಕ್ಷಿಪ್ತವಾಗಿ ಉತ್ತರ ಕೊಡಿ."),
        HumanMessage(content="ಸೈಬರ್ ಹಿಂಸೆ ಎಂದರೆ ಏನು?"),
    ])
    print(f"[langchain] > {response.content[:300]}")
    usage = response.response_metadata.get("usage", {})
    print(f"  tokens: {usage}")

    print("\n" + "=" * 60)
    print("3. LangGraph single-node graph")
    print("=" * 60)
    test_langgraph(llm)

    print("\n✓ All three tests passed.")
