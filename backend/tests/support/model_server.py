"""Deterministic OpenAI HTTP fixture. Never imported by application code."""

import base64
import json
import struct
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

from extraction_fixture import extracted_order, screenshot


class ModelHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # Do not print request bodies, Authorization or image data.

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        messages = body["messages"]
        system = messages[0]["content"]
        tool_calls = None
        if "范围分类器" in system:
            scope = json.loads(messages[-1]["content"])
            content = json.dumps(
                {
                    "decision": "ALLOW",
                    "reason_code": "IN_SCOPE",
                    "requested_operation": "GENERATE" if scope["agent_type"] == "SCHEDULING" else "QUERY",
                }
            )
        elif "【任务】看聊天截图" in system:
            assert any(
                part.get("type") == "image_url"
                for m in messages
                if isinstance(m["content"], list)
                for part in m["content"]
            )
            # Give the browser enough time to observe a persisted running task.
            time.sleep(0.5)
            image = next(
                part["image_url"]["url"]
                for m in messages
                if isinstance(m["content"], list)
                for part in m["content"]
                if part.get("type") == "image_url"
            )
            # A distinct valid 1px PNG is the two-order synthetic fixture.
            multi = struct.unpack(">I", base64.b64decode(image.split(",", 1)[1])[16:20])[0] == 1
            raw = extracted_order(
                customer_name=None if multi else "联调客户",
                product_description="透明薄膜" if multi else "透明膜",
                quantity=250,
                quantity_unit="kg",
                width_inferred=multi,
                thickness_inferred=multi,
                notes="不要多-包含损耗" if multi else None,
            )
            second = extracted_order(
                customer_name="联调客户",
                product_description="透明膜",
                width=60.5,
                quantity=600,
                quantity_unit="kg",
                width_inferred=True,
                thickness_inferred=True,
            )
            result = screenshot(raw, second) if multi else screenshot(raw)
            if multi:
                result["context_text"] = "订单群；联调客户跟单发来的订单"
            catalog = json.loads(messages[1]["content"][0]["text"])["catalog"]
            for order in result["orders"]:
                for field, label, evidence in (
                    ("customer_id", "联调客户", "联调客户跟单" if multi else "联调客户"),
                    ("product_id", "透明膜", order["product_description"]),
                ):
                    candidate = next(c for c in catalog[field] if c["label"] == label)
                    order[field.replace("_id", "_match")] = dict(
                        candidate_id=candidate["id"],
                        confidence=0.97,
                        runner_up_confidence=0.1,
                        evidence=evidence,
                        reason="截图归属与候选相符",
                    )
            content = json.dumps(result)
        elif "排单说明助手" in system:
            content = "根据规格和配方匹配机器，新增任务排在已有任务之后，请核对后确认。"
        elif body.get("tools"):
            if messages[-1]["role"] != "tool":
                names = {tool["function"]["name"] for tool in body["tools"]}
                name = "read_current_draft" if "read_current_draft" in names else "read_draft"
                assert name in names
                tool_calls = [
                    {
                        "id": f"call_{uuid4().hex}",
                        "type": "function",
                        "function": {"name": name, "arguments": "{}"},
                    }
                ]
                content = None
            else:
                content = "已读取当前草稿，请核对。"
        elif "根据本轮已验证" in system:
            content = "草稿已准备好，请在右侧核对并确认。"
        else:
            self.send_error(400, "Unexpected model call in integration fixture")
            return

        base = {"id": f"chatcmpl-{uuid4().hex}", "created": int(time.time()), "model": "filmos-test-model"}
        self.send_response(200)
        if body.get("stream"):
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.end_headers()
            for fragment in [content[:8], content[8:]]:
                event = {
                    **base,
                    "object": "chat.completion.chunk",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": fragment},
                            "finish_reason": None,
                        }
                    ],
                }
                self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
            event = {
                **base,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            self.wfile.write(f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n".encode())
            self.wfile.flush()
        else:
            message = {"role": "assistant", "content": content}
            if tool_calls:
                message["tool_calls"] = tool_calls
            payload = {
                **base,
                "object": "chat.completion",
                "choices": [
                    {"index": 0, "message": message, "finish_reason": "tool_calls" if tool_calls else "stop"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            }
            encoded = json.dumps(payload).encode()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)


def model_server(port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), ModelHandler)
