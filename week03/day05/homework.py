"""你的设计方案：

需求： 用户需要一个能帮他们整理会议要点的工具。

设计提示：

是否需要拆成多个工具？（记录/查询/总结）
哪些是安全操作？哪些需要确认？
默认值怎么设计？
应该支持什么参数？
在下面空白处自己设计 Schema：

"""


# 记录会议记录
WRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "write_meeting_notes",
        "description": (
            "生成会议记录",
            "当用户需要记录某个会议的要点时，可以使用该工具。例如：帮我记录一下会议内容。",
            "必须传入 confirm=true 才会真正执行写入操作"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "meeting_title": {
                    "type": "string",
                    "description": "会议的主题"
                },
                "meeting_keywords": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "与会会议相关的关键词"
                },
                "meeting_notes": {
                    "type": "string",
                    "description": "会议记录的内容"
                },
                "meeting_participants": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "与会人员的列表"
                },
                "meeting_start_time": {
                    "type": "string",
                    "format": "date-time",
                    "description": "会议的开始时间"
                },
                "meeting_end_time": {
                    "type": "string",
                    "format": "date-time",
                    "description": "会议的结束时间"
                },
                "confirm": {
                    "type": "boolean",
                    "description": "是否确认执行写入操作",
                    "default": False
                }
            },
            "required": ["meeting_title"],
        },
    },
}

QUERY_TOOL = {
    "type": "function",
    "function": {
        "name": "query_meeting_notes",
        "description": (
            "查询会议记录",
            "当用户需要查询某个会议的记录时，可以使用该工具。",
            "该工具可以根据会议主题、关键词、起始时间、结束时间、会议关键词、会议ID、和与会人员进行搜索。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "meeting_start_time": {
                    "type": "string",
                    "format": "date-time",
                    "description": "会议的开始时间"
                },
                "meeting_end_time": {
                    "type": "string",
                    "format": "date-time",
                    "description": "会议的结束时间"
                },
                "meeting_title": {
                    "type": "string",
                    "description": "会议的主题"
                },
                "meeting_keywords": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "与会会议相关的关键词"
                },
                "meeting_participants": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "与会人员的列表"
                },
                "meeting_id": {
                    "type": "string",
                    "description": "会议的唯一标识符"
                },  
                "limit": {
                    "type": "integer",
                    "description": "返回的会议记录数量限制",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10
                }
            },
            "required": [],
        },
    },
}

SUMMARY_TOOL = {
    "type": "function",
    "function": {
        "name": "summarize_meeting_notes",
        "description": (
            "对会议记录进行总结",
            "该工具将根据会议内容进行提取，并生成摘要。",
            "该工具使用前应该获取会议记录的内容"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "meeting_content": {
                    "type": "string",
                    "description": "会议的内容"
                },
                "summary_length": {
                    "type": "integer",
                    "description": "摘要的长度",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 100
                }
            },
            "required": ["meeting_content"],
        },
    },
}

