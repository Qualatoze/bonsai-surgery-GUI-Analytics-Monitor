import ast, pathlib

for path in pathlib.Path("tabs").glob("*.py"):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            defined = {n.name for n in node.body if isinstance(n, ast.FunctionDef)}
            used = set()
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Attribute)
                        and isinstance(sub.value, ast.Name)
                        and sub.value.id == "self"
                        and isinstance(sub.ctx, ast.Load)):
                    used.add(sub.attr)
            missing = used - defined - {"controller", "cfg", "store"}
            missing = {m for m in missing if m.startswith("_") and not m.startswith("__")}
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Attribute)
                        and isinstance(sub.value, ast.Name)
                        and sub.value.id == "self"
                        and isinstance(sub.ctx, ast.Store)):
                    missing.discard(sub.attr)
            if missing:
                print(f"{path}:{node.name} -> missing: {sorted(missing)}")

print("Audit complete.")
