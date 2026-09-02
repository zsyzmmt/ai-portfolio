#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Resume Kit HTTP API 服务（纯Python标准库实现，无需任何第三方依赖）
使resume-kit可以被任何AI平台通过HTTP调用
用法: python api_server.py --host 127.0.0.1 --port 8080
"""

import json
import os
import sys
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# 确保项目根目录在path中
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

import yaml


# ============================================================
# 全局组件（懒加载）
# ============================================================
_config = None
_kb = None
_llm = None
_generator = None
_auditor = None
_agent = None
_sse_clients = {}
_sse_counter = 0


def get_config():
    global _config
    if _config is None:
        config_path = PROJECT_ROOT / "config.yaml"
        with open(config_path, 'r', encoding='utf-8') as f:
            _config = yaml.safe_load(f)
    return _config


def get_kb():
    global _kb
    if _kb is None:
        from knowledge_base import KnowledgeBase
        _kb = KnowledgeBase(data_dir=str(PROJECT_ROOT / "data"))
    return _kb


def get_llm():
    global _llm
    if _llm is None:
        from resume_generator import LLMClient
        _llm = LLMClient(get_config().get("llm", {}))
    return _llm


def get_generator():
    global _generator
    if _generator is None:
        from resume_generator import ResumeGenerator
        _generator = ResumeGenerator(get_config(), knowledge_base=get_kb(), llm_client=get_llm())
    return _generator


def get_auditor():
    global _auditor
    if _auditor is None:
        from resume_generator import ResumeAuditor
        _auditor = ResumeAuditor(get_config(), knowledge_base=get_kb(), llm_client=get_llm())
    return _auditor


def get_agent():
    global _agent
    if _agent is None:
        from resume_generator import ResumeAgent
        _agent = ResumeAgent(get_config(), knowledge_base=get_kb(), llm_client=get_llm())
    return _agent


# ============================================================
# HTTP请求处理器
# ============================================================
class ResumeAPIHandler(BaseHTTPRequestHandler):
    """Resume Kit API请求处理器"""

    def log_message(self, format, *args):
        """简化日志输出"""
        print(f"[{self.log_date_time_string()}] {format % args}")

    def _send_json(self, data, status=200):
        """发送JSON响应"""
        body = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, message, status=500):
        """发送错误响应"""
        self._send_json({"error": message}, status=status)

    def _read_json_body(self):
        """读取JSON请求体"""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            return {}
        body = self.rfile.read(content_length)
        return json.loads(body.decode('utf-8'))

    def do_OPTIONS(self):
        """处理CORS预检请求"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        """处理GET请求"""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')

        try:
            if path == '/sse':
                self._handle_sse()
            elif path == '/api/health':
                self._handle_health()
            elif path == '/api/kb/stats':
                self._handle_kb_stats()
            elif path == '/api/kb/documents':
                self._handle_kb_documents()
            elif path == '/api/models':
                self._handle_models()
            elif path.startswith('/api/download/'):
                self._handle_download(path)
            elif path == '/docs' or path == '' or path == '/':
                self._handle_docs()
            else:
                self._send_error("Not Found", status=404)
        except Exception as e:
            self._send_error(str(e), status=500)

    def do_POST(self):
        """处理POST请求"""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')

        try:
            if path == '/api/generate':
                self._handle_generate()
            elif path == '/api/audit':
                self._handle_audit()
            elif path == '/api/agent':
                self._handle_agent()
            elif path == '/api/kb/search':
                self._handle_kb_search()
            elif path == '/api/kb/build-index':
                self._handle_kb_build_index()
            elif path == '/mcp/message':
                self._handle_mcp_message()
            elif path == '/mcp/message':
                self._handle_mcp_message()
            elif path == '/mcp':
                self._handle_mcp()
            else:
                self._send_error("Not Found", status=404)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_error(str(e), status=500)

    # ============================================================
    # 各端点处理
    # ============================================================
    def _handle_health(self):
        """健康检查"""
        self._send_json({
            "status": "ok",
            "service": "Resume Kit API",
            "version": "1.0.0",
            "knowledge_base_loaded": _kb is not None,
            "llm_loaded": _llm is not None
        })

    def _handle_docs(self):
        """API文档页面"""
        html = """<!DOCTYPE html>
<html>
<head><title>Resume Kit API</title>
<style>body{font-family:Arial;max-width:800px;margin:40px auto;padding:0 20px}
h1{color:#16213e}h2{color:#0f3460;margin-top:30px}
.endpoint{background:#f8f9fa;padding:15px;margin:10px 0;border-radius:8px;border-left:4px solid #16213e}
.method{display:inline-block;background:#16213e;color:white;padding:3px 10px;border-radius:4px;font-weight:bold;margin-right:10px}
.path{font-family:monospace;font-size:16px}
.desc{color:#666;margin-top:8px}</style></head>
<body>
<h1>Resume Kit API</h1>
<p>简历RAG工具包HTTP API服务</p>

<h2>简历生成</h2>
<div class="endpoint"><span class="method">POST</span><span class="path">/api/generate</span>
<div class="desc">生成简历。Body: {company, position, jd_text, use_rag?, render?}</div></div>

<div class="endpoint"><span class="method">POST</span><span class="path">/api/audit</span>
<div class="desc">审核简历。Body: {resume_json, jd_text?, company?, position?}</div></div>

<div class="endpoint"><span class="method">POST</span><span class="path">/api/agent</span>
<div class="desc">Agent模式：生成→审核→修改→循环，最多3轮。Body: {company, position, jd_text, use_rag?, render?, max_retries?, target_score?}</div></div>

<h2>知识库</h2>
<div class="endpoint"><span class="method">GET</span><span class="path">/api/kb/stats</span>
<div class="desc">知识库统计信息</div></div>

<div class="endpoint"><span class="method">GET</span><span class="path">/api/kb/documents</span>
<div class="desc">列出已添加的文档</div></div>

<div class="endpoint"><span class="method">POST</span><span class="path">/api/kb/search</span>
<div class="desc">语义检索。Body: {query, top_k?}</div></div>

<div class="endpoint"><span class="method">POST</span><span class="path">/api/kb/build-index</span>
<div class="desc">构建/重建向量索引</div></div>

<h2>其他</h2>
<div class="endpoint"><span class="method">GET</span><span class="path">/api/health</span>
<div class="desc">健康检查</div></div>

<div class="endpoint"><span class="method">GET</span><span class="path">/api/models</span>
<div class="desc">列出所有已配置的模型</div></div>

<div class="endpoint"><span class="method">GET</span><span class="path">/api/download/{file_path}</span>
<div class="desc">下载生成的文件</div></div>

</body></html>"""
        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_generate(self):
        """生成简历"""
        data = self._read_json_body()
        company = data.get("company", "")
        position = data.get("position", "")
        jd_text = data.get("jd_text", "")
        use_rag = data.get("use_rag", True)
        render = data.get("render", True)

        if not company or not position or not jd_text:
            self._send_error("company, position, jd_text are required", status=400)
            return

        generator = get_generator()
        result = generator.generate_and_save(
            company=company, position=position, jd_text=jd_text,
            use_rag=use_rag, render=render
        )

        self._send_json({
            "status": "success",
            "company": company,
            "position": position,
            "files": {"json": result.get("json"), "pdf": result.get("pdf"), "docx": result.get("docx")},
            "resume": result.get("resume")
        })

    def _handle_audit(self):
        """审核简历"""
        data = self._read_json_body()
        resume_json = data.get("resume_json", {})
        jd_text = data.get("jd_text", "")
        company = data.get("company", "")
        position = data.get("position", "")

        if not resume_json:
            self._send_error("resume_json is required", status=400)
            return

        auditor = get_auditor()
        audit_result = auditor.audit(
            resume_json=resume_json, jd_text=jd_text,
            company=company, position=position, auto_fix=False
        )

        self._send_json({
            "status": "success",
            "audit": audit_result,
            "passed": audit_result["overall"]["passed"],
            "score": audit_result["overall"]["weighted_score"]
        })

    def _handle_agent(self):
        """Agent模式"""
        data = self._read_json_body()
        company = data.get("company", "")
        position = data.get("position", "")
        jd_text = data.get("jd_text", "")
        use_rag = data.get("use_rag", True)
        render = data.get("render", True)
        max_retries = data.get("max_retries")
        target_score = data.get("target_score")

        if not company or not position or not jd_text:
            self._send_error("company, position, jd_text are required", status=400)
            return

        agent = get_agent()
        if max_retries:
            agent.max_retries = max_retries
        if target_score:
            agent.target_score = target_score

        result = agent.run(
            company=company, position=position, jd_text=jd_text,
            use_rag=use_rag, render=render
        )

        self._send_json({
            "status": "success",
            "company": company,
            "position": position,
            "iterations": result["iterations"],
            "final_score": result["final_score"],
            "passed": result["passed"],
            "files": result["files"],
            "final_resume": result["final_resume"],
            "final_audit": result["final_audit"]
        })

    def _handle_kb_stats(self):
        """知识库统计"""
        kb = get_kb()
        self._send_json(kb.stats())

    def _handle_kb_documents(self):
        """列出文档"""
        kb = get_kb()
        self._send_json({"documents": kb.list_documents()})

    def _handle_kb_search(self):
        """语义检索"""
        data = self._read_json_body()
        query = data.get("query", "")
        top_k = data.get("top_k", 8)

        if not query:
            self._send_error("query is required", status=400)
            return

        kb = get_kb()
        results = kb.search(query, top_k=top_k)
        self._send_json({"query": query, "count": len(results), "results": results})

    def _handle_kb_build_index(self):
        """构建索引"""
        kb = get_kb()
        success = kb.build_index()
        self._send_json({"status": "success" if success else "failed", "index_built": success})

    # ============================================================
    # MCP (Model Context Protocol) 支持
    # ============================================================

    def _handle_sse(self):
        """处理MCP SSE连接"""
        global _sse_counter
        _sse_counter += 1
        session_id = str(_sse_counter)

        print(f"[SSE] 新连接 session_id={session_id}")

        # 发送SSE响应头
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        # 保存客户端连接
        _sse_clients[session_id] = self.wfile

        # 发送endpoint事件（用相对路径，兼容更多MCP客户端）
        endpoint_url = f"/mcp/message?session_id={session_id}"
        endpoint_data = json.dumps({"endpoint": endpoint_url})
        self.wfile.write(f"event: endpoint\ndata: {endpoint_data}\n\n".encode('utf-8'))
        self.wfile.flush()

        print(f"[SSE] endpoint已发送: {endpoint_url}")

        # 保持连接，定期发送心跳
        import time
        try:
            while session_id in _sse_clients:
                time.sleep(30)
                if session_id in _sse_clients:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            print(f"[SSE] 连接断开 session_id={session_id}")
        finally:
            if session_id in _sse_clients:
                del _sse_clients[session_id]

    def _handle_mcp_message(self):
        """处理MCP消息（通过SSE推送响应）"""
        # 从URL参数获取session_id
        parsed = urlparse(self.path)
        query_params = parse_qs(parsed.query)
        session_id = query_params.get('session_id', [''])[0]

        if not session_id or session_id not in _sse_clients:
            self._send_error("Invalid or expired session_id", status=400)
            return

        data = self._read_json_body()
        method = data.get("method", "")
        req_id = data.get("id")
        params = data.get("params", {})

        print(f"[MCP-SSE] method={method}, id={req_id}, session={session_id}")

        try:
            if method == "initialize":
                result = self._mcp_initialize(params)
            elif method == "tools/list":
                result = self._mcp_tools_list(params)
            elif method == "tools/call":
                result = self._mcp_tools_call(params)
            elif method == "notifications/initialized":
                # 通知不需要响应
                self.send_response(202)
                self.end_headers()
                return
            elif method == "ping":
                result = {}
            else:
                result = None
                error_resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                }
                self._sse_send(session_id, error_resp)
                self.send_response(202)
                self.end_headers()
                return

            # 通过SSE推送响应
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result
            }
            self._sse_send(session_id, response)

            # HTTP返回202 Accepted
            self.send_response(202)
            self.end_headers()

        except Exception as e:
            import traceback
            traceback.print_exc()
            error_resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(e)}
            }
            self._sse_send(session_id, error_resp)
            self.send_response(202)
            self.end_headers()

    def _sse_send(self, session_id, message):
        """通过SSE连接推送消息"""
        if session_id in _sse_clients:
            wfile = _sse_clients[session_id]
            data = json.dumps(message, ensure_ascii=False)
            wfile.write(f"data: {data}\n\n".encode('utf-8'))
            wfile.flush()
            print(f"[SSE] 已推送响应 session_id={session_id}")

    def _handle_mcp(self):
        """处理MCP Streamable HTTP请求（JSON-RPC 2.0）"""
        data = self._read_json_body()
        method = data.get("method", "")
        req_id = data.get("id")
        params = data.get("params", {})

        # 获取客户端协议版本
        client_version = self.headers.get('MCP-Protocol-Version', '2025-06-18')
        print(f"[MCP-Streamable] method={method}, id={req_id}, version={client_version}")

        # 通知（没有id）直接返回202 Accepted
        if req_id is None:
            if method == "notifications/initialized":
                print("[MCP] 客户端初始化完成")
            self.send_response(202)
            self.send_header('MCP-Protocol-Version', '2025-06-18')
            self.end_headers()
            return

        try:
            if method == "initialize":
                result = self._mcp_initialize(params)
            elif method == "tools/list":
                result = self._mcp_tools_list(params)
            elif method == "tools/call":
                result = self._mcp_tools_call(params)
            elif method == "ping":
                result = {}
            else:
                self._mcp_send_streamable_error(req_id, -32601, f"Method not found: {method}")
                return

            self._mcp_send_streamable_response(req_id, result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._mcp_send_streamable_error(req_id, -32000, str(e))

    def _mcp_send_streamable_response(self, req_id, result):
        """发送MCP Streamable HTTP响应"""
        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result
        }
        body = json.dumps(response, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('MCP-Protocol-Version', '2025-06-18')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, MCP-Protocol-Version')
        self.end_headers()
        self.wfile.write(body)

    def _mcp_send_streamable_error(self, req_id, code, message):
        """发送MCP Streamable HTTP错误响应"""
        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": code,
                "message": message
            }
        }
        body = json.dumps(response, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('MCP-Protocol-Version', '2025-06-18')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _mcp_initialize(self, params):
        """MCP初始化握手"""
        return {
            "protocolVersion": "2025-06-18",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "Resume Kit MCP Server",
                "version": "1.0.0"
            }
        }

    def _mcp_tools_list(self, params):
        """列出MCP可用工具"""
        return {
            "tools": [
                {
                    "name": "generate_resume",
                    "description": "根据岗位JD生成定制化简历，输出PDF和DOCX文件。基于RAG知识库检索个人经历，确保内容真实可追溯。",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "company": {"type": "string", "description": "目标公司名称"},
                            "position": {"type": "string", "description": "目标岗位名称"},
                            "jd_text": {"type": "string", "description": "岗位JD全文"},
                            "use_rag": {"type": "boolean", "description": "是否使用知识库检索，默认true"},
                            "render": {"type": "boolean", "description": "是否渲染PDF/DOCX，默认true"}
                        },
                        "required": ["company", "position", "jd_text"]
                    }
                },
                {
                    "name": "audit_resume",
                    "description": "审核简历质量，从三个维度打分：相似度检测（防照搬上一份）、真实性检测（防编造）、JD匹配度检测。返回审核报告和修改建议。",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "resume_json": {"type": "object", "description": "简历JSON内容"},
                            "jd_text": {"type": "string", "description": "岗位JD全文（可选）"},
                            "company": {"type": "string", "description": "公司名（可选）"},
                            "position": {"type": "string", "description": "岗位名（可选）"}
                        },
                        "required": ["resume_json"]
                    }
                },
                {
                    "name": "agent_resume",
                    "description": "Agent模式：自动生成简历→审核→修改→循环，最多3轮迭代直至通过审核阈值。返回最终简历、审核报告和生成的PDF/DOCX文件路径。",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "company": {"type": "string", "description": "目标公司名称"},
                            "position": {"type": "string", "description": "目标岗位名称"},
                            "jd_text": {"type": "string", "description": "岗位JD全文"},
                            "use_rag": {"type": "boolean", "description": "是否使用知识库检索，默认true"},
                            "render": {"type": "boolean", "description": "是否渲染PDF/DOCX，默认true"},
                            "max_retries": {"type": "integer", "description": "最大迭代次数，默认3"},
                            "target_score": {"type": "number", "description": "目标审核分数阈值，默认80"}
                        },
                        "required": ["company", "position", "jd_text"]
                    }
                }
            ]
        }

    def _mcp_tools_call(self, params):
        """调用MCP工具"""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        print(f"[MCP] calling tool: {tool_name}, args keys: {list(arguments.keys())}")

        if tool_name == "generate_resume":
            result = get_generator().generate_and_save(
                company=arguments.get("company", ""),
                position=arguments.get("position", ""),
                jd_text=arguments.get("jd_text", ""),
                use_rag=arguments.get("use_rag", True),
                render=arguments.get("render", True)
            )
            text = f"简历生成成功！\n公司: {arguments.get('company')}\n岗位: {arguments.get('position')}\n\n生成文件:\n- JSON: {result.get('json', 'N/A')}\n- PDF: {result.get('pdf', 'N/A')}\n- DOCX: {result.get('docx', 'N/A')}"

        elif tool_name == "audit_resume":
            audit_result = get_auditor().audit(
                resume_json=arguments.get("resume_json", {}),
                jd_text=arguments.get("jd_text", ""),
                company=arguments.get("company", ""),
                position=arguments.get("position", ""),
                auto_fix=False
            )
            overall = audit_result.get("overall", {})
            text = f"简历审核完成！\n\n综合得分: {overall.get('weighted_score', 'N/A')}/100\n是否通过: {'是' if overall.get('passed') else '否'}\n\n各维度得分:\n- 相似度: {audit_result.get('similarity', {}).get('score', 'N/A')}\n- 真实性: {audit_result.get('authenticity', {}).get('score', 'N/A')}\n- JD匹配度: {audit_result.get('jd_match', {}).get('score', 'N/A')}"

        elif tool_name == "agent_resume":
            agent = get_agent()
            if arguments.get("max_retries"):
                agent.max_retries = arguments["max_retries"]
            if arguments.get("target_score"):
                agent.target_score = arguments["target_score"]

            result = agent.run(
                company=arguments.get("company", ""),
                position=arguments.get("position", ""),
                jd_text=arguments.get("jd_text", ""),
                use_rag=arguments.get("use_rag", True),
                render=arguments.get("render", True)
            )
            files = result.get("files", {})
            text = f"Agent模式完成！\n公司: {arguments.get('company')}\n岗位: {arguments.get('position')}\n\n迭代次数: {result.get('iterations', 0)}\n最终得分: {result.get('final_score', 'N/A')}\n是否通过: {'是' if result.get('passed') else '否'}\n\n生成文件:\n- JSON: {files.get('json', 'N/A')}\n- PDF: {files.get('pdf', 'N/A')}\n- DOCX: {files.get('docx', 'N/A')}"

        else:
            text = f"未知工具: {tool_name}"

        return {
            "content": [
                {"type": "text", "text": text}
            ]
        }

    def _mcp_send_response(self, req_id, result):
        """发送MCP JSON-RPC响应"""
        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result
        }
        body = json.dumps(response, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(body)

    def _mcp_send_error(self, req_id, code, message):
        """发送MCP JSON-RPC错误响应"""
        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": code,
                "message": message
            }
        }
        body = json.dumps(response, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _handle_models(self):
        """列出模型"""
        llm = get_llm()
        self._send_json({
            "current": llm.get_current_model(),
            "available": llm.list_available_models(),
            "current_info": llm.get_model_info()
        })

    def _handle_download(self, path):
        """下载文件"""
        file_path = path.replace('/api/download/', '', 1)
        full_path = PROJECT_ROOT / file_path

        if not full_path.exists() or not full_path.is_file():
            self._send_error("File not found", status=404)
            return

        with open(full_path, 'rb') as f:
            content = f.read()

        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Disposition', f'attachment; filename="{full_path.name}"')
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(content)


# ============================================================
# 启动
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Resume Kit API Server")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8080, help="监听端口")
    args = parser.parse_args()

    print("=" * 50)
    print("  Resume Kit API Server 启动中...")
    print("=" * 50)
    print(f"  服务地址: http://{args.host}:{args.port}")
    print(f"  API文档:  http://{args.host}:{args.port}/docs")
    print(f"  健康检查: http://{args.host}:{args.port}/api/health")
    print()
    print("  关闭此窗口即停止服务")
    print("=" * 50)
    print()

    server = ThreadingHTTPServer((args.host, args.port), ResumeAPIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.server_close()


if __name__ == "__main__":
    main()
