#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多模型LLM客户端：支持OpenAI兼容API和Anthropic Claude
通过配置文件切换模型，额度用完后可无缝切换到其他模型
"""

import json
import time
from typing import List, Dict, Optional, Any


class LLMClient:
    """统一的LLM客户端"""

    def __init__(self, config: Dict):
        """
        Args:
            config: LLM配置字典，来自config.yaml的llm部分
        """
        self.config = config
        self.active_model = config.get("active_model", "deepseek")
        self.models = config.get("models", {})

        if self.active_model not in self.models:
            raise ValueError(
                f"未找到模型配置: {self.active_model}\n"
                f"可用模型: {list(self.models.keys())}"
            )

        self.model_config = self.models[self.active_model]
        self.model_type = self.model_config.get("type", "openai_compatible")
        self._client = None

        print(f"[LLM] 当前模型: {self.active_model} ({self.model_type})")

    def switch_model(self, model_name: str):
        """
        切换到另一个模型

        Args:
            model_name: 模型名称（必须在config中已配置）
        """
        if model_name not in self.models:
            raise ValueError(f"未找到模型配置: {model_name}")
        self.active_model = model_name
        self.model_config = self.models[model_name]
        self.model_type = self.model_config.get("type", "openai_compatible")
        self._client = None
        print(f"[LLM] 切换到: {model_name} ({self.model_type})")

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        发送聊天请求

        Args:
            messages: 消息列表，格式 [{"role": "system/user/assistant", "content": "..."}]
            **kwargs: 额外参数（temperature, max_tokens等）

        Returns:
            str: 模型回复文本
        """
        if self.model_type == "openai_compatible":
            return self._chat_openai(messages, **kwargs)
        elif self.model_type == "anthropic":
            return self._chat_anthropic(messages, **kwargs)
        else:
            raise ValueError(f"不支持的模型类型: {self.model_type}")

    def chat_with_retry(self, messages: List[Dict[str, str]], max_retries: int = 3, **kwargs) -> str:
        """
        带重试的聊天请求（处理网络错误、限流等）

        Args:
            messages: 消息列表
            max_retries: 最大重试次数
            **kwargs: 额外参数

        Returns:
            str: 模型回复文本
        """
        last_error = None
        for attempt in range(max_retries):
            try:
                return self.chat(messages, **kwargs)
            except Exception as e:
                last_error = e
                wait_time = (attempt + 1) * 2
                print(f"[LLM] 第{attempt+1}次请求失败: {e}，{wait_time}秒后重试...")
                time.sleep(wait_time)

        raise RuntimeError(f"LLM请求失败（已重试{max_retries}次）: {last_error}")

    def chat_with_fallback(self, messages: List[Dict[str, str]], fallback_models: Optional[List[str]] = None, **kwargs) -> str:
        """
        带模型降级的聊天请求（当前模型失败时自动切换到备用模型）

        Args:
            messages: 消息列表
            fallback_models: 备用模型列表（按优先级排序），默认使用config中除当前模型外的所有模型
            **kwargs: 额外参数

        Returns:
            str: 模型回复文本
        """
        # 尝试当前模型
        try:
            return self.chat(messages, **kwargs)
        except Exception as e:
            print(f"[LLM] 当前模型 {self.active_model} 失败: {e}")

        # 确定备用模型列表
        if fallback_models is None:
            fallback_models = [m for m in self.models.keys() if m != self.active_model]

        # 依次尝试备用模型
        original_model = self.active_model
        for model in fallback_models:
            try:
                print(f"[LLM] 尝试备用模型: {model}")
                self.switch_model(model)
                result = self.chat(messages, **kwargs)
                print(f"[LLM] 备用模型 {model} 成功")
                return result
            except Exception as e:
                print(f"[LLM] 备用模型 {model} 失败: {e}")
                continue

        # 所有模型都失败，切回原模型
        self.switch_model(original_model)
        raise RuntimeError("所有模型均请求失败")

    # ============================================================
    # OpenAI 兼容接口
    # ============================================================
    def _chat_openai(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """使用OpenAI兼容API"""
        client = self._get_openai_client()

        response = client.chat.completions.create(
            model=self.model_config.get("model", "gpt-4o-mini"),
            messages=messages,
            temperature=kwargs.get("temperature", self.model_config.get("temperature", 0.3)),
            max_tokens=kwargs.get("max_tokens", self.model_config.get("max_tokens", 4096)),
            top_p=kwargs.get("top_p", 1.0),
            stream=kwargs.get("stream", False)
        )

        return response.choices[0].message.content

    def _get_openai_client(self):
        """获取OpenAI客户端（懒加载）"""
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError:
                raise ImportError("openai 库未安装。请运行: pip install openai")

            api_key = self.model_config.get("api_key", "")
            base_url = self.model_config.get("base_url", "https://api.openai.com/v1")

            if not api_key or api_key.startswith("your-"):
                raise ValueError(
                    f"模型 {self.active_model} 的API密钥未配置。\n"
                    f"请在config.yaml中设置 llm.models.{self.active_model}.api_key"
                )

            self._client = OpenAI(api_key=api_key, base_url=base_url)
        return self._client

    # ============================================================
    # Anthropic Claude 接口
    # ============================================================
    def _chat_anthropic(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """使用Anthropic Claude API"""
        client = self._get_anthropic_client()

        # 分离system消息
        system_messages = [m["content"] for m in messages if m["role"] == "system"]
        other_messages = [m for m in messages if m["role"] != "system"]

        response = client.messages.create(
            model=self.model_config.get("model", "claude-3-5-sonnet-20241022"),
            max_tokens=kwargs.get("max_tokens", self.model_config.get("max_tokens", 4096)),
            temperature=kwargs.get("temperature", self.model_config.get("temperature", 0.3)),
            system="\n\n".join(system_messages) if system_messages else None,
            messages=other_messages
        )

        # 提取文本内容
        text_parts = [block.text for block in response.content if block.type == "text"]
        return "\n".join(text_parts)

    def _get_anthropic_client(self):
        """获取Anthropic客户端（懒加载）"""
        if self._client is None:
            try:
                import anthropic
            except ImportError:
                raise ImportError("anthropic 库未安装。请运行: pip install anthropic")

            api_key = self.model_config.get("api_key", "")
            if not api_key or api_key.startswith("your-"):
                raise ValueError(
                    f"模型 {self.active_model} 的API密钥未配置。\n"
                    f"请在config.yaml中设置 llm.models.{self.active_model}.api_key"
                )

            self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    # ============================================================
    # 工具方法
    # ============================================================
    def list_available_models(self) -> List[str]:
        """列出所有已配置的模型"""
        return list(self.models.keys())

    def get_current_model(self) -> str:
        """获取当前模型名称"""
        return self.active_model

    def get_model_info(self) -> Dict:
        """获取当前模型信息"""
        return {
            "name": self.active_model,
            "type": self.model_type,
            "model": self.model_config.get("model", ""),
            "base_url": self.model_config.get("base_url", "")
        }

    def extract_json(self, text: str) -> Any:
        """
        从模型回复中提取JSON（处理markdown代码块等包装）

        Args:
            text: 模型回复文本

        Returns:
            解析后的JSON对象
        """
        text = text.strip()

        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取 ```json ... ``` 代码块
        import re
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 尝试提取第一个 { 到最后一个 }
        brace_start = text.find('{')
        brace_end = text.rfind('}')
        if brace_start >= 0 and brace_end > brace_start:
            try:
                return json.loads(text[brace_start:brace_end + 1])
            except json.JSONDecodeError:
                pass

        raise ValueError(f"无法从文本中提取JSON: {text[:200]}...")
