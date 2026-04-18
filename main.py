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
# L2: LOOP SIMPLIFICATION
# ─────────────────────────────────────────────
def apply_L2(code: str) -> str:
    """
    Convert indexed for-loops to enhanced for-loops.
    Must run BEFORE L3 (renaming) so variable names are still readable.

    List pattern:
      for (int i = 0; i < col.size(); i++) {
          Type var = col.get(i);
          ... var ...
      }
      → for (Object item : col) { ... item ... }

    Array pattern:
      for (int i = 0; i < arr.length; i++) {
          Type var = arr[i];
          ... var ...
      }
      → for (Object item : arr) { ... item ... }
    """

    # ── List loop ────────────────────────────────────────────────────────
    list_pattern = re.compile(
        r'for\s*\(\s*int\s+(\w+)\s*=\s*0\s*;\s*\1\s*<\s*(\w+)\.size\(\)\s*;\s*\1\+\+\s*\)\s*\{([^}]*)\}',
        re.DOTALL
    )

    def replace_list(m):
        idx_var = m.group(1)   # e.g. "index"
        col     = m.group(2)   # e.g. "numbers"
        body    = m.group(3)

        # Remove temp variable declaration: Type varName = col.get(idx);
        temp_decl = re.compile(
            rf'\s*\w+\s+(\w+)\s*=\s*{re.escape(col)}\.get\({re.escape(idx_var)}\)\s*;'
        )
        temp_match = temp_decl.search(body)
        if temp_match:
            temp_var = temp_match.group(1)
            body = temp_decl.sub('', body)
            # Replace remaining usages of temp_var with 'item'
            body = re.sub(rf'\b{re.escape(temp_var)}\b', 'item', body)
        else:
            # No temp var — replace col.get(idx) directly
            body = re.sub(
                rf'\b{re.escape(col)}\.get\({re.escape(idx_var)}\)',
                'item', body
            )

        return f'for (Object item : {col}) {{{body}}}'

    # ── Array loop ───────────────────────────────────────────────────────
    array_pattern = re.compile(
        r'for\s*\(\s*int\s+(\w+)\s*=\s*0\s*;\s*\1\s*<\s*(\w+)\.length\s*;\s*\1\+\+\s*\)\s*\{([^}]*)\}',
        re.DOTALL
    )

    def replace_array(m):
        idx_var = m.group(1)   # e.g. "position"
        arr     = m.group(2)   # e.g. "dataArray"
        body    = m.group(3)

        # Remove temp variable declaration: Type varName = arr[idx];
        temp_decl = re.compile(
            rf'\s*\w+\s+(\w+)\s*=\s*{re.escape(arr)}\[{re.escape(idx_var)}\]\s*;'
        )
        temp_match = temp_decl.search(body)
        if temp_match:
            temp_var = temp_match.group(1)
            body = temp_decl.sub('', body)
            body = re.sub(rf'\b{re.escape(temp_var)}\b', 'item', body)
        else:
            body = re.sub(
                rf'\b{re.escape(arr)}\[{re.escape(idx_var)}\]',
                'item', body
            )

        return f'for (Object item : {arr}) {{{body}}}'

    code = list_pattern.sub(replace_list, code)
    code = array_pattern.sub(replace_array, code)
    return code


# ─────────────────────────────────────────────
# L3: VARIABLE RENAMING
# ─────────────────────────────────────────────
JAVA_KEYWORDS = {
    "abstract","assert","boolean","break","byte","case","catch","char",
    "class","const","continue","default","do","double","else","enum",
    "extends","final","finally","float","for","goto","if","implements",
    "import","instanceof","int","interface","long","native","new",
    "package","private","protected","public","return","short","static",
    "super","switch","synchronized","this","throw","throws","transient",
    "try","void","volatile","while","true","false","null",
    # Common Java standard names — do not rename
    "String","System","out","println","print","main","args","Object",
    "List","ArrayList","Map","HashMap","Override","Exception",
    "size","get","length","put","add","remove","contains","isEmpty",
    # Loop keyword introduced by L2
    "item",
    # Class/method names in sample — add your own as needed
    "Example","calculateSum","printElements","Integer",
}

def encode_name(n: int) -> str:
    letters = string.ascii_lowercase
    result = ""
    n += 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = letters[rem] + result
    return result

def apply_L3(code: str) -> str:
    """
    Rename local variables and parameters to short names (a, b, c, ...).
    Preserves Java keywords, standard library names, and L2 'item' keyword.
    """
    # Extract candidate identifiers (not in keywords)
    tokens = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', code)
    candidates = sorted(set(t for t in tokens if t not in JAVA_KEYWORDS))

    rename_map = {}
    for i, name in enumerate(candidates):
        rename_map[name] = encode_name(i)

    result = code
    for original, short in rename_map.items():
        result = re.sub(rf'\b{re.escape(original)}\b', short, result)

    return result, rename_map


# ─────────────────────────────────────────────
# PIPELINE: L0 → L1 → L2 → L3
# ─────────────────────────────────────────────
def run_pipeline(code: str) -> dict:
    L0 = code
    L1 = apply_L1(L0)
    L2 = apply_L2(L1)
    L3, rename_map = apply_L3(L2)

    return {
        "L0": L0,
        "L1": L1,
        "L2": L2,
        "L3": L3,
        "rename_map": rename_map,
    }


# ─────────────────────────────────────────────
# DISPLAY
# ─────────────────────────────────────────────
def token_count(code: str) -> int:
    return len(code.split())

def print_level(label, code):
    print(f"\n{'━'*65}")
    print(f"  {label}")
    print(f"{'━'*65}")
    print(code)

def print_report(results: dict):
    L0 = results["L0"]
    L1 = results["L1"]
    L2 = results["L2"]
    L3 = results["L3"]

    print_level("L0 — Original",            L0)
    print_level("L1 — Formatting Removed",  L1)
    print_level("L2 — Loop Simplified",     L2)
    print_level("L3 — Variables Renamed",   L3)

    print(f"\n{'━'*65}")
    print("  RENAME MAP (L3)")
    print(f"{'━'*65}")
    for orig, short in results["rename_map"].items():
        print(f"  {orig:<25} →  {short}")


# ─────────────────────────────────────────────
# SAMPLE
# ─────────────────────────────────────────────
SAMPLE_JAVA = """\
import java.io.*;

public class GeeksforGeeks {
    // Method to check leap year
    public static void isLeapYear(int year)
    {
        // flag to take a non-leap year by default
        boolean is_leap_year = false;

        // If year is divisible by 4
        if (year % 4 == 0) {
            is_leap_year = true;

            // To identify whether it is a
            // century year or not
            if (year % 100 == 0) {
                // Checking if year is divisible by 400
                // therefore century leap year
                if (year % 400 == 0)
                    is_leap_year = true;
                else
                    is_leap_year = false;
            }
        }

        // We land here when corresponding if fails
        // If year is not divisible by 4
        else

            // Flag dealing-  Non leap-year
            is_leap_year = false;

        if (!is_leap_year)
            System.out.println(year + " : Non Leap-year");
        else
            System.out.println(year + " : Leap-year");
    }

    // Driver Code
    public static void main(String[] args)
    {
        // Calling our function by
        // passing century year not divisible by 400
        isLeapYear(2000);

        // Calling our function by
        // passing Non-century year
        isLeapYear(2002);
    }
}"""

if __name__ == "__main__":
    results = run_pipeline(SAMPLE_JAVA)
    print_report(results)