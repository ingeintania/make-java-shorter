import re
import string

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
# L2: LOOP SIMPLIFICATION (run BEFORE L3)
# ─────────────────────────────────────────────
def apply_L2(code: str) -> str:
    list_pat = re.compile(
        r'for\s*\(\s*int\s+(\w+)\s*=\s*0\s*;\s*\1\s*<\s*(\w+)\.size\(\)\s*;\s*\1\+\+\s*\)\s*\{([^}]*)\}',
        re.DOTALL)
    arr_pat = re.compile(
        r'for\s*\(\s*int\s+(\w+)\s*=\s*0\s*;\s*\1\s*<\s*(\w+)\.length\s*;\s*\1\+\+\s*\)\s*\{([^}]*)\}',
        re.DOTALL)

    def replace_list(m):
        idx, col, body = m.group(1), m.group(2), m.group(3)
        tdecl = re.compile(
            rf'\s*\w+\s+(\w+)\s*=\s*{re.escape(col)}\.get\({re.escape(idx)}\)\s*;')
        t = tdecl.search(body)
        if t:
            body = tdecl.sub('', body)
            body = re.sub(rf'\b{re.escape(t.group(1))}\b', 'item', body)
        else:
            body = re.sub(
                rf'\b{re.escape(col)}\.get\({re.escape(idx)}\)', 'item', body)
        return f'for (Object item : {col}) {{{body}}}'

    def replace_array(m):
        idx, arr, body = m.group(1), m.group(2), m.group(3)
        tdecl = re.compile(
            rf'\s*\w+\s+(\w+)\s*=\s*{re.escape(arr)}\[{re.escape(idx)}\]\s*;')
        t = tdecl.search(body)
        if t:
            body = tdecl.sub('', body)
            body = re.sub(rf'\b{re.escape(t.group(1))}\b', 'item', body)
        else:
            body = re.sub(
                rf'\b{re.escape(arr)}\[{re.escape(idx)}\]', 'item', body)
        return f'for (Object item : {arr}) {{{body}}}'

    code = list_pat.sub(replace_list, code)
    code = arr_pat.sub(replace_array, code)
    return code


# ─────────────────────────────────────────────
# L3: VARIABLE RENAMING (tokenizer-based)
# ─────────────────────────────────────────────
JAVA_KEYWORDS = {
    # Language keywords
    "abstract","assert","boolean","break","byte","case","catch","char",
    "class","const","continue","default","do","double","else","enum",
    "extends","final","finally","float","for","goto","if","implements",
    "import","instanceof","int","interface","long","native","new",
    "package","private","protected","public","return","short","static",
    "super","switch","synchronized","this","throw","throws","transient",
    "try","void","volatile","while","true","false","null",
    # Standard library — never rename
    "String","System","Object","Integer","Double","Float","Long","Boolean",
    "List","ArrayList","Map","HashMap","Set","HashSet","Arrays","Collections",
    "Math","StringBuilder","Scanner","Iterator",
    "out","err","in",
    "println","print","printf","format",
    "toString","toArray","size","get","set","add","remove","put",
    "contains","isEmpty","length","charAt","substring","equals",
    "indexOf","valueOf","parseInt","main","args",
    # Introduced by L2
    "item",
}

def encode_name(n: int) -> str:
    letters = string.ascii_lowercase
    result, n = "", n + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = letters[rem] + result
    return result

def apply_L3(code: str):
    """
    Tokenizer-based renaming. Splits code into typed tokens so we never
    accidentally rename:
      - identifiers inside string literals  "..."
      - identifiers inside import statements
      - identifiers after a dot  (obj.METHOD)
      - numeric literals
      - Java keywords / stdlib names
      - uppercase-starting names (class/type names)
    """
    token_re = re.compile(
        r'("(?:[^"\\]|\\.)*")'          # G1: string literal
        r'|(import\b[^;]+;)'             # G2: full import statement
        r'|(\d+(?:\.\d+)?[fFdDlL]?)'   # G3: numeric literal
        r'|([a-zA-Z_]\w*)'              # G4: identifier
        r'|(\.)'                         # G5: dot
        r'|(\s+)'                        # G6: whitespace
        r'|([^\w\s])'                   # G7: any other symbol
    )

    tokens = list(token_re.finditer(code))

    # ── Pass 1: collect rename candidates ────────────────────────────
    candidates = set()
    after_dot = False
    for tok in tokens:
        g1, g2, g3, g4, g5, g6, g7 = tok.groups()
        if g6:          # whitespace — skip, don't reset after_dot
            continue
        if g5:          # dot — next identifier is a method/field, protect it
            after_dot = True
            continue
        if g4 and not after_dot:
            if g4 not in JAVA_KEYWORDS and g4[0].islower() and len(g4) > 1:
                candidates.add(g4)
        after_dot = False   # reset after any non-whitespace, non-dot token

    rename_map = {name: encode_name(i)
                  for i, name in enumerate(sorted(candidates))}

    # ── Pass 2: rebuild code with renames applied ─────────────────────
    result = []
    after_dot = False
    for tok in tokens:
        g1, g2, g3, g4, g5, g6, g7 = tok.groups()
        if g6:                          # whitespace — preserve as-is
            result.append(g6)
            continue
        if g5:                          # dot
            result.append('.')
            after_dot = True
            continue
        if g4 and not after_dot and g4 in rename_map:
            result.append(rename_map[g4])   # ← rename
        else:
            result.append(tok.group(0))     # ← keep original
        after_dot = False

    return ''.join(result), rename_map

# ─────────────────────────────────────────────
# PIPELINE: L0 → L1 → L2 → L3
# ─────────────────────────────────────────────
def run_pipeline(code: str) -> dict:
    L0 = code
    L1 = apply_L1(L0)
    L2 = apply_L2(L1)       # loop simplification first (names still readable)
    L3, rename_map = apply_L3(L2)   # then rename
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
    print_level("L0 — Original",           r["L0"])
    print_level("L1 — Formatting Removed", r["L1"])
    print_level("L2 — Loop Simplified",    r["L2"])
    print_level("L3 — String Literals Truncated", r["L3"])
    print_level("L3 — Variables Renamed",  r["L3"])

    print(f"\n{'━'*65}")
    print("  RENAME MAP (L3)")
    print(f"{'━'*65}")
    for orig, short in r["rename_map"].items():
        print(f"  {orig:<25} →  {short}")


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