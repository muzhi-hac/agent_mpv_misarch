Subject: Follow-up on Baseline Presentation: Deployment, Implementation, and Fresh Rerun

Dear [Tutor's Name],

thank you for listening to our baseline presentation.

After the presentation we realized that our slides probably looked too generic and did not show enough of our own implementation work. We would like to clarify what we actually deployed, implemented, and tested.

For our current prototype, we deployed MiSArch on a Google Cloud Compute Engine VM and implemented a separate Go-based MCP gateway. The gateway connects to the MiSArch GraphQL gateway through Docker internal networking and exposes selected catalog operations as MCP tools, especially `list_products` and `get_product`.

We reran the main baseline comparison today. This rerun only compares native MiSArch GraphQL access with the Go MCP gateway. We disabled the LLM-generated GraphQL path and did not run the pending-order side-effect test, so the result is focused only on the main read-only catalog baseline.

In 5 trials, both approaches succeeded in 5/5 runs and returned the same core product data. The native GraphQL baseline had an average latency of 212.63 ms, while the MCP gateway had an average latency of 443.01 ms. The MCP gateway therefore adds latency overhead in this simple task, but it also provides tool discovery, input schemas, standardized tool calls, and side-effect/source metadata that are useful for agent-facing interoperability.

We attached a short appendix with the fresh rerun result and a clean CSV table. Raw JSON/CSV logs are also available if needed.

Would it be possible to schedule a short appointment with you to discuss this? We would like to explain our deployment, code design, and baseline result more concretely, because our presentation did not make this clear enough.

Best regards,
[Your Names]

