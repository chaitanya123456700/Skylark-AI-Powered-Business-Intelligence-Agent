import json
import math

from google import genai

from config import GEMINI_API_KEY, GEMINI_MODEL
from tools import TOOLS_SPEC, execute_tool


# =========================================================
# Gemini Client
# =========================================================

client = genai.Client(
    api_key=GEMINI_API_KEY
)


# =========================================================
# System Prompt
# =========================================================

SYSTEM_PROMPT = """You are a business intelligence assistant for a founder/executive.

You are backed by live data synced from two monday.com boards:

1. Deals - sales pipeline
2. Work Orders - project execution

Rules:

1. NEVER invent a number.
   Every number in your answer must come from a tool result.

2. Prefer compute_metric whenever the question matches a known
   business metric.

3. Use run_sql_query for novel questions, custom analysis,
   unusual filtering, grouping, or questions requiring both
   Deals and Work Orders.

4. Use search_notes for questions about free-text notes,
   comments, or remarks.

5. Use get_data_quality_report when missing data could
   materially affect the answer.

6. If the question is genuinely ambiguous, ask ONE short
   clarifying question instead of guessing.

7. For "this quarter", use the current calendar quarter.

8. Keep answers concise and business-friendly:
   - short headline finding
   - 2-4 supporting bullets

9. For leadership updates, provide:
   - Pipeline health
   - Notable wins
   - Notable risks
   - Operational status
   - Important data-quality issues

10. NEVER invent or estimate data that was not returned
    by a tool.
"""


# =========================================================
# JSON Safety
# =========================================================

def make_json_safe(value):
    """
    Convert pandas/numpy-style NaN and Infinity values
    into JSON-safe None values.
    """

    if isinstance(value, float):

        if math.isnan(value) or math.isinf(value):
            return None

        return value

    if isinstance(value, dict):

        return {
            key: make_json_safe(val)
            for key, val in value.items()
        }

    if isinstance(value, list):

        return [
            make_json_safe(item)
            for item in value
        ]

    return value


# =========================================================
# Gemini Tool Definitions
# =========================================================

def build_gemini_tools():
    """
    Convert the existing Anthropic-style TOOLS_SPEC
    into the dictionary format required by the
    Gemini Interactions API.
    """

    tools = []

    for tool in TOOLS_SPEC:

        tools.append(
            {
                "type": "function",
                "name": tool["name"],
                "description": tool.get(
                    "description",
                    ""
                ),
                "parameters": tool.get(
                    "input_schema",
                    {
                        "type": "object",
                        "properties": {}
                    }
                )
            }
        )

    return tools


GEMINI_TOOLS = build_gemini_tools()


# =========================================================
# Main Agent
# =========================================================

def handle_query(
    history: list,
    message: str,
    max_tool_iters: int = 12
):
    """
    Main Gemini agent loop.

    Flow:

        User
          ↓
        Gemini
          ↓
        Function Call
          ↓
        execute_tool()
          ↓
        Monday / Pandas / DuckDB
          ↓
        Function Result
          ↓
        Gemini
          ↓
        Final Answer

    Returns:

        reply_text,
        updated_history,
        tool_log
    """

    tool_log = []

    # -----------------------------------------------------
    # Initial request
    # -----------------------------------------------------

    response = client.interactions.create(
        model=GEMINI_MODEL,
        input=message,
        system_instruction=SYSTEM_PROMPT,
        tools=GEMINI_TOOLS
    )

    # -----------------------------------------------------
    # Tool-calling loop
    # -----------------------------------------------------

    for _ in range(max_tool_iters):

        function_calls = []

        # Find all function calls from Gemini
        for step in response.steps:

            if getattr(step, "type", None) == "function_call":

                function_calls.append(step)

        # -------------------------------------------------
        # No function call = final answer
        # -------------------------------------------------

        if not function_calls:

            answer = response.output_text or ""

            updated_history = history + [
                {
                    "role": "user",
                    "content": message
                },
                {
                    "role": "assistant",
                    "content": answer
                }
            ]

            return (
                answer,
                updated_history,
                tool_log
            )

        # -------------------------------------------------
        # Execute all requested functions
        # -------------------------------------------------

        function_results = []

        for call in function_calls:

            tool_name = call.name

            arguments = call.arguments or {}

            print(
                f"\n[TOOL CALL] {tool_name}"
            )

            print(
                f"[ARGUMENTS] {arguments}"
            )

            # ---------------------------------------------
            # Execute Python tool
            # ---------------------------------------------

            try:

                raw_result = execute_tool(
                    tool_name,
                    arguments
                )

                result = make_json_safe(
                    raw_result
                )

            except Exception as e:

                result = {
                    "error": str(e)
                }

            # ---------------------------------------------
            # Save tool log
            # ---------------------------------------------

            tool_log.append(
                {
                    "tool": tool_name,
                    "input": arguments,
                    "result": result
                }
            )

            # ---------------------------------------------
            # Convert result to JSON text
            # ---------------------------------------------

            result_text = json.dumps(
                result,
                default=str
            )

            # Gemini Interactions API expects:
            #
            # {
            #     "type": "function_result",
            #     "name": "...",
            #     "call_id": "...",
            #     "result": [
            #         {
            #             "type": "text",
            #             "text": "..."
            #         }
            #     ]
            # }
            #
            # This matches Google's current
            # Interactions API function-calling format.

            function_results.append(
                {
                    "type": "function_result",
                    "name": tool_name,
                    "call_id": call.id,
                    "result": [
                        {
                            "type": "text",
                            "text": result_text
                        }
                    ]
                }
            )

        # -------------------------------------------------
        # Send tool results back to Gemini
        # -------------------------------------------------

        response = client.interactions.create(
            model=GEMINI_MODEL,
            previous_interaction_id=response.id,
            input=function_results,
            tools=GEMINI_TOOLS
        )

    # -----------------------------------------------------
    # Tool-call limit reached
    # -----------------------------------------------------

    return (
        "I wasn't able to finish that within my tool-call "
        "budget. Please narrow the question by specifying "
        "a sector or time period.",
        history + [
            {
                "role": "user",
                "content": message
            }
        ],
        tool_log
    )