import subprocess
import os
import re
import sys

def parse_queries_file(filename):
    if not os.path.exists(filename):
        print(f"Error: {filename} not found.")
        return []
    
    all_queries = []
    current_config = None
    curr_section = ""

    with open(filename, 'r') as f:
        for line in f:
            clean_line = line.strip()
            if not clean_line: continue

            if "SELECT ATTRIBUTE" in clean_line.upper():
                if current_config:
                    all_queries.append(current_config)
                current_config = {"S": [], "n": 0, "V": [], "F": [], "sigma": {}, "G": ""}
                curr_section = "S"
            elif "NUMBER OF GROUPING" in clean_line.upper(): curr_section = "n"
            elif "GROUPING ATTRIBUTES" in clean_line.upper(): curr_section = "V"
            elif "F-VECT" in clean_line.upper(): curr_section = "F"
            elif "SELECT CONDITION" in clean_line.upper(): curr_section = "sigma"
            elif "HAVING CONDITION" in clean_line.upper(): curr_section = "G"
            else:
                if curr_section == "S":
                    current_config["S"] = [x.strip() for x in clean_line.split(",")]
                elif curr_section == "n":
                    num = re.search(r'\d+', clean_line)
                    if num: current_config["n"] = int(num.group())
                elif curr_section == "V":
                    current_config["V"] = [x.strip() for x in clean_line.split(",")]
                elif curr_section == "F":
                    current_config["F"] = [x.strip() for x in clean_line.split(",")]
                elif curr_section == "sigma":
                    # Each line: "1.col op val" -- multiple lines allowed per variable
                    # Operators: =, !=, <>, <, >, <=, >=
                    m = re.match(r"(\d+)\s*\.\s*(\w+)\s*(!=|<>|<=|>=|<|>|=)\s*(.+)$", clean_line)
                    if m:
                        var, col, op, raw_val = m.group(1), m.group(2), m.group(3), m.group(4).strip()
                        py_op = "!=" if op == "<>" else ("==" if op == "=" else op)
                        if (raw_val.startswith("'") and raw_val.endswith("'")) or \
                           (raw_val.startswith('"') and raw_val.endswith('"')):
                            val = f"'{raw_val[1:-1]}'"
                        else:
                            try: int(raw_val); val = raw_val
                            except ValueError:
                                try: float(raw_val); val = raw_val
                                except ValueError: val = f"'{raw_val}'"
                        predicate = f"row['{col}']{py_op}{val}"
                        if var not in current_config["sigma"]:
                            current_config["sigma"][var] = []
                        current_config["sigma"][var].append(predicate)
                elif curr_section == "G":
                    current_config["G"] = re.sub(r"\b(\d+)_", r"obj.v\1_", clean_line).strip()

        if current_config:
            all_queries.append(current_config)
            
    return all_queries

def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else None

    if input_file and os.path.exists(input_file):
        queries = parse_queries_file(input_file)
    else:
        if input_file:
            print(f"File '{input_file}' not found. Switching to interactive mode.\n")
        else:
            print("No file provided. Switching to interactive mode.\n")

        phi = {"S": [], "n": 0, "V": [], "F": [], "sigma": {}, "G": ""}
        phi["S"] = [x.strip() for x in input("SELECT ATTRIBUTE(S):\n> ").split(",")]
        num_raw = input("\nNUMBER OF GROUPING VARIABLES(n):\n> ")
        num_match = re.search(r'\d+', num_raw)
        phi["n"] = int(num_match.group()) if num_match else 0
        phi["V"] = [x.strip() for x in input("\nGROUPING ATTRIBUTES(V):\n> ").split(",")]
        phi["F"] = [x.strip() for x in input("\nF-VECT([F]):\n> ").split(",")]

        print(f"\nSELECT CONDITION-VECT([sigma]): (Enter predicates as var.col op val, blank to finish)")
        while True:
            line = input("> ").strip()
            if not line: break
            m = re.match(r"(\d+)\s*\.\s*(\w+)\s*(!=|<>|<=|>=|<|>|=)\s*(.+)$", line)
            if m:
                var, col, op, raw_val = m.group(1), m.group(2), m.group(3), m.group(4).strip()
                py_op = "!=" if op == "<>" else ("==" if op == "=" else op)
                if (raw_val.startswith("'") and raw_val.endswith("'")) or \
                   (raw_val.startswith('"') and raw_val.endswith('"')):
                    val = f"'{raw_val[1:-1]}'"
                else:
                    try: int(raw_val); val = raw_val
                    except ValueError:
                        try: float(raw_val); val = raw_val
                        except ValueError: val = f"'{raw_val}'"
                predicate = f"row['{col}']{py_op}{val}"
                if var not in phi["sigma"]:
                    phi["sigma"][var] = []
                phi["sigma"][var].append(predicate)

        raw_g = input("\nHAVING CONDITION(G):\n> ").strip()
        phi["G"] = re.sub(r"\b(\d+)_", r"obj.v\1_", raw_g).strip() if raw_g else ""
        queries = [phi]

    for query_num, phi in enumerate(queries):
        # Auto-detect global aggs (e.g. "avg_quant") from S or F, rewrite as "0_avg_quant".
        # They do not need to be declared in F -- referencing them in S is enough.
        global_pat = re.compile(r"^(sum|count|avg|min|max)_\w+$", re.IGNORECASE)
        phi["S"] = ["0_" + a if global_pat.match(a) else a for a in phi["S"]]
        phi["F"] = ["0_" + a if global_pat.match(a) else a for a in phi["F"]]
        for a in phi["S"]:
            if a.startswith("0_") and a not in phi["F"]:
                phi["F"].append(a)
        if any(a.startswith("0_") for a in phi["F"]):
            phi["sigma"]["0"] = []  # no condition = every row matches

        # 1. MF Class setup
        agg_init_lines = []
        for agg in phi["F"]:
            agg = agg.strip()
            func_m = re.search(r'_?(sum|count|avg|min|max)_', agg, re.IGNORECASE)
            if func_m and func_m.group(1).lower() in ('min', 'max'):
                agg_init_lines.append(f"        self.v{agg} = None")
            else:
                agg_init_lines.append(f"        self.v{agg} = 0")
        agg_init = "\n".join(agg_init_lines)

        # Trackers for avg: one sum+count pair per (var_id, col)
        internal_trackers = []
        seen_avg_trackers = set()
        for agg in phi["F"]:
            agg = agg.strip()
            avg_match = re.match(r"^(\d+)_avg_(\w+)$", agg, re.IGNORECASE)
            if avg_match:
                v_id, col = avg_match.group(1), avg_match.group(2)
                if (v_id, col) not in seen_avg_trackers:
                    seen_avg_trackers.add((v_id, col))
                    internal_trackers.append(f"        self.v{v_id}_sum_{col} = 0")
                    internal_trackers.append(f"        self.v{v_id}_cnt_{col} = 0")

        trackers_code = "\n".join(internal_trackers)
        group_init = "\n".join([f"        self.{attr} = {attr}" for attr in phi["V"]])
        
        class_def = f"""
class MFStructureRow:
    def __init__(self, {', '.join(phi['V'])}):
{group_init}
{agg_init}
{trackers_code}
"""
        # 2. Scans -- one per grouping variable (var "0" = no condition = global)
        scans_code = ""
        for var_id, predicates in phi["sigma"].items():
            combined = " and ".join(predicates) if predicates else "True"

            var_aggs = [a.strip() for a in phi["F"] if re.match(rf"^{var_id}_", a.strip(), re.IGNORECASE)]

            agg_update_lines = []
            for agg in var_aggs:
                func_match = re.match(r"^\d+_(sum|count|avg|min|max)_(\w+)$", agg, re.IGNORECASE)
                if not func_match: continue
                func = func_match.group(1).lower()
                col  = func_match.group(2).lower()

                if func == "sum":
                    agg_update_lines.append(f"            obj.v{agg} += row['{col}']")
                elif func == "count":
                    agg_update_lines.append(f"            obj.v{agg} += 1")
                elif func == "avg":
                    agg_update_lines.append(f"            obj.v{var_id}_sum_{col} += row['{col}']")
                    agg_update_lines.append(f"            obj.v{var_id}_cnt_{col} += 1")
                elif func == "min":
                    agg_update_lines.append(
                        f"            obj.v{agg} = row['{col}'] if obj.v{agg} is None else min(obj.v{agg}, row['{col}'])"
                    )
                elif func == "max":
                    agg_update_lines.append(
                        f"            obj.v{agg} = row['{col}'] if obj.v{agg} is None else max(obj.v{agg}, row['{col}'])"
                    )

            agg_updates = "\n".join(agg_update_lines) if agg_update_lines else "            pass"

            scans_code += f"""
    cur.execute("SELECT * FROM sales")
    for row in cur:
        if {combined}:
            key = tuple(row[attr] for attr in {phi['V']})
            obj = mf_struct[key]
{agg_updates}
"""

        # 3. Finalize avgs
        avg_finalize = ""
        for agg in phi["F"]:
            agg = agg.strip()
            avg_match = re.match(r"^(\d+)_avg_(\w+)$", agg, re.IGNORECASE)
            if avg_match:
                v_id, col = avg_match.group(1), avg_match.group(2)
                avg_finalize += f"\n        if obj.v{v_id}_cnt_{col} > 0: obj.v{agg} = obj.v{v_id}_sum_{col} / obj.v{v_id}_cnt_{col}"

        # Normalize having: AND/OR case-insensitive, = -> ==, <> -> !=
        having_str = phi["G"]
        having_str = re.sub(r'\bAND\b', 'and', having_str, flags=re.IGNORECASE)
        having_str = re.sub(r'\bOR\b',  'or',  having_str, flags=re.IGNORECASE)
        having_str = re.sub(r'(?<![!<>])=(?!=)', '==', having_str)
        having_str = having_str.replace('<>', '!=')

        having_cond = f"if {having_str}:" if having_str else ""
        res_indent  = "            " if having_str else "        "

        final_logic = f"""
    _global_res = []
    for key in mf_struct:
        obj = mf_struct[key]
{avg_finalize}
        {having_cond}
{res_indent}res = {{}}
{res_indent}for attr in {phi['S']}:
{res_indent}    target = attr if attr in {phi['V']} else 'v' + attr
{res_indent}    res[attr] = getattr(obj, target, 0)
{res_indent}_global_res.append(res)
"""
        tmp = f"""
import os, psycopg2, psycopg2.extras, tabulate
from dotenv import load_dotenv
{class_def}
def query():
    load_dotenv()
    conn = psycopg2.connect(dbname=os.getenv('DBNAME'), user=os.getenv('USER'),
                            password=os.getenv('PASSWORD'), host=os.getenv('HOST', 'localhost'),
                            cursor_factory=psycopg2.extras.DictCursor)
    cur = conn.cursor()
    mf_struct = {{}}
    cur.execute("SELECT DISTINCT {', '.join(phi['V'])} FROM sales")
    for row in cur:
        key = tuple(row[attr] for attr in {phi['V']})
        mf_struct[key] = MFStructureRow(*[row[a] for a in {phi['V']}])
{scans_code}
{final_logic}
    cur.close(); conn.close()
    return tabulate.tabulate(_global_res, headers="keys", tablefmt="psql")

if __name__ == "__main__":
    print(query())
"""
        with open("_generated.py", "w") as f: f.write(tmp)
        subprocess.run(["python", "_generated.py"])

if __name__ == "__main__":
    main()