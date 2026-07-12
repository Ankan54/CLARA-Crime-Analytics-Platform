# Bedrock Kannada + LangGraph Integration

## Quick Start (30 seconds)

```bash
# 1. Verify connection
python test_bedrock_kannada.py

# 2. Use in your code
from test_bedrock_kannada import ChatBedrockKannada
from langchain_core.messages import HumanMessage, SystemMessage

llm = ChatBedrockKannada()
response = llm.invoke([
    SystemMessage(content="ನೀವು ಸಹಾಯಕ."),
    HumanMessage(content="ಸೈಬರ್ ಹಿಂಸೆ ಎಂದರೆ ಏನು?"),
])
print(response.content)
```

## Files

| File | Purpose |
|------|---------|
| `test_bedrock_kannada.py` | Main test script + `ChatBedrockKannada` class |
| `BEDROCK_KANNADA_GUIDE.md` | Complete integration guide |
| `BEDROCK_KANNADA_SUMMARY.md` | Quick reference summary |
| `examples_bedrock_kannada.py` | 10 usage examples |

## What's Included

✅ **ChatBedrockKannada** - LangChain-compatible wrapper for Bedrock Kannada model
✅ **LangGraph Integration** - Ready to use in multi-node graphs
✅ **Tool Binding** - Support for function calling
✅ **Token Tracking** - Automatic usage monitoring
✅ **Error Handling** - Graceful failure modes
✅ **Unicode Support** - Full Kannada text support

## Test Results

```
1. Raw Bedrock API ✓
   - 2.4s latency
   - 142 tokens
   - Kannada response

2. LangChain ChatModel ✓
   - 69 input tokens
   - 110 output tokens
   - Full message handling

3. LangGraph Integration ✓
   - 2.1s end-to-end
   - State machine ready
   - Multi-node capable
```

## Environment Setup

```env
AWS_ACCESS_KEY_ID=<your_key>
AWS_SECRET_ACCESS_KEY=<your_secret>
AWS_DEFAULT_REGION=us-east-1
BEDROCK_MODEL_ID_KANNADA=amazon.nova-pro-v1:0
```

## Usage Examples

### Simple Chat
```python
from test_bedrock_kannada import ChatBedrockKannada
llm = ChatBedrockKannada()
response = llm.invoke([HumanMessage(content="ನಮಸ್ಕಾರ")])
```

### With LangGraph
```python
from langgraph.graph import StateGraph, END
from test_bedrock_kannada import ChatBedrockKannada

def chat_node(state):
    llm = ChatBedrockKannada()
    return {"messages": state["messages"] + [llm.invoke(state["messages"])]}

graph = StateGraph(State)
graph.add_node("chat", chat_node)
# ... build your graph
```

### With Tools
```python
from langchain_core.tools import tool

@tool
def search_database(query: str) -> str:
    """Search crime database."""
    return f"Results for: {query}"

llm = ChatBedrockKannada()
llm_with_tools = llm.bind_tools([search_database])
response = llm_with_tools.invoke(messages)
```

## Performance

- **Latency**: 2-3 seconds per request
- **Input tokens**: ~70 average
- **Output tokens**: ~100 average
- **Model**: amazon.nova-pro-v1:0
- **Region**: us-east-1

## Troubleshooting

| Issue | Solution |
|-------|----------|
| AWS credentials not found | Add to `.env` and run `load_dotenv()` |
| Unicode errors on Windows | Already handled in test script |
| Model not available | Check region is `us-east-1` |
| Permission denied | Verify IAM has `bedrock:InvokeModel` |

## Next Steps

1. **Copy `ChatBedrockKannada`** into your assistant code
2. **Create your LangGraph** with the model as a node
3. **Add tools** for database queries
4. **Test end-to-end** with your data
5. **Monitor costs** using token counts

## Documentation

- **BEDROCK_KANNADA_GUIDE.md** - Full integration guide with examples
- **examples_bedrock_kannada.py** - 10 ready-to-use code examples
- **BEDROCK_KANNADA_SUMMARY.md** - Detailed summary

## Support

For issues, check:
1. `.env` has all AWS credentials
2. AWS region is `us-east-1`
3. Model ID is `amazon.nova-pro-v1:0`
4. AWS IAM permissions include `bedrock:InvokeModel`
5. See BEDROCK_KANNADA_GUIDE.md for detailed troubleshooting

## Verification

```bash
python test_bedrock_kannada.py
```

Should output:
- ✓ Raw API test (2.4s)
- ✓ LangChain test (Kannada response)
- ✓ LangGraph test (2.1s)
- ✓ All three tests passed

---

**Ready to use in your LangGraph assistant!**
