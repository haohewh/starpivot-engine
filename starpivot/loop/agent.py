
# ═══════════════════════════════════════════════════════════════════
# 核心入口
# ═══════════════════════════════════════════════════════════════════

def agent_turn(agent_id: str, user_input: str) -> Dict[str, Any]:
    """执行一轮 Agent 推理：Think → Act → Observe → Persist。

    Args:
        agent_id: Agent 唯一标识符。
        user_input: 用户本轮输入文本。

    Returns:
        dict:
            - content:           assistant 回复内容（成功时）。
            - credits_remaining: 剩余余额（积分）。
            - error:            错误信息（仅失败时出现）。
            - tool_calls:       工具调用记录（如有）。
    """
    result = agent_turn_with_tools(agent_id, user_input)
    return result


# ═══════════════════════════════════════════════════════════════════
# 工具格式化
# ═══════════════════════════════════════════════════════════════════

def _tools_to_openai_format(tools_list: list[dict]) -> list[dict]:
    """将工具列表转换为 OpenAI function calling 格式。"""
    openai_tools = []
    for tool in tools_list:
        properties = {}
        required = []
        for param in tool.get("parameters", []):
            properties[param["name"]] = {
                "type": param.get("type", "string"),
                "description": param.get("description", ""),
            }
            if param.get("required", False):
                required.append(param["name"])

        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                },
            },
        })
        if required:
            openai_tools[-1]["function"]["parameters"]["required"] = required

    return openai_tools


# ═══════════════════════════════════════════════════════════════════
# 主流程（重写版）
# ═══════════════════════════════════════════════════════════════════

def agent_turn_with_tools(
    agent_id: str,
    user_input: str,
    available_tools: list[dict] | None = None,
    max_tool_rounds: int = 3,
) -> Dict[str, Any]:
    """执行一轮 Agent 推理（重写版：快准稳）。

    流程决策树：
    ┌─ 搜索类请求 ──→ 星枢引擎搜索（agent_reach_search）─→ AI 总结（无工具）
    │
    ├─ 非搜索工具类 ──→ function calling（星枢引擎调度，≤3 轮）
    │
    └─ 纯对话 ──→ 直接 AI 回答（无工具）

    Args:
        agent_id: Agent 唯一标识符。
        user_input: 用户本轮输入文本。
        available_tools: 可选的自定义工具列表。
        max_tool_rounds: 最大工具调用轮数（默认 3）。

    Returns:
        dict:
            - content:           最终 assistant 回复内容。
            - credits_remaining: 剩余余额。
            - tool_calls:        工具调用记录列表。
            - error:             错误信息（仅失败时出现）。
    """
    db = get_db()

    # ── 1. 加载 Agent ──
    agent = db.get_agent(agent_id)
    if agent is None:
        return {"content": "", "credits_remaining": 0, "error": f"Agent 不存在: {agent_id}"}

    # ── 2. 检查 Agent 状态 ──
    if agent["status"] == "dead":
        return {
            "content": "",
            "credits_remaining": agent["balance_cents"],
            "error": f"Agent {agent['name']} 已死亡，无法执行推理。",
        }
    if agent["status"] == "paused":
        return {
            "content": "",
            "credits_remaining": agent["balance_cents"],
            "error": f"Agent {agent['name']} 已暂停，无法执行推理。",
        }

    # ── 3. 扣生存费 ──
    turn_cost = config.settings.turn_cost
    try:
        new_balance = db.adjust_balance(agent_id, -turn_cost, entity_type="agent")
    except ValueError as e:
        return {"content": "", "credits_remaining": agent["balance_cents"], "error": str(e)}

    # ── 4. 构建系统提示词（含 SOUL.md + 铁律 + 记忆注入） ──
    user_id = agent.get("user_id", "")
    system_prompt = _build_system_prompt(agent, new_balance, user_id=user_id, user_input=user_input)

    # ── 4b. 旧版跨会话记忆（兼容） ──
    agent_memory = AgentMemory(agent_id, user_id)
    system_prompt = agent_memory.inject_memories(system_prompt)

    # ── 5. 开始新对话记录 ──
    conversation_id = agent_memory.start_conversation()

    # ── 5b. 记录用户消息 ──
    db.create_message(agent_id, "user", user_input)

    # ── 6. 确定 API 配置 ──
    api_key = agent.get("api_key") or config.settings.deepseek_api_key
    base_url = config.settings.deepseek_base_url
    model = agent.get("api_model") or config.settings.default_model

    today_str = datetime.now().strftime("%Y年%m月%d日")

    # ═══════════════════════════════════════════════════════════════
    # 路径一：搜索类请求 — 星枢引擎搜索 + AI 总结
    # ═══════════════════════════════════════════════════════════════
    if _is_search_query(user_input):
        logger.info("[搜索路径] %s: %s", agent_id, user_input[:50])
        try:
            result = _sync_execute(
                "agent_reach_search",
                {"query": user_input[:40]},
                {"agent_id": agent_id},
            )
            if result.get("success"):
                search_result = result.get("output", "")
            else:
                search_result = f"搜索失败: {result.get('error', '未知错误')}"
        except Exception as e:
            logger.error("智能搜索失败: %s", e)
            search_result = f"搜索失败: {e}"

        # 构建消息：系统提示 + 搜索数据注入 + 用户问题
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"今天是 {today_str}。\n\n"
                    f"以下是为你的问题「{user_input}」搜索到的实时信息：\n\n"
                    f"{search_result}\n\n"
                    "请根据以上搜索结果，用中文简洁、清晰地回答用户的问题。"
                    "引用来源时标注来源（如【百度热搜】【今日热榜】【网络搜索】）。"
                    "如果搜索结果中没有相关信息，请如实说明。"
                ),
            },
        ]

        try:
            content = _call_deepseek(
                messages=messages,
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout=15,
            )
        except RuntimeError as e:
            logger.error("搜索总结失败: %s", e)
            # 降级：直接返回搜索结果
            content = search_result
            db.create_message(agent_id, "assistant", content)
            agent_memory.summarize_conversation(messages=messages, conversation_id=conversation_id)
            return {"content": content, "credits_remaining": new_balance, "tool_calls": []}

        db.create_message(agent_id, "assistant", content)
        agent_memory.summarize_conversation(messages=messages, conversation_id=conversation_id)
        # ── 保存热记忆 + 提取温记忆 ──
        _save_conversation_memory(agent_id, user_id, user_input, content, messages=messages)
        return {"content": content, "credits_remaining": new_balance, "tool_calls": []}

    # ═══════════════════════════════════════════════════════════════
    # 路径二：非搜索工具类 — function calling（≤3 工具）
    # ═══════════════════════════════════════════════════════════════
    if _needs_non_search_tools(user_input):
        logger.info("[工具路径] %s: %s", agent_id, user_input[:50])

        # 从星枢引擎加载工具列表，转为 OpenAI function calling 格式
        _init_starpivot()
        from core.starpivot.translator import ModelTranslator
        all_tools = _registry.list_tools()
        openai_tools = ModelTranslator.to_deepseek(all_tools) if all_tools else []
        logger.info("星枢引擎提供 %d 个工具", len(all_tools))

        messages: list = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"今天是 {today_str}。\n\n{user_input}"},
        ]

        tool_call_records: list[dict] = []
        final_content = ""
        current_tool_round = 0

        while current_tool_round <= max_tool_rounds:
            logger.info("工具循环 %d/%d", current_tool_round + 1, max_tool_rounds)
            try:
                content, tool_calls, full_message = _call_deepseek_full(
                    messages=messages,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    tools=openai_tools,
                    timeout=15,
                )
            except RuntimeError as e:
                logger.error("DeepSeek API 调用失败: %s", e)
                db.create_message(agent_id, "assistant", f"[错误] {e}")
                return {"content": "", "credits_remaining": new_balance, "error": str(e), "tool_calls": tool_call_records}

            # 添加 assistant 响应
            assistant_msg = {"role": "assistant", "content": content}
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ]
            messages.append(assistant_msg)

            # 处理 XML 格式 tool_calls（DeepSeek 不稳定时）
            if not tool_calls and content and "<tool_calls>" in content:
                xml_match = re.search(
                    r'<invoke name="(\w+)">(.*?)</invoke>', content, re.DOTALL
                )
                if xml_match:
                    func_name = xml_match.group(1)
                    args_text = xml_match.group(2)
                    args = {}
                    for p in re.finditer(
                        r'<parameter name="(\w+)"[^>]*>(.*?)</parameter>',
                        args_text, re.DOTALL,
                    ):
                        args[p.group(1)] = p.group(2).strip()
                    from types import SimpleNamespace
                    tc = SimpleNamespace()
                    tc.id = "call_" + str(hash(content))[:10]
                    tc.function = SimpleNamespace()
                    tc.function.name = func_name
                    tc.function.arguments = json.dumps(args, ensure_ascii=False)
                    tool_calls = [tc]
                    content = re.sub(
                        r'<tool_calls>.*?</tool_calls>', '', content,
                        flags=re.DOTALL,
                    ).strip()
                    # 替换消息
                    messages[-1] = {
                        "role": "assistant",
                        "content": content,
                        "tool_calls": [{
                            "id": tc.id, "type": "function",
                            "function": {"name": func_name, "arguments": tc.function.arguments},
                        }],
                    }
                    continue

            # 无 tool_calls → 最终回复
            if not tool_calls:
                final_content = content or ""
                db.create_message(agent_id, "assistant", final_content)
                break

            # 执行工具（通过星枢引擎）
            current_tool_round += 1
            for tc in tool_calls:
                func_name = tc.function.name
                try:
                    func_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError as e:
                    func_args = {}
                    logger.warning("工具 %s 参数解析失败: %s", func_name, e)

                result = _sync_execute(func_name, func_args, {"agent_id": agent_id})

                record = {
                    "tool_call_id": tc.id,
                    "name": func_name,
                    "arguments": func_args,
                    "result": result,
                }
                tool_call_records.append(record)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result.get("output", "") or result.get("error", ""),
                })

                db.create_message(
                    agent_id,
                    "tool",
                    f"[{func_name}] args={func_args} → success={result.get('success', False)} output={result.get('output', '')[:200]}",
                )

            if current_tool_round >= max_tool_rounds:
                logger.info("Agent %s 达到最大工具轮数，强制总结", agent_id)
                try:
                    content = _call_deepseek(
                        messages=messages,
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        timeout=15,
                    )
                    final_content = content or ""
                except RuntimeError:
                    final_content = ""
                db.create_message(agent_id, "assistant", final_content)
                break

        agent_memory.summarize_conversation(messages=messages, conversation_id=conversation_id)
        # ── 保存热记忆 + 提取温记忆 ──
        _save_conversation_memory(agent_id, user_id, user_input, final_content, messages=messages)
        return {
            "content": final_content,
            "credits_remaining": new_balance,
            "tool_calls": tool_call_records,
        }

    # ═══════════════════════════════════════════════════════════════
    # 路径三：纯对话 — 直接 AI 回答，无工具
    # ═══════════════════════════════════════════════════════════════
    logger.info("[对话路径] %s: %s", agent_id, user_input[:50])
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]

    try:
        content = _call_deepseek(
            messages=messages,
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=15,
        )
    except RuntimeError as e:
        logger.error("DeepSeek API 调用失败: %s", e)
        db.create_message(agent_id, "assistant", f"[错误] {e}")
        agent_memory.summarize_conversation(messages=messages, conversation_id=conversation_id)
        return {"content": "", "credits_remaining": new_balance, "error": str(e)}

    db.create_message(agent_id, "assistant", content)
    agent_memory.summarize_conversation(messages=messages, conversation_id=conversation_id)
    # ── 保存热记忆 + 提取温记忆 ──
    _save_conversation_memory(agent_id, user_id, user_input, content, messages=messages)
    return {"content": content, "credits_remaining": new_balance, "tool_calls": []}


# ═══════════════════════════════════════════════════════════════
# 流式 API 调用 — SSE (Server-Sent Events) 支持
# ═══════════════════════════════════════════════════════════════════


def _call_deepseek_stream(
    messages: list,
    api_key: str,
    base_url: str,
    model: str,
    tools: list | None = None,
    timeout: int = 30,
) -> str:
    """流式调用 DeepSeek API，逐 chunk 打印日志，返回完整内容。

    Args:
        messages: 符合 OpenAI 格式的消息列表。
        api_key: DeepSeek API Key。
        base_url: API 基础地址。
        model: 模型名称。
        tools: 可选的工具定义。
        timeout: 请求超时秒数（默认 30）。

    Returns:
        API 返回的完整 assistant 消息 content。

    Raises:
        RuntimeError: API 调用失败时抛出。
    """
    kwargs: dict = dict(
        model=model,
        messages=messages,
        temperature=0.7,
        max_tokens=4000,
        timeout=timeout,
        stream=True,
    )
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(**kwargs)
    except Exception as e:
        raise RuntimeError(f"DeepSeek 流式 API 调用失败: {e}")

    full_content: list[str] = []
    tool_calls_data: dict[int, dict] = {}
    finish_reason: str | None = None

    for chunk in response:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta is None:
            continue

        # 文本内容
        if delta.content:
            full_content.append(delta.content)

        # tool_calls（function calling 场景）
        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in tool_calls_data:
                    tool_calls_data[idx] = {
                        "id": tc.id or "",
                        "function": {"name": "", "arguments": ""},
                    }
                if tc.id:
                    tool_calls_data[idx]["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        tool_calls_data[idx]["function"]["name"] += tc.function.name
                    if tc.function.arguments:
                        tool_calls_data[idx]["function"]["arguments"] += tc.function.arguments

        # 记录结束原因
        fc = chunk.choices[0].finish_reason if chunk.choices else None
        if fc:
            finish_reason = fc

    logger.info(
        "流式 API: finish_reason=%s, content_len=%d, tool_calls=%d",
        finish_reason, len("".join(full_content)), len(tool_calls_data),
    )
    return "".join(full_content), list(tool_calls_data.values()) if tool_calls_data else None


def agent_stream(
    agent_id: str,
    user_input: str,
    available_tools: list[dict] | None = None,
    max_tool_rounds: int = 3,
):
    """流式 Agent 执行生成器，沿途推送 SSE 事件。

    在每个阶段 yield 事件字典，由 FastAPI StreamingResponse 序列化为 SSE。

    Yields:
        dict: {"type": str, "content": str}
            - type="thinking":  AI 正在思考
            - type="tool":      正在调用工具（含工具名）
            - type="tool_result": 工具执行结果摘要
            - type="text":      AI 回复文本（逐 chunk）
            - type="done":      执行完成
            - type="error":     执行出错
    """
    db = get_db()

    # ── 1. 加载 Agent ──
    agent = db.get_agent(agent_id)
    if agent is None:
        yield {"type": "error", "content": f"Agent 不存在: {agent_id}"}
        return

    if agent["status"] == "dead":
        yield {"type": "error", "content": f"Agent {agent['name']} 已死亡，无法执行推理。"}
        return
    if agent["status"] == "paused":
        yield {"type": "error", "content": f"Agent {agent['name']} 已暂停，无法执行推理。"}
        return

    # ── 2. 扣生存费 ──
    turn_cost = config.settings.turn_cost
    try:
        new_balance = db.adjust_balance(agent_id, -turn_cost, entity_type="agent")
    except ValueError as e:
        yield {"type": "error", "content": str(e)}
        return

    # ── 3. 构建系统提示词（含 SOUL.md + 铁律 + 记忆注入） ──
    user_id = agent.get("user_id", "")
    system_prompt = _build_system_prompt(agent, new_balance, user_id=user_id, user_input=user_input)

    # ── 4. 记录用户消息 ──
    db.create_message(agent_id, "user", user_input)

    # ── 5. 确定 API 配置 ──
    api_key = agent.get("api_key") or config.settings.deepseek_api_key
    base_url = config.settings.deepseek_base_url
    model = agent.get("api_model") or config.settings.default_model

    today_str = datetime.now().strftime("%Y年%m月%d日")

    yield {"type": "thinking", "content": "正在分析你的问题..."}

    # ═══════════════════════════════════════════════════════════════
    # 路径一：搜索类请求
    # ═══════════════════════════════════════════════════════════════
    if _is_search_query(user_input):
        logger.info("[流式搜索路径] %s: %s", agent_id, user_input[:50])
        yield {"type": "tool", "content": "正在联网搜索..."}
        try:
            result = _sync_execute(
                "agent_reach_search",
                {"query": user_input[:40]},
                {"agent_id": agent_id},
            )
            if result.get("success"):
                search_result = result.get("output", "")
            else:
                search_result = f"搜索失败: {result.get('error', '未知错误')}"
        except Exception as e:
            logger.error("流式智能搜索失败: %s", e)
            search_result = f"搜索失败: {e}"

        yield {"type": "tool_result", "content": "搜索完成，正在生成回答..."}

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"今天是 {today_str}。\n\n"
                    f"以下是为你的问题「{user_input}」搜索到的实时信息：\n\n"
                    f"{search_result}\n\n"
                    "请根据以上搜索结果，用中文简洁、清晰地回答用户的问题。"
                    "引用来源时标注来源（如【百度热搜】【今日热榜】【网络搜索】）。"
                    "如果搜索结果中没有相关信息，请如实说明。"
                ),
            },
        ]

        try:
            content, _ = _call_deepseek_stream(
                messages=messages,
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout=15,
            )
            # 逐 chunk 推送
            if content:
                yield {"type": "text", "content": content}
        except RuntimeError as e:
            logger.error("流式搜索总结失败: %s", e)
            yield {"type": "text", "content": search_result}

        db.create_message(agent_id, "assistant", content if 'content' in dir() else search_result)
        _save_conversation_memory(agent_id, user_id, user_input, content if 'content' in dir() else search_result, messages=messages)
        yield {"type": "done", "content": "", "credits_remaining": new_balance}
        return

    # ═══════════════════════════════════════════════════════════════
    # 路径二：非搜索工具类 — function calling
    # ═══════════════════════════════════════════════════════════════
    if _needs_non_search_tools(user_input):
        logger.info("[流式工具路径] %s: %s", agent_id, user_input[:50])

        _init_starpivot()
        from core.starpivot.translator import ModelTranslator
        all_tools = _registry.list_tools()
        openai_tools = ModelTranslator.to_deepseek(all_tools) if all_tools else []

        messages: list = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"今天是 {today_str}。\n\n{user_input}"},
        ]

        final_content = ""
        current_tool_round = 0

        while current_tool_round <= max_tool_rounds:
            yield {"type": "thinking", "content": f"正在思考（第 {current_tool_round + 1} 轮）..."}

            try:
                content, tool_calls = _call_deepseek_stream(
                    messages=messages,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    tools=openai_tools,
                    timeout=15,
                )
            except RuntimeError as e:
                logger.error("流式 DeepSeek 调用失败: %s", e)
                yield {"type": "error", "content": str(e)}
                db.create_message(agent_id, "assistant", f"[错误] {e}")
                return

            # 添加 assistant 消息
            assistant_msg = {"role": "assistant", "content": content}
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("function", {}).get("name", ""),
                            "arguments": tc.get("function", {}).get("arguments", ""),
                        },
                    }
                    for tc in tool_calls
                ]
            messages.append(assistant_msg)

            # 无 tool_calls → 最终回复（逐 chunk 推送）
            if not tool_calls:
                final_content = content or ""
                if final_content:
                    yield {"type": "text", "content": final_content}
                db.create_message(agent_id, "assistant", final_content)
                break

            # 执行工具
            current_tool_round += 1
            for tc in tool_calls:
                func_name = tc.get("function", {}).get("name", "")
                yield {"type": "tool", "content": f"正在调用工具: {func_name}"}

                try:
                    func_args_raw = tc.get("function", {}).get("arguments", "{}")
                    if isinstance(func_args_raw, str):
                        try:
                            func_args = json.loads(func_args_raw)
                        except json.JSONDecodeError:
                            from json_repair import repair_json
                            func_args = json.loads(repair_json(func_args_raw))
                    else:
                        func_args = func_args_raw
                except Exception:
                    func_args = {"query": func_args_raw[:50]}

                result = _sync_execute(func_name, func_args, {"agent_id": agent_id})
                yield {"type": "tool_result", "content": f"{func_name} 执行完成"}

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result.get("output", "") or result.get("error", ""),
                })

                db.create_message(
                    agent_id,
                    "tool",
                    f"[{func_name}] args={func_args} → success={result.get('success', False)}",
                )

            if current_tool_round >= max_tool_rounds:
                yield {"type": "thinking", "content": "工具轮数上限，强制总结..."}
                try:
                    content, _ = _call_deepseek_stream(
                        messages=messages,
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        timeout=15,
                    )
                    final_content = content or ""
                    if final_content:
                        yield {"type": "text", "content": final_content}
                except RuntimeError:
                    final_content = ""
                db.create_message(agent_id, "assistant", final_content)
                break

        _save_conversation_memory(agent_id, user_id, user_input, final_content, messages=messages)
        yield {"type": "done", "content": "", "credits_remaining": new_balance}
        return

    # ═══════════════════════════════════════════════════════════════
    # 路径三：纯对话
    # ═══════════════════════════════════════════════════════════════
    logger.info("[流式对话路径] %s: %s", agent_id, user_input[:50])
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]

    try:
        content, _ = _call_deepseek_stream(
            messages=messages,
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=15,
        )
        if content:
            yield {"type": "text", "content": content}
    except RuntimeError as e:
        logger.error("流式对话失败: %s", e)
        yield {"type": "error", "content": str(e)}
        db.create_message(agent_id, "assistant", f"[错误] {e}")
        return

    db.create_message(agent_id, "assistant", content)
    _save_conversation_memory(agent_id, user_id, user_input, content, messages=messages)
    yield {"type": "done", "content": "", "credits_remaining": new_balance}
