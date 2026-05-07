import subprocess
import os
import re
import sys

def parse_queries_file(filename):
    #6 phi operators
    config = {"S": [], "n": 0, "V": [], "F": [], "sigma": {}, "G": ""}
    curr = ""

    if not os.path.exists(filename):
        print(f"Error: {filename} not found.")
        return None
    
    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            
            #identify the current section of phi operator
            if "SELECT ATTRIBUTE" in line: curr = "S"
            elif "NUMBER OF GROUPING VARIABLES" in line: curr = "n"
            elif "GROUPING ATTRIBUTES" in line: curr = "V"
            elif "F-VECT" in line: curr = "F"
            elif "SELECT CONDITION-VECT" in line: curr = "sigma"
            elif "HAVING CONDITION" in line: curr = "G"
            else:
                #put values from lines in config
                if curr == "S": 
                    config["S"] = [x.strip() for x in line.split(",")]
                elif curr == "n": 
                    config["n"] = int(line)
                elif curr == "V": 
                    config["V"] = [x.strip() for x in line.split(",")]
                elif curr == "F": 
                    config["F"] = [x.strip() for x in line.split(",")]
                elif curr == "sigma":
                    #matches both 'variable.attribute'
                    is_match = re.search(r"([a-zA-Z0-9]+)\.(.*)", line)
                    if is_match:
                        var_name, cond = is_match.groups()
                        py_cond = cond.replace("=", "==")
                        if "==" in py_cond:
                            parts = py_cond.split("==")
                            col = parts[0].strip()
                            val = parts[1].strip()
                            config["sigma"][var_name.strip()] = f"row['{col}']=={val}"
                elif curr == "G":
                    #format variable to match python syntax
                    #use \b to prevent "obj.v1_obj.vsum" double-replacement
                    temp_g = re.sub(r"\b([a-zA-Z0-9]+)_", r"obj.v\1_", line)
                    config["G"] = temp_g.replace(";", "").strip()
    return config

def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else "queries.txt"
    phi = parse_queries_file(input_file)
    
    if not phi or not phi["sigma"]:
        print("Error: Could not parse Phi components. Check queries.txt.")
        return

    # --- 1. Generate MF-Structure Class ---
    agg_init = "\n".join([f"        self.v{agg} = 0" for agg in phi["F"]])
    # Create count trackers for all variables to support average calculations
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

    # --- 4. Assemble the Script ---
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

    # SCAN 0: Initialize groups
    cur.execute("SELECT DISTINCT {', '.join(phi['V'])} FROM sales")
    for row in cur:
        key = tuple(row[attr] for attr in {phi['V']})
        mf_struct[key] = MFStructureRow(*key)

{scans_code}
{final_logic}
    cur.close()
    conn.close()
    return tabulate.tabulate(_global, headers="keys", tablefmt="psql")

if __name__ == "__main__":
    print(query())
"""

    with open("_generated.py", "w") as f:
        f.write(tmp)
    
    print(f"--- Compiled _generated.py with {len(phi['sigma'])+1} scans ---")
    
    # Try to run the generated script automatically
    try:
        subprocess.run(["python", "_generated.py"], check=True)
    except subprocess.CalledProcessError:
        print("Error: _generated.py crashed. Check the file for syntax errors.")

if __name__ == "__main__":
    main()