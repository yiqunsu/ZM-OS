"""Code-owned budgets shared by execution and Run configuration snapshots."""

MAX_MAIN_CALLS = 6
MAX_MODEL_CALLS = 10
MAX_TOOL_CALLS = 8
CONTEXT_TOKEN_BUDGET = 24000
# UTF-8 bytes conservatively bound text tokens; reserve room for tools and output.
MAX_CONTEXT_TEXT_BYTES = 18000
