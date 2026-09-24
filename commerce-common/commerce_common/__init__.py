"""两个 agent 角色共用的机制。从子模块导入：

``config``            ``BaseAgentConfig`` 和模型默认值
``types``             ``MemoryFact``、``MemoryCategory``
``fencing``           ``Fence``、建议按钮和展示文本的清洗
``memory``            ``MemoryStore``、写入过滤器、提取、``MemoryRuntime``
``skills``            ``SkillRegistry``
``prompt_assembly``   缓存断点：系统块、工具数组、滚动对话
``grounding``         ``GroundingRule`` 和词表匹配函数
``presentation``      ``PresentationComponent``、``PresentationExtension``、运行器
``streaming``         ``AgentEvent``、``ToolOutcome``、``to_sse``
``turn``              Messages API 对话循环的辅助函数
"""
