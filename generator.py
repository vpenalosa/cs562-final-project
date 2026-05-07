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
            
            # Use headers from your file  to split queries
            if "SELECT ATTRIBUTE" in clean_line.upper():
                if current_config:
                    all_queries.append(current_config)
                current_config = {"S": [], "n": 0, "V": [], "F": [], "sigma": {}, "G": ""}
                curr_section = "S"
            elif "NUMBER OF GROUPING" in clean_line.upper(): curr_section = "n"
            elif "GROUPING ATTRIBUTES" in clean_line.upper(): curr_section = "V"
            elif "F-VECT" in clean_line.upper(): curr_section = "F"
            elif "SELECT CONDITION-VECT" in clean_line.upper(): curr_section = "sigma"
            elif "HAVING CONDITION" in clean_line.upper(): curr_section = "G"
            else:
                if not current_config: continue
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
                    # Matches 1.state='NY' or 4.state='NY' 
                    is_match = re.search(r"([a-zA-Z0-9]+)\.(.*)", clean_line)
                    if is_match:
                        var, cond = is_match.groups()
                        py_cond = cond.replace("=", "==")
                        if "==" in py_cond:
                            parts = py_cond.split("==")
                            current_config["sigma"][var.strip()] = f"row['{parts[0].strip()}']=={parts[1].strip()}"
                elif curr_section == "G":
                    # Replaces 1_sum with obj.v1_sum 
                    current_config["G"] = re.sub(r"\b([a-zA-Z0-9]+)_", r"obj.v\1_", clean_line).strip()

        if current_config:
            all_queries.append(current_config)
            
    return all_queries

def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else "queries.txt"
    queries = parse_queries_file(input_file)
    
    if not queries:
        print("No queries found. Check your queries.txt formatting.")
        return

    for index, phi in enumerate(queries):
        print(f"\n{'='*20} OUTPUT FOR QUERY {index + 1} {'='*20}")

        # 1. MF-Structure Class
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

        # 2. Scans
        scans_code = ""
        for var_name, cond in phi["sigma"].items():
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

        # 3. Averages & Having
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

        # 4. Assembly
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
        with open("_generated.py", "w") as f:
            f.write(tmp)
        
        subprocess.run(["python", "_generated.py"])

if __name__ == "__main__":
    main()