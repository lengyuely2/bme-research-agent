class NullMcp:
    """No external processes, discovery or configuration in the BME build."""
    def tool_defs_for_responses(self): return []
    def remote_tool_blocks(self): return []
    def status(self): return []
    def shutdown(self): pass
