# Bedrock Kannada Model Integration Guide

## Overview

This guide explains how to use the AWS Bedrock Kannada model (`amazon.nova-pro-v1:0`) with LangChain and LangGraph for your KSP datathon assistant.

## Quick Start

### 1. Verify Connection

Run the test script to verify your Bedrock connection:

```bash
python test_bedrock_kannada.py
```

Expected output:
```
============================================================
1. Raw Bedrock API
============================================================
[raw API]  ~2400ms  |  tokens: {'inputTokens': 71, 'outputTokens': 86, 'totalTokens': 157}
  > ಸೈಬರ್ ಹಿಂಸೆ ಎಂದರೆ ಆನ್‌ಲೈನ್ ಮೂಲಕ ಒಬ್ಬರಿಗೆ ಹಾನಿ ಮಾಡುವ ಅಥವಾ ಅವಮಾನಿಸುವ ಕ್ರಿಯೆ.

============================================================
2. LangChain ChatModel
============================================================
[langchain] > ಸೈಬರ್ ಹಿಂಸೆ ಎಂದರೆ ಇಂಟರ್ನೆಟ್ ಅಥವಾ ಡಿಜಿಟಲ್ ಸಾಧನಗಳ ಮೂಲಕ ಒಬ್ಬರನ್ನೊಬ್ಬರು ತೊಂದರೆಗೊಳಿಸುವ ಅಥವಾ ಹಿಂಸಿಸುವ ಕ್ರಿಯೆ.
  tokens: {'inputTokens': 69, 'outputTokens': 115, 'totalTokens': 184}

============================================================
3. LangGraph single-node graph
============================================================
[langgraph] 2095ms  >  ಫಿಶಿಂಗ್, ಡೇಟಾ ಉಲ್ಲಂಘನೆ, ಮ್ಯಾಲ್ವೇರ್ ದಾಳಿಗಳು.

✓ All three tests passed.
```

### 2. Environment Variables

Ensure these are in your `.env` file:

```env
# AWS Credentials
AWS_ACCESS_KEY_ID=<your_key>
AWS_SECRET_ACCESS_KEY=<your_secret>
AWS_DEFAULT_REGION=us-east-1

# Bedrock Models
BEDROCK_MODEL_ID=amazon.nova-lite-v1:0
BEDROCK_MODEL_ID_KANNADA=amazon.nova-pro-v1:0
BEDROCK_EMBEDDING_MODEL=amazon.titan-embed-text-v1
```

## Using in Your Code

### Basic Usage with LangChain

```python
from test_bedrock_kannada import ChatBedrockKannada
from langchain_core.messages import SystemMessage, HumanMessage

# Initialize the model
llm = ChatBedrockKannada()

# Invoke with messages
response = llm.invoke([
    SystemMessage(content="ನೀವು ಸಹಾಯಕ. ಸಂಕ್ಷಿಪ್ತವಾಗಿ ಉತ್ತರ ಕೊಡಿ."),
    HumanMessage(content="ಸೈಬರ್ ಹಿಂಸೆ ಎಂದರೆ ಏನು?"),
])

print(response.content)
```

### Using in LangGraph

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict, List
from langchain_core.messages import BaseMessage
from test_bedrock_kannada import ChatBedrockKannada

class State(TypedDict):
    messages: List[BaseMessage]

def chat_node(state: State) -> State:
    llm = ChatBedrockKannada()
    response = llm.invoke(state["messages"])
    return {"messages": state["messages"] + [response]}

# Build graph
graph = StateGraph(State)
graph.add_node("chat", chat_node)
graph.set_entry_point("chat")
graph.add_edge("chat", END)
app = graph.compile()

# Run
result = app.invoke({"messages": [
    SystemMessage(content="ನೀವು ಸಹಾಯಕ."),
    HumanMessage(content="ಕರ್ನಾಟಕದಲ್ಲಿ ಸೈಬರ್ ಅಪರಾಧದ ಮೂರು ಪ್ರಕಾರಗಳನ್ನು ಹೆಸರಿಸಿ."),
]})

print(result["messages"][-1].content)
```

### Multi-Node LangGraph with Tool Calling

```python
from langgraph.graph import StateGraph, END
from langchain_core.tools import tool
from test_bedrock_kannada import ChatBedrockKannada

@tool
def search_crime_database(query: str) -> str:
    """Search the crime database for information."""
    return f"Found crime records for: {query}"

class State(TypedDict):
    messages: List[BaseMessage]

def chat_node(state: State) -> State:
    llm = ChatBedrockKannada()
    # Bind tools to the model
    llm_with_tools = llm.bind_tools([search_crime_database])
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": state["messages"] + [response]}

def tool_node(state: State) -> State:
    # Handle tool calls here
    return state

# Build graph
graph = StateGraph(State)
graph.add_node("chat", chat_node)
graph.add_node("tools", tool_node)
graph.set_entry_point("chat")
graph.add_edge("chat", END)
app = graph.compile()
```

## API Details

### ChatBedrockKannada Class

**Parameters:**
- `model_id` (str): Bedrock model ID (default: `amazon.nova-pro-v1:0`)
- `region_name` (str): AWS region (default: `us-east-1`)
- `temperature` (float): Sampling temperature (default: `0.3`)
- `max_tokens` (int): Maximum tokens in response (default: `512`)
- `stream_output` (bool): Enable streaming (default: `False`)

**Methods:**
- `invoke(messages)`: Send messages and get response
- `bind_tools(tools)`: Bind LangChain tools for function calling
- `_generate(messages, stop, run_manager, **kwargs)`: Internal generation method

### Bedrock Converse API Format

The underlying Bedrock API uses the Converse format:

```python
client.converse(
    modelId="amazon.nova-pro-v1:0",
    messages=[
        {"role": "user", "content": [{"text": "Your question"}]},
    ],
    system=[{"text": "System prompt"}],
    inferenceConfig={
        "maxTokens": 512,
        "temperature": 0.3,
    },
)
```

## Performance Notes

- **Raw API latency**: ~2-3 seconds per request
- **Token usage**: Tracked in response metadata
- **Kannada support**: Full Unicode support for Kannada text
- **Batch processing**: Not yet implemented (can be added for multiple queries)

## Common Issues

### 1. AWS Credentials Not Found

**Error**: `botocore.exceptions.NoCredentialsError`

**Fix**: Ensure `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` are in `.env` and loaded before importing boto3.

```python
from dotenv import load_dotenv
load_dotenv()  # Must be before any boto3 import
```

### 2. Unicode Output Issues on Windows

**Error**: `UnicodeEncodeError` when printing Kannada text

**Fix**: The test script automatically handles this with:

```python
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
```

### 3. Model Not Available

**Error**: `ValidationException: Could not validate the provided model identifier`

**Fix**: Verify the model ID is correct and available in your AWS region:
- `amazon.nova-pro-v1:0` (Kannada)
- `amazon.nova-lite-v1:0` (English)

### 4. Insufficient Permissions

**Error**: `AccessDeniedException`

**Fix**: Ensure your AWS credentials have `bedrock:InvokeModel` permission.

## Integration with Existing Systems

### With Pinecone Vector Search

```python
from test_bedrock_kannada import ChatBedrockKannada
from langchain_core.messages import HumanMessage, SystemMessage

# Search Pinecone for relevant documents
query_embedding = embed_query("ಸೈಬರ್ ಹಿಂಸೆ")
results = pinecone_index.query(query_embedding, top_k=3)

# Build context from results
context = "\n".join([r["metadata"]["text"] for r in results])

# Generate response with Bedrock
llm = ChatBedrockKannada()
response = llm.invoke([
    SystemMessage(content=f"Context: {context}"),
    HumanMessage(content="ಸೈಬರ್ ಹಿಂಸೆ ಎಂದರೆ ಏನು?"),
])
```

### With Neo4j Graph Database

```python
from neo4j import GraphDatabase
from test_bedrock_kannada import ChatBedrockKannada

# Query Neo4j for entity relationships
driver = GraphDatabase.driver("neo4j+s://...", auth=(...))
with driver.session() as session:
    result = session.run("MATCH (c:Crime)-[:RELATED_TO]->(e:Entity) RETURN c, e LIMIT 5")
    entities = [record for record in result]

# Use in LLM context
llm = ChatBedrockKannada()
response = llm.invoke([
    SystemMessage(content=f"Related entities: {entities}"),
    HumanMessage(content="ಈ ಅಪರಾಧಗಳ ನಡುವಿನ ಸಂಬಂಧ ಏನು?"),
])
```

## Testing

Run the comprehensive test suite:

```bash
# Test all three components
python test_bedrock_kannada.py

# Test just the raw API
python -c "from test_bedrock_kannada import test_raw_api; test_raw_api()"

# Test just LangChain
python -c "from test_bedrock_kannada import ChatBedrockKannada; from langchain_core.messages import HumanMessage; llm = ChatBedrockKannada(); print(llm.invoke([HumanMessage(content='ನಮಸ್ಕಾರ')]))"

# Test just LangGraph
python -c "from test_bedrock_kannada import test_langgraph, ChatBedrockKannada; test_langgraph(ChatBedrockKannada())"
```

## Next Steps

1. **Integrate with your LangGraph assistant**: Use `ChatBedrockKannada` as the LLM in your multi-node graph
2. **Add tool calling**: Bind tools for database queries, web search, etc.
3. **Implement streaming**: Set `stream_output=True` for real-time responses
4. **Add caching**: Cache embeddings and model responses for faster retrieval
5. **Monitor costs**: Track token usage in response metadata

## References

- [AWS Bedrock Documentation](https://docs.aws.amazon.com/bedrock/)
- [LangChain Bedrock Integration](https://python.langchain.com/docs/integrations/llms/bedrock/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Kannada Language Support](https://en.wikipedia.org/wiki/Kannada_script)
