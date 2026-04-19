import re
import string
from tree_sitter import Language, Parser
import tree_sitter_java as tsjava

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
# L2: LOOP SIMPLIFICATION (Tree-sitter based)
#
# A loop is ONLY converted if ALL of these hold:
#   1. for (int i = 0; i < bound; i++)  — standard increment
#   2. bound is col.size(), arr.length, or body has col.get(i)/arr[i]
#   3. After removing the collection access, index `i` does NOT appear
#      anywhere else in the body (meaning i is ONLY used for element access)
# ─────────────────────────────────────────────
def apply_L2(code: str) -> str:
    tree = parse(code)
    candidates = []

    def walk(node):
        if node.type == "for_statement":
            info = analyze_for(node, code)
            if info:
                candidates.append((node, info))
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    candidates.sort(key=lambda x: x[0].start_byte, reverse=True)

    result = code
    for node, info in candidates:
        converted = convert_loop(node, info, result)
        if converted is not None:
            result = result[:node.start_byte] + converted + result[node.end_byte:]
        # if None → keep original, do not replace

    return result


def analyze_for(node, code: str):
    full = node_text(node, code)
    init_node = cond_node = body_node = None

    for child in node.children:
        if child.type == "local_variable_declaration":
            init_node = child
        elif child.type == "binary_expression":
            cond_node = child
        elif child.type == "block":
            body_node = child

    if not (init_node and cond_node and body_node):
        return None

    # Init: must be  int i = 0
    init_text = node_text(init_node, code).strip()
    init_m = re.match(r'int\s+(\w+)\s*=\s*0', init_text)
    if not init_m:
        return None
    idx = init_m.group(1)

    # Condition: must be  i < something
    cond_text = node_text(cond_node, code).strip()
    cond_m = re.match(rf'{re.escape(idx)}\s*<\s*(.+)', cond_text)
    if not cond_m:
        return None
    bound = cond_m.group(1).strip()

    # Update: must be  i++  (not i--)
    if f'{idx}++' not in full and f'++{idx}' not in full:
        return None

    body = node_text(body_node, code)  # includes { }

    # Case A: bound = col.size()
    size_m = re.fullmatch(r'(\w+)\.size\(\)', bound)
    if size_m:
        return {"kind": "list", "idx": idx, "col": size_m.group(1), "body": body}

    # Case B: bound = arr.length
    len_m = re.fullmatch(r'(\w+)\.length', bound)
    if len_m:
        return {"kind": "array", "idx": idx, "col": len_m.group(1), "body": body}

    # Case C: body has col.get(i) or col[i]
    get_m = re.search(rf'(\w+)\.get\({re.escape(idx)}\)', body)
    if get_m:
        return {"kind": "list", "idx": idx, "col": get_m.group(1), "body": body}

    arr_m = re.search(rf'(\w+)\[{re.escape(idx)}\]', body)
    if arr_m:
        return {"kind": "array", "idx": idx, "col": arr_m.group(1), "body": body}

    return None


def index_still_used(inner: str, idx: str) -> bool:
    """
    After stripping the collection access pattern, check if the index
    variable `idx` still appears in the body.
    If yes → loop is NOT safe to convert (idx used for other purposes).
    Uses word-boundary match to avoid false positives.
    """
    return bool(re.search(rf'\b{re.escape(idx)}\b', inner))


def convert_loop(node, info: dict, code: str):
    """
    Returns the converted loop string, or None if conversion is unsafe.
    """
    idx  = info["idx"]
    col  = info["col"]
    kind = info["kind"]
    body = info["body"]

    inner = body[body.index('{')+1 : body.rindex('}')]

    if kind == "list":
        # Remove temp var: Type var = col.get(idx);
        tdecl = re.compile(
            rf'\s*[\w<>\[\]]+\s+(\w+)\s*=\s*{re.escape(col)}\.get\({re.escape(idx)}\)\s*;')
        t = tdecl.search(inner)
        if t:
            inner_converted = tdecl.sub('', inner)
            inner_converted = re.sub(rf'\b{re.escape(t.group(1))}\b', 'item', inner_converted)
        else:
            inner_converted = re.sub(
                rf'{re.escape(col)}\.get\({re.escape(idx)}\)', 'item', inner)

    elif kind == "array":
        # Remove temp var: Type var = col[idx];
        tdecl = re.compile(
            rf'\s*[\w<>\[\]]+\s+(\w+)\s*=\s*{re.escape(col)}\[{re.escape(idx)}\]\s*;')
        t = tdecl.search(inner)
        if t:
            inner_converted = tdecl.sub('', inner)
            inner_converted = re.sub(rf'\b{re.escape(t.group(1))}\b', 'item', inner_converted)
        else:
            inner_converted = re.sub(
                rf'{re.escape(col)}\[{re.escape(idx)}\]', 'item', inner)
    else:
        return None

    # ── Safety check ──────────────────────────────────────────────────
    # If index variable still appears after conversion → unsafe, bail out
    if index_still_used(inner_converted, idx):
        return None

    return f'for (Object item : {col}) {{{inner_converted}}}'


# ─────────────────────────────────────────────
# L3: VARIABLE + METHOD RENAMING (Tree-sitter)
# ─────────────────────────────────────────────
JAVA_KEYWORDS = {
    "abstract","assert","boolean","break","byte","case","catch","char",
    "class","const","continue","default","do","double","else","enum",
    "extends","final","finally","float","for","goto","if","implements",
    "import","instanceof","int","interface","long","native","new",
    "package","private","protected","public","return","short","static",
    "super","switch","synchronized","this","throw","throws","transient",
    "try","void","volatile","while","true","false","null",
    "String","System","Object","Integer","Double","Float","Long","Boolean",
    "List","ArrayList","Map","HashMap","Set","HashSet","Arrays","Collections",
    "Math","StringBuilder","Scanner","Iterator","Optional","Random",
    "Collection","Graph","DisjointSetUnion","KargerOutput",
    "out","err","in","println","print","printf","format",
    "toString","toArray","toList","size","get","set","add","remove","put",
    "contains","isEmpty","length","charAt","substring","equals","equalsIgnoreCase",
    "indexOf","lastIndexOf","valueOf","parseInt","parseDouble","trim","strip",
    "split","join","replace","replaceAll","matches","startsWith","endsWith",
    "compareTo","hashCode","clone","getClass","notify","wait","copy",
    "next","hasNext","iterator","stream","forEach","map","filter","collect",
    "sort","reverse","shuffle","min","max","abs","pow","sqrt","floor","ceil",
    "append","insert","delete","capacity","nextInt",
    "main","args","item",
    "run","start","stop","init","execute","call",
    "equals","hashCode","toString","compareTo",
    "getValue","setValue","getName","setName","getId","setId",
}

def encode_name(n: int) -> str:
    letters = string.ascii_lowercase
    result, n = "", n + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = letters[rem] + result
    return result


def collect_rename_targets(tree, code: str) -> set:
    targets = set()

    def is_override(method_node) -> bool:
        for child in method_node.children:
            if child.type == "modifiers":
                for mod in child.children:
                    if mod.type == "marker_annotation":
                        if "Override" in node_text(mod, code):
                            return True
        return False

    def walk(node):
        if node.type == "local_variable_declaration":
            for child in node.children:
                if child.type == "variable_declarator":
                    for sub in child.children:
                        if sub.type == "identifier":
                            name = node_text(sub, code)
                            if _is_candidate(name):
                                targets.add(name)

        elif node.type == "formal_parameter":
            for child in node.children:
                if child.type == "identifier":
                    name = node_text(child, code)
                    if _is_candidate(name):
                        targets.add(name)

        elif node.type == "enhanced_for_statement":
            for child in node.children:
                if child.type == "identifier":
                    name = node_text(child, code)
                    if _is_candidate(name):
                        targets.add(name)

        elif node.type == "method_declaration":
            if not is_override(node):
                for child in node.children:
                    if child.type == "identifier":
                        name = node_text(child, code)
                        if _is_candidate(name):
                            targets.add(name)
                        break

        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return targets


def _is_candidate(name: str) -> bool:
    return (
        name not in JAVA_KEYWORDS
        and len(name) > 1
        and name[0].islower()
    )


def apply_L3(code: str):
    tree = parse(code)
    targets = collect_rename_targets(tree, code)
    rename_map = {name: encode_name(i) for i, name in enumerate(sorted(targets))}

    if not rename_map:
        return code, rename_map

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
        if g4 and not after_dot and g4 in rename_map:
            result.append(rename_map[g4])
        else:
            result.append(tok.group(0))
        after_dot = False

    return ''.join(result), rename_map


# ─────────────────────────────────────────────
# PIPELINE: L0 -> L1 -> L2 -> L3
# ─────────────────────────────────────────────
def run_pipeline(code: str) -> dict:
    L0 = code
    L1 = apply_L1(L0)
    L2 = apply_L2(L1)
    L3, rename_map = apply_L3(L2)
    return {"L0": L0, "L1": L1, "L2": L2, "L3": L3, "rename_map": rename_map}


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
    print_level("L2 — Loop Simplified",             r["L2"])
    print_level("L3 — Variables + Methods Renamed", r["L3"])

    print(f"\n{'━'*65}")
    print("  RENAME MAP (L3)")
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