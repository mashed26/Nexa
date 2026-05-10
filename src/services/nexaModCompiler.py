# This compiles NexaMods written in Python using the NexusMod API into a format
# that is interpreted by Nexus. It is then executed by Nexus according to the 
# hooks and capabilities declared in the mod.

# Under the MIT License.

# Also, this is not being currently worked on right now, nor is it actually production ready. Please do NOT integrate.

import ast
from typing import List, Dict
import sys

class NexusModCompiler:
    def __init__(self, source_code: str):
        self.source_code = source_code
        self.tree = None
        self.metadata = {}
        self.definitions = []
        self.functions = []
        self.events = []

    # ----------------------------
    # Stage 0: Preprocess
    # ----------------------------
    def preprocess(self):
        self.tree = ast.parse(self.source_code)

    # ----------------------------
    # Stage 1: Static evaluation
    # ----------------------------
    def evaluate_static_expressions(self):
        class StaticEvaluator(ast.NodeTransformer):
            def visit_BinOp(self, node):
                self.generic_visit(node)
                if all(isinstance(n, ast.Constant) for n in [node.left, node.right]):
                    try:
                        return ast.Constant(eval(compile(ast.Expression(node), '', 'eval')))
                    except Exception:
                        return node
                return node
        self.tree = StaticEvaluator().visit(self.tree)

    # ----------------------------
    # Stage 2: Extract Metadata
    # ----------------------------
    def extract_metadata(self):
        for node in self.tree.body:
            if isinstance(node, ast.ClassDef):
                for stmt in node.body:
                    if isinstance(stmt, ast.FunctionDef) and stmt.name == "__init__":
                        if not stmt.body:
                            continue
                        first_stmt = stmt.body[0]
                        if isinstance(first_stmt, ast.Expr) and isinstance(first_stmt.value, ast.Call):
                            call = first_stmt.value
                            if isinstance(call.func, ast.Attribute) and call.func.attr == "__init__":
                                for kw in call.keywords:
                                    self.metadata[kw.arg] = ast.literal_eval(kw.value)

    # ----------------------------
    # Stage 3: Extract Definitions
    # ----------------------------
    def extract_definitions(self):
        class DefinitionVisitor(ast.NodeVisitor):
            def __init__(self):
                self.defs = []

            def visit_Assign(self, node):
                # Only handle simple assignments to a Name
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    return
                var_name = node.targets[0].id

                # Handle constructor calls
                if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
                    type_name = node.value.func.id
                    allowed_types = ("Effects", "Sounds", "Entities", "World", "PersistentData", "Player")  # allowed Nexus types
                    if type_name not in allowed_types:
                        return

                    params = []
                    for kw in node.value.keywords:
                        try:
                            val = ast.literal_eval(kw.value)
                            val_str = f'"{val}"' if isinstance(val, str) else str(val)
                            params.append(f"{kw.arg}:{val_str}")
                        except Exception:
                            pass

                    if "searchMCNamespace" not in [kw.arg for kw in node.value.keywords]:
                        params.append('searchMCNamespace:"minecraft"')

                    def_line = f"{type_name}:{var_name}({', '.join(params)})"
                    self.defs.append(def_line)

        visitor = DefinitionVisitor()
        visitor.visit(self.tree)
        self.definitions = visitor.defs

        # Collect defined variable names for later checks
        self.defined_names = set()
        for d in self.definitions:
            try:
                var = d.split(":", 1)[1].split("(", 1)[0]
                self.defined_names.add(var)
            except Exception:
                pass

    # ----------------------------
    # Stage 4-5: Extract Functions + Hooks
    # ----------------------------
    def extract_functions(self):
        class FunctionVisitor(ast.NodeVisitor):
            def __init__(self, defined_names):
                self.funcs = []
                self.hooks = {}
                self.defined_names = defined_names  # Inject defined names
    
            def extract_arg_token(self, arg):
                if isinstance(arg, ast.Name):
                    return arg.id
                elif isinstance(arg, ast.Constant):
                    return str(arg.value)
                elif isinstance(arg, ast.Call):
                    # Inline constructor usage is forbidden
                    print(f"Compilation error (line {arg.lineno}): inline constructor usage is not allowed. Assign to a variable first.", file=sys.stderr, flush=True)
                    sys.exit(1)
                elif isinstance(arg, ast.Attribute):
                    parts = []
                    curr = arg
                    while isinstance(curr, ast.Attribute):
                        parts.append(curr.attr)
                        curr = curr.value
                    if isinstance(curr, ast.Name):
                        parts.append(curr.id)
                    return ".".join(reversed(parts))
                else:
                    print(f"Compilation error (line {arg.lineno}): argument could not be parsed.", file=sys.stderr, flush=True)
                    sys.exit(1)
    
            def visit_FunctionDef(self, node: ast.FunctionDef):
                # Detect hook decorator
                event_name = None
                for deco in node.decorator_list:
                    if isinstance(deco, ast.Call) and getattr(deco.func, 'attr', '') == 'hook':
                        for kw in deco.keywords:
                            if kw.arg == "event":
                                event_name = ast.literal_eval(kw.value)
                if not event_name:
                    return
    
                func_lines = []
                arg_list = [arg.arg for arg in node.args.args if arg.arg != "self"]
                arg_str = ",".join(arg_list)
                func_lines.append(f"{node.name}({arg_str}:HOOK.{event_name}) "+"{")
    
                # Parse statements recursively
                def parse_statements(stmts):
                    for stmt in stmts:
                        if isinstance(stmt, ast.If):
                            cond = stmt.test
                            if isinstance(cond, ast.Compare) and isinstance(cond.left, ast.Call):
                                left_func = cond.left.func
                                cond_str = ""
                                if isinstance(left_func, ast.Attribute):
                                    cond_str = f"{left_func.value.id}.{left_func.attr}"
                                elif isinstance(left_func, ast.Name):
                                    cond_str = left_func.id
    
                                comp = cond.ops[0]
                                op = "<" if isinstance(comp, ast.Lt) else ">" if isinstance(comp, ast.Gt) else None
                                if not op:
                                    continue
                                right_val = ast.literal_eval(cond.comparators[0])
                                condition_token = f"IF:{cond_str} {op} {right_val}"
    
                                for then_stmt in stmt.body:
                                    if isinstance(then_stmt, ast.Expr) and isinstance(then_stmt.value, ast.Call):
                                        call = then_stmt.value
                                        if isinstance(call.func, ast.Attribute):
                                            var_name = self.extract_arg_token(call.func.value)
                                            method_name = call.func.attr
                                            arg_names = [self.extract_arg_token(a) for a in call.args]
    
                                            # Reject undefined variable usage
                                            base_name = var_name.split(".")[0]
                                            if base_name not in self.defined_names and base_name not in arg_list:
                                                print(f"Compilation error (line {call.lineno}): method call receiver '{base_name}' is not a defined Nexus element. Assign to a variable first.", file=sys.stderr, flush=True)
                                                sys.exit(1)
    
                                            then_token = f"DEFINITIONS::{var_name}.{method_name}({','.join(arg_names)})"
                                            func_lines.append(f"{condition_token} THEN:{then_token}")
    
                                    elif isinstance(then_stmt, ast.If):
                                        parse_statements([then_stmt])
                        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                            call = stmt.value
                            if isinstance(call.func, ast.Attribute):
                                var_name = self.extract_arg_token(call.func.value)
                                method_name = call.func.attr
                                arg_names = [self.extract_arg_token(a) for a in call.args]
    
                                base_name = var_name.split(".")[0]
                                if base_name not in self.defined_names and base_name not in arg_list:
                                    print(f"Compilation error (line {call.lineno}): method call receiver '{base_name}' is not a defined Nexus element. Assign to a variable first.", file=sys.stderr, flush=True)
                                    sys.exit(1)
    
                                func_lines.append(f"DEFINITIONS::{var_name}.{method_name}({','.join(arg_names)})")
    
                parse_statements(node.body)
                func_lines.append("}")
                self.funcs.append("\n".join(func_lines))
                self.hooks[node.name] = event_name
    
        visitor = FunctionVisitor(self.defined_names)
        visitor.visit(self.tree)
        self.functions = visitor.funcs
        self.events = [f"EVENT:{evt} {{\n    FUNCTS::{func}\n}}" for func, evt in visitor.hooks.items()]

    # ----------------------------
    # Stage 6: Compile .nxmod
    # ----------------------------
    def compile(self) -> str:
        compilerVersion = "nexamodCompiler-0.0.1-alpha"
        lines = [
            f"name:{self.metadata.get('name')}",
            f"version:{self.metadata.get('version')}",
            f"author:{self.metadata.get('author')}",
            f"desc:{self.metadata.get('description')}",
            f"capabilities:{','.join(self.metadata.get('capabilities', []))}",
            f"compiledWith:{compilerVersion}"
        ]
        lines.append("\nDEFINITIONS::")
        lines.extend(self.definitions)
        lines.append("::-::")
        lines.append("\nFUNCTS::")
        lines.extend(self.functions)
        lines.append("::-::")
        lines.append("\nEVENTS::")
        lines.extend(self.events)
        lines.append("::-::")
        return "\n".join(lines)


# ----------------------------
# Example: Read Python file and compile
# ----------------------------
if __name__ == "__main__":
    with open("C:\\Users\\micro\\OneDrive\\Desktop\\Nexabot\\nexus_modAPI\\example.py", "r") as f:  # replace with your file path
        source = f.read()

    compiler = NexusModCompiler(source)
    compiler.preprocess()
    compiler.evaluate_static_expressions()
    compiler.extract_metadata()
    compiler.extract_definitions()
    compiler.extract_functions()
    nxmod_output = compiler.compile()

    #print(nxmod_output)



    # Write to <ClassName>.nxmod
    class_name = compiler.metadata.get("name", "UnnamedMod").replace(" ", "_")
    with open(f"{class_name}.nxmod", "w") as f:
        f.write(nxmod_output)

    print(f"Compiled {class_name}.nxmod successfully.")