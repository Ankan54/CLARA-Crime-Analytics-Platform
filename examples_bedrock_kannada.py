"""
Example usage patterns for ChatBedrockKannada in LangGraph.
Copy and adapt these examples for your assistant.
"""

# ============================================================================
# Example 1: Simple Chat Node
# ============================================================================
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage
from typing import TypedDict, List
from test_bedrock_kannada import ChatBedrockKannada

class ChatState(TypedDict):
    messages: List[BaseMessage]

def simple_chat_node(state: ChatState) -> ChatState:
    """Simple chat node that responds to user messages."""
    llm = ChatBedrockKannada()
    response = llm.invoke(state["messages"])
    return {"messages": state["messages"] + [response]}

# Build graph
graph = StateGraph(ChatState)
graph.add_node("chat", simple_chat_node)
graph.set_entry_point("chat")
graph.add_edge("chat", END)
app = graph.compile()

# Use it
result = app.invoke({"messages": [
    SystemMessage(content="ನೀವು ಸಹಾಯಕ ಸಹಾಯಕ."),
    HumanMessage(content="ಸೈಬರ್ ಹಿಂಸೆ ಎಂದರೆ ಏನು?"),
]})
print(result["messages"][-1].content)


# ============================================================================
# Example 2: Multi-Node Graph with Tool Calling
# ============================================================================
from langchain_core.tools import tool
from langchain_core.messages import ToolMessage, AIMessage

@tool
def search_crime_database(query: str) -> str:
    """Search the crime database for information about cyber crimes."""
    # In real implementation, query your database
    return f"Found records for: {query}"

@tool
def get_crime_statistics(crime_type: str) -> str:
    """Get statistics about a specific type of crime."""
    return f"Statistics for {crime_type}: 150 cases in 2024"

class ToolState(TypedDict):
    messages: List[BaseMessage]

def llm_node(state: ToolState) -> ToolState:
    """LLM node that can call tools."""
    llm = ChatBedrockKannada()
    llm_with_tools = llm.bind_tools([search_crime_database, get_crime_statistics])
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": state["messages"] + [response]}

def tool_node(state: ToolState) -> ToolState:
    """Execute tool calls from the LLM."""
    messages = state["messages"]
    last_message = messages[-1]
    
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return state
    
    tool_results = []
    for tool_call in last_message.tool_calls:
        if tool_call["name"] == "search_crime_database":
            result = search_crime_database.invoke({"query": tool_call["args"]["query"]})
        elif tool_call["name"] == "get_crime_statistics":
            result = get_crime_statistics.invoke({"crime_type": tool_call["args"]["crime_type"]})
        else:
            result = "Unknown tool"
        
        tool_results.append(ToolMessage(
            content=result,
            tool_call_id=tool_call["id"],
        ))
    
    return {"messages": messages + tool_results}

# Build graph
graph = StateGraph(ToolState)
graph.add_node("llm", llm_node)
graph.add_node("tools", tool_node)
graph.set_entry_point("llm")

# Route based on whether tools were called
def should_continue(state: ToolState):
    messages = state["messages"]
    last_message = messages[-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return END

graph.add_conditional_edges("llm", should_continue)
graph.add_edge("tools", "llm")

app = graph.compile()

# Use it
result = app.invoke({"messages": [
    SystemMessage(content="ನೀವು ಸೈಬರ್ ಅಪರಾಧ ವಿಶ್ಲೇಷಕ. ಡೇಟಾಬೇಸ್ ಅನ್ನು ಖೋಜಿ."),
    HumanMessage(content="ಫಿಶಿಂಗ್ ದಾಳಿಗಳ ಬಗ್ಗೆ ಮಾಹಿತಿ ಪಡೆಯಿರಿ."),
]})
print(result["messages"][-1].content)


# ============================================================================
# Example 3: Multi-Turn Conversation with Context
# ============================================================================
class ConversationState(TypedDict):
    messages: List[BaseMessage]
    context: str

def context_aware_chat(state: ConversationState) -> ConversationState:
    """Chat node that uses context from previous turns."""
    llm = ChatBedrockKannada(temperature=0.5)  # More creative
    
    # Build system prompt with context
    system_prompt = f"""ನೀವು ಸೈಬರ್ ಅಪರಾಧ ವಿಶ್ಲೇಷಕ.
ಸಂದರ್ಭ: {state['context']}
ಸಂಕ್ಷಿಪ್ತವಾಗಿ ಮತ್ತು ನಿಖುಂಜವಾಗಿ ಉತ್ತರ ಕೊಡಿ."""
    
    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    response = llm.invoke(messages)
    
    return {
        "messages": state["messages"] + [response],
        "context": state["context"],
    }

# Use it
state = {
    "messages": [HumanMessage(content="ಫಿಶಿಂಗ್ ದಾಳಿ ಎಂದರೆ ಏನು?")],
    "context": "ಕರ್ನಾಟಕ ಪೊಲೀಸ್ ಸೈಬರ್ ಕ್ರೈಮ್ ವಿಭಾಗ",
}
result = context_aware_chat(state)
print(result["messages"][-1].content)


# ============================================================================
# Example 4: Streaming Responses (Future Enhancement)
# ============================================================================
# Note: Streaming not yet implemented in ChatBedrockKannada
# This is a placeholder for future enhancement

def streaming_chat_node(state: ChatState) -> ChatState:
    """Chat node with streaming support (future)."""
    llm = ChatBedrockKannada(stream_output=True)
    # When streaming is implemented:
    # for chunk in llm.stream(state["messages"]):
    #     print(chunk.content, end="", flush=True)
    response = llm.invoke(state["messages"])
    return {"messages": state["messages"] + [response]}


# ============================================================================
# Example 5: Error Handling and Retry Logic
# ============================================================================
import time
from langchain_core.exceptions import LLMException

def resilient_chat_node(state: ChatState, max_retries: int = 3) -> ChatState:
    """Chat node with retry logic."""
    llm = ChatBedrockKannada()
    
    for attempt in range(max_retries):
        try:
            response = llm.invoke(state["messages"])
            return {"messages": state["messages"] + [response]}
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff
                print(f"Attempt {attempt + 1} failed, retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                # Return error message
                error_msg = AIMessage(content=f"ಸಾರಿ, ಸಮಸ್ಯೆ ಉಂಟಾಯಿತು: {str(e)}")
                return {"messages": state["messages"] + [error_msg]}


# ============================================================================
# Example 6: Batch Processing Multiple Queries
# ============================================================================
def batch_chat_node(state: ChatState) -> ChatState:
    """Process multiple queries efficiently."""
    llm = ChatBedrockKannada()
    
    # Assume state["messages"] contains multiple user queries
    responses = []
    for msg in state["messages"]:
        if isinstance(msg, HumanMessage):
            response = llm.invoke([msg])
            responses.append(response)
    
    return {"messages": state["messages"] + responses}


# ============================================================================
# Example 7: Integration with Pinecone Vector Search
# ============================================================================
def rag_chat_node(state: ChatState, pinecone_index) -> ChatState:
    """Chat node with Retrieval-Augmented Generation."""
    from sentence_transformers import SentenceTransformer
    
    llm = ChatBedrockKannada()
    
    # Get the last user message
    last_user_msg = None
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            last_user_msg = msg.content
            break
    
    if not last_user_msg:
        return state
    
    # Embed and search
    embedder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    query_embedding = embedder.encode(last_user_msg).tolist()
    results = pinecone_index.query(query_embedding, top_k=3)
    
    # Build context from results
    context = "\n".join([
        f"- {r['metadata'].get('text', '')}"
        for r in results["matches"]
    ])
    
    # Generate response with context
    messages = [
        SystemMessage(content=f"ಸಂದರ್ಭ:\n{context}"),
    ] + state["messages"]
    
    response = llm.invoke(messages)
    return {"messages": state["messages"] + [response]}


# ============================================================================
# Example 8: Custom Temperature and Token Limits
# ============================================================================
def creative_chat_node(state: ChatState) -> ChatState:
    """Chat node with higher temperature for creative responses."""
    llm = ChatBedrockKannada(
        temperature=0.8,  # More creative
        max_tokens=1024,  # Longer responses
    )
    response = llm.invoke(state["messages"])
    return {"messages": state["messages"] + [response]}

def precise_chat_node(state: ChatState) -> ChatState:
    """Chat node with lower temperature for precise responses."""
    llm = ChatBedrockKannada(
        temperature=0.1,  # More deterministic
        max_tokens=256,   # Shorter responses
    )
    response = llm.invoke(state["messages"])
    return {"messages": state["messages"] + [response]}


# ============================================================================
# Example 9: Conditional Routing Based on Intent
# ============================================================================
def intent_router(state: ChatState) -> str:
    """Route to different nodes based on user intent."""
    last_msg = state["messages"][-1].content.lower()
    
    if "ಸಂಖ್ಯೆ" in last_msg or "ಅಂಕಿ" in last_msg:
        return "statistics"
    elif "ಹುಡುಕು" in last_msg or "ಖೋಜು" in last_msg:
        return "search"
    else:
        return "chat"

# Use in graph
graph = StateGraph(ChatState)
graph.add_node("chat", simple_chat_node)
graph.add_node("statistics", lambda s: s)  # Placeholder
graph.add_node("search", lambda s: s)      # Placeholder
graph.set_entry_point("chat")
graph.add_conditional_edges("chat", intent_router)


# ============================================================================
# Example 10: Logging and Monitoring
# ============================================================================
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def monitored_chat_node(state: ChatState) -> ChatState:
    """Chat node with logging and monitoring."""
    llm = ChatBedrockKannada()
    
    logger.info(f"Processing {len(state['messages'])} messages")
    start_time = time.time()
    
    response = llm.invoke(state["messages"])
    
    elapsed = time.time() - start_time
    usage = response.response_metadata.get("usage", {})
    
    logger.info(f"Response generated in {elapsed:.2f}s")
    logger.info(f"Tokens: {usage}")
    
    return {"messages": state["messages"] + [response]}
