import subprocess
import os
import re
import sys

def parse_queries_file(filename):
    if not os.path.exists(filename):
        return []
    
    all_queries = []
    current_config = None
    curr_section = ""

    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            
            # If we see "SELECT ATTRIBUTE", it means a new query block is starting
            if "SELECT ATTRIBUTE" in line:
                if current_config:
                    all_queries.append(current_config)
                current_config = {"S": [], "n": 0, "V": [], "F": [], "sigma": {}, "G": ""}
                curr_section = "S"
            elif "NUMBER OF GROUPING VARIABLES" in line: curr_section = "n"
            elif "GROUPING ATTRIBUTES" in line: curr_section = "V"
            elif "F-VECT" in line: curr_section = "F"
            elif "SELECT CONDITION-VECT" in line: curr_section = "sigma"
            elif "HAVING CONDITION" in line: curr_section = "G"
            else:
                if not current_config: continue
                # Data parsing logic
                if curr_section == "S": current_config["S"] = [x.strip() for x in line.split(",")]
                elif curr_section == "n": current_config["n"] = int(line)
                elif curr_section == "V": current_config["V"] = [x.strip() for x in line.split(",")]
                elif curr_section == "F": current_config["F"] = [x.strip() for x in line.split(",")]
                elif curr_section == "sigma":
                    is_match = re.search(r"([a-zA-Z0-9]+)\.(.*)", line)
                    if is_match:
                        var, cond = is_match.groups()
                        current_config["sigma"][var.strip()] = cond.replace("=", "==")
                elif curr_section == "G":
                    temp_g = re.sub(r"\b([a-zA-Z0-9]+)_", r"obj.v\1_", line)
                    current_config["G"] = temp_g.replace(";", "").strip()

        # Append the very last query in the file
        if current_config:
            all_queries.append(current_config)
            
    return all_queries

def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else "queries.txt"
    # queries is now a LIST of dictionaries
    queries = parse_queries_file(input_file)
    
    if not queries:
        print("Error: No queries found or file is empty.")
        return

    # Loop through each query found in the file
    for index, phi in enumerate(queries):
        print(f"\n{'='*25}")
        print(f"  RUNNING QUERY {index + 1}")
        print(f"{'='*25}\n")

        # --- 1. Generate MF-Structure Class ---
        agg_init = "\n".join([f"        self.v{agg} = 0" for agg in phi["F"]])
        count_trackers = "\n".join([f"        self.v{v}_count_quant = 0" for v in phi["sigma"].keys()])
        group_init = "\n".join([f"        self.{attr} = {attr}" for attr in phi["V"]])
        
        class_def = f"""
class MFStructureRow:
    def __init__(self, {', '.join(phi['V'])}):
{group_init}
{agg_init}
{count_trackers}
"""

        # --- 2. Generate Scans ---
        scans_code = ""
        for var_name in phi["sigma"].keys():
            cond = phi["sigma"][var_name]
            scans_code += f"""
    # SCAN for variable {var_name}
    cur.execute("SELECT * FROM sales")
    for row in cur:
        if {cond}:
            key = tuple(row[attr] for attr in {phi['V']})
            obj = mf_struct[key]
            if hasattr(obj, 'v{var_name}_sum_quant'): 
                obj.v{var_name}_sum_quant += row['quant']
            if hasattr(obj, 'v{var_name}_count_quant'):
                obj.v{var_name}_count_quant += 1
"""

        # --- 3. Final Output Logic ---
        avg_loops = ""
        for var_name in phi["sigma"].keys():
            avg_loops += f"""
        s_attr = 'v{var_name}_sum_quant'
        c_attr = 'v{var_name}_count_quant'
        a_attr = 'v{var_name}_avg_quant'
        if hasattr(obj, a_attr) and getattr(obj, c_attr, 0) > 0:
            setattr(obj, a_attr, getattr(obj, s_attr) / getattr(obj, c_attr))
"""

        final_logic = f"""
    _global = []
    for key in mf_struct:
        obj = mf_struct[key]
{avg_loops}
        if {phi['G']}:
            res = {{}}
            for attr in {phi['S']}:
                target_attr = attr if attr in {phi['V']} else 'v' + attr
                res[attr] = getattr(obj, target_attr)
            _global.append(res)
"""

        # --- 4. Assemble and Run ---
        tmp = f"""
import os
import psycopg2
import psycopg2.extras
import tabulate
from dotenv import load_dotenv

{class_def}

def query():
    load_dotenv()
    conn = psycopg2.connect(
        dbname=os.getenv('DBNAME'), user=os.getenv('USER'),
        password=os.getenv('PASSWORD'), host=os.getenv('HOST', 'localhost'),
        cursor_factory=psycopg2.extras.DictCursor
    )
    cur = conn.cursor()
    mf_struct = {{}}

    cur.execute("SELECT DISTINCT {', '.join(phi['V'])} FROM sales")
    for row in cur:
        key = tuple(row[attr] for attr in {phi['V']})
        mf_struct[key] = MFStructureRow(*[row[a] for a in {phi['V']}])

{scans_code}
{final_logic}
    cur.close()
    conn.close()
    return tabulate.tabulate(_global, headers="keys", tablefmt="psql")

if __name__ == "__main__":
    print(query())
"""
        # Write and run for THIS specific query
        with open("_generated.py", "w") as f:
            f.write(tmp)
        
        subprocess.run(["python", "_generated.py"])