# Agent-Driven Four-Pane Search Implementation Plan

**Goal:** Replace the deterministic last-token query extraction in the recorded
four-pane demo with a real OpenAI Responses API function-calling loop.

**Architecture:** Each pane sends the user's original question to its OpenAI
Agent first. The Agent must call the strict `search_catalog` function with a
product query and optional EUR price ceiling. The application executes that
request through the pane's real GraphQL, MCP, or A2A path, then returns a
`function_call_output` to the same Agent for the final structured decision.
The request remains `store: false`, so the second request manually includes the
original user input and every output item from the first response, including
reasoning items.

**OpenAI contract:** Follow the official Responses API function-calling flow:
declare a strict JSON-schema function, parse `function_call.arguments`, execute
the application function, append the response output plus a matching
`function_call_output`, and request the final response.

## Task 1: Specify the Agent tool contract with tests

**Files:**
- Modify: `scripts/test_openai_demo_agent.py`
- Modify: `scripts/openai_demo_agent.py`

1. Add fixtures for a Responses API `function_call` and a final structured
   response.
2. Add failing tests proving the raw question is sent before retrieval, the
   strict `search_catalog` schema is exposed, `cup` and `25` come from the Agent
   call, and the second request carries the tool output and first response
   items.
3. Implement tool-call parsing, validation, two-turn request orchestration,
   aggregate token usage, and response metadata.
4. Run the focused OpenAI Agent unit tests.

## Task 2: Route each arm's actual protocol through the Agent callback

**Files:**
- Modify: `scripts/test_demo_four_arms.py`
- Modify: `scripts/demo_four_arms.py`

1. Add failing tests for query and price constraint application and for
   rendering the Agent-issued tool call.
2. Replace `extract_catalog_query(question)` in `run_arm` with an executor
   callback invoked only after the Agent returns `search_catalog`.
3. Execute the existing GraphQL, MCP, or A2A retrieval path inside that
   callback, then apply the Agent's query and EUR ceiling.
4. Preserve each arm's policy, privacy boundary, protocol trace, and public
   audit output.
5. Render the actual Agent tool arguments and the two-call Agent timing/token
   metadata.

## Task 3: Document and verify the recording workflow

**Files:**
- Modify: `README.md`
- Modify: `docs/video-deployment-demo.zh.md`

1. Explain that four-pane mode sends the original question directly to the
   Agent and requires `OPENAI_API_KEY`, while the deployment recording remains
   independent and key-free.
2. Run all focused demo and deployment-script tests.
3. Run syntax/compile checks and shell lint checks for the launch scripts.
4. If the current shell has an API key, perform one live Agent tool-call smoke
   test; otherwise report the exact ready-to-record command without exposing or
   persisting the key.
5. Review the diff for secrets, placeholders, accidental generated files, and
   unrelated user changes.
