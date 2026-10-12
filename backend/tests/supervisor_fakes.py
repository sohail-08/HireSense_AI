import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


class QueueToolModel:
    """Script Gemini responses while exercising the real native ToolNode."""

    def __init__(self, actions=()):
        self.actions = list(actions)
        self.tool_name = "screen_candidates"
        self.tool_args = {}
        self.bindings = []
        self.context = None
        self.tool_messages = []
        self.final_response = None
        self.calls = 0

    def bind_tools(self, tools, **kwargs):
        self.bindings.append({"names": [tool.name for tool in tools], **kwargs})
        model = self
        choice = kwargs.get("tool_choice")

        class BoundModel:
            def invoke(self, messages):
                return model._invoke(messages, choice)

        return BoundModel()

    def _invoke(self, messages, choice):
        self.calls += 1
        if choice == "none":
            last = messages[-1]
            assert isinstance(last, ToolMessage)
            self.tool_messages.append(last)
            if isinstance(self.final_response, Exception):
                raise self.final_response
            if self.final_response is not None:
                return self.final_response
            result = json.loads(str(last.content))
            return AIMessage(content=result["assistant_message"])
        system = next(msg for msg in messages if isinstance(msg, SystemMessage))
        self.context = json.loads(system.content.split("Current workflow state:\n", 1)[1])
        user = next(msg for msg in reversed(messages) if isinstance(msg, HumanMessage))
        action = self.actions.pop(0) if self.actions else self.tool_name
        if isinstance(action, Exception):
            raise action
        if isinstance(action, AIMessage):
            return action
        return AIMessage(content="", tool_calls=[{
            "name": action,
            "args": {"message": str(user.content), **self.tool_args},
            "id": f"test-call-{self.calls}",
            "type": "tool_call",
        }])
