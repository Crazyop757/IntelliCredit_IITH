import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("m", "src/agent/tools/rbi_tool.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
print(repr(m._normalise("R.K. Mehta (Ltd)")))
print(repr(m._normalise("")))
print(repr(m._normalise("  SBI  ")))
