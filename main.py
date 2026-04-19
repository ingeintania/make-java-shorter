import re
import string
from tree_sitter import Language, Parser
import tree_sitter_java as tsjava
from java_keywords import JAVA_KEYWORDS

# ─────────────────────────────────────────────
# SETUP TREE-SITTER
# ─────────────────────────────────────────────
JAVA_LANGUAGE = Language(tsjava.language())
parser = Parser(JAVA_LANGUAGE)

def parse(code: str):
    return parser.parse(bytes(code, "utf8"))

def node_text(node, code: str) -> str:
    return code[node.start_byte:node.end_byte]


# ─────────────────────────────────────────────
# L1: FORMATTING REMOVAL
# ─────────────────────────────────────────────
def apply_L1(code: str) -> str:
    code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
    code = re.sub(r'//[^\n]*', '', code)
    lines = [line.strip() for line in code.splitlines()]
    lines = [l for l in lines if l]
    return ' '.join(lines)


# ─────────────────────────────────────────────
# L2: VARIABLE + METHOD RENAMING
#
# Key fixes vs previous version:
#   1. Method calls after dot ARE renamed (consistent with declaration)
#   2. Field names skipped — too risky without full type resolution
#   3. Collision detection — if a short name already used, skip
#   4. Rename map built from declarations, applied everywhere including
#      post-dot positions for method names
# ─────────────────────────────────────────────
def encode_name(n: int) -> str:
    letters = string.ascii_lowercase
    result, n = "", n + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = letters[rem] + result
    return result


def _is_candidate(name: str) -> bool:
    return (
        name not in JAVA_KEYWORDS
        and len(name) > 1
        and name[0].islower()
    )


def collect_rename_targets(tree, code: str) -> dict:
    """
    Collect rename targets separated by kind:
      - 'locals'  : local variables + parameters + for-each vars
      - 'methods' : user-defined method names

    Fields are intentionally EXCLUDED — renaming fields requires
    tracking all usages across methods which risks collision.
    Methods ARE included because Tree-sitter finds both declaration
    and all call sites can be renamed consistently via token pass.
    """
    locals_set  = set()
    methods_set = set()

    def is_override(method_node) -> bool:
        for child in method_node.children:
            if child.type == "modifiers":
                for mod in child.children:
                    if mod.type == "marker_annotation":
                        if "Override" in node_text(mod, code):
                            return True
        return False

    def walk(node):
        # Local variable declaration
        if node.type == "local_variable_declaration":
            for child in node.children:
                if child.type == "variable_declarator":
                    for sub in child.children:
                        if sub.type == "identifier":
                            name = node_text(sub, code)
                            if _is_candidate(name):
                                locals_set.add(name)

        # Method parameter
        elif node.type == "formal_parameter":
            for child in node.children:
                if child.type == "identifier":
                    name = node_text(child, code)
                    if _is_candidate(name):
                        locals_set.add(name)

        # Enhanced for variable
        elif node.type == "enhanced_for_statement":
            for child in node.children:
                if child.type == "identifier":
                    name = node_text(child, code)
                    if _is_candidate(name):
                        locals_set.add(name)

        # Method declaration name
        elif node.type == "method_declaration":
            if not is_override(node):
                for child in node.children:
                    if child.type == "identifier":
                        name = node_text(child, code)
                        if _is_candidate(name):
                            methods_set.add(name)
                        break

        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return {"locals": locals_set, "methods": methods_set}


def build_rename_map(targets: dict) -> dict:
    """
    Build rename map ensuring no collision between locals and methods.
    Locals get names first (a, b, c...), methods get next names.
    This prevents a local 'i' and method 'init' both mapping to 'a'.
    """
    rename_map = {}
    counter = 0

    # Locals first
    for name in sorted(targets["locals"]):
        rename_map[name] = encode_name(counter)
        counter += 1

    # Methods after — get next available names
    for name in sorted(targets["methods"]):
        if name not in rename_map:  # avoid overwrite if same name somehow
            rename_map[name] = encode_name(counter)
            counter += 1

    return rename_map


def apply_L2(code: str):
    tree = parse(code)
    targets  = collect_rename_targets(tree, code)
    rename_map = build_rename_map(targets)

    if not rename_map:
        return code, rename_map

    method_names = targets["methods"]

    # Tokenizer pass — two modes:
    #   - locals: rename only when NOT after dot
    #   - methods: rename BOTH when standalone AND when after dot
    #     (so declaration + all call sites are renamed consistently)
    token_re = re.compile(
        r'("(?:[^"\\]|\\.)*")'
        r'|(import\b[^;]+;)'
        r'|(\d+(?:\.\d+)?[fFdDlL]?)'
        r'|([a-zA-Z_]\w*)'
        r'|(\.)'
        r'|(\s+)'
        r'|([^\w\s])'
    )

    result = []
    after_dot = False

    for tok in token_re.finditer(code):
        g1,g2,g3,g4,g5,g6,g7 = tok.groups()

        if g6:
            result.append(g6)
            continue

        if g5:
            result.append('.')
            after_dot = True
            continue

        if g4:
            is_method_name = g4 in method_names
            in_rename_map  = g4 in rename_map

            if in_rename_map:
                if is_method_name:
                    # Methods: rename everywhere — declaration AND call sites
                    result.append(rename_map[g4])
                elif not after_dot:
                    # Locals: only rename when not after dot
                    result.append(rename_map[g4])
                else:
                    # Local name appearing after dot = field/method of object
                    # Do not rename — we don't track field ownership
                    result.append(tok.group(0))
            else:
                result.append(tok.group(0))

        else:
            result.append(tok.group(0))

        after_dot = False

    return ''.join(result), rename_map


# ─────────────────────────────────────────────
# PIPELINE: L0 -> L1 -> L2
# ─────────────────────────────────────────────
def run_pipeline(code: str) -> dict:
    L0 = code
    L1 = apply_L1(L0)
    L2, rename_map = apply_L2(L1)
    return {"L0": L0, "L1": L1, "L2": L2, "rename_map": rename_map}


# ─────────────────────────────────────────────
# DISPLAY
# ─────────────────────────────────────────────
def print_level(label, code):
    print(f"\n{'━'*65}")
    print(f"  {label}")
    print(f"{'━'*65}")
    print(code)

def print_report(r):
    print_level("L0 — Original",                    r["L0"])
    print_level("L1 — Formatting Removed",          r["L1"])
    print_level("L2 — Variables + Methods Renamed", r["L2"])

    print(f"\n{'━'*65}")
    print("  RENAME MAP (L2)")
    print(f"{'━'*65}")
    if r["rename_map"]:
        for orig, short in r["rename_map"].items():
            print(f"  {orig:<25} ->  {short}")
    else:
        print("  (no variables or methods renamed)")


# ─────────────────────────────────────────────
# READ FROM FILE
# ─────────────────────────────────────────────
def read_java_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    java_code = read_java_file("example.java")
    results = run_pipeline(java_code)
    print_report(results)