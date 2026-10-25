"""Hash repository-local import closures for Durham PDF candidate bindings."""
from __future__ import annotations
import ast, hashlib, json
from pathlib import Path

def digest(root: Path, entry: Path) -> str:
    root=root.resolve(strict=True);pending=[entry.resolve(strict=True)];seen=set()
    def local(name):
        base=root.joinpath(*name.split("."))
        for p in (base.with_suffix(".py"),base/"__init__.py"):
            if p.is_file():return p.resolve(strict=True)
        return None
    while pending:
        path=pending.pop()
        if path in seen:continue
        path.relative_to(root)
        seen.add(path)
        tree=ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in {"__import__","eval","exec"}:
                raise ValueError("dynamic repository import is unbound")
            names=[]
            if isinstance(node,ast.Import):
                names=[x.name for x in node.names]
            elif isinstance(node,ast.ImportFrom):
                base=node.module or ""
                if node.level:
                    parts=list(path.relative_to(root).with_suffix("").parts)
                    if path.name!="__init__.py":parts.pop()
                    if node.level>len(parts):raise ValueError("relative import escapes repository")
                    prefix=".".join(parts[:len(parts)-node.level+1])
                    base=".".join(x for x in (prefix,base) if x)
                if base:names=[base]+[base+"."+x.name for x in node.names]
            for name in names:
                dep=local(name)
                if dep is not None and dep not in seen:pending.append(dep)
                parts=name.split(".")
                for i in range(1,len(parts)):
                    dep=local(".".join(parts[:i]))
                    if dep is not None and dep not in seen:pending.append(dep)
    records=[{"path":p.relative_to(root).as_posix(),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(seen,key=lambda x:x.relative_to(root).as_posix())]
    return hashlib.sha256((json.dumps(records,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()).hexdigest()

