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
            elif "SELECT CONDITION-VECT" in clean_line.upper(): curr_section = "sigma"
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
                    is_match = re.search(r"(\d+)\.(.*)", clean_line)
                    if is_match:
                        var, cond = is_match.groups()
                        py_cond = cond.replace("=", "==")
                        if "==" in py_cond:
                            parts = py_cond.split("==")
                            current_config["sigma"][var.strip()] = f"row['{parts[0].strip()}']=={parts[1].strip()}"
                elif curr_section == "G":
                    current_config["G"] = re.sub(r"\b(\d+)_", r"obj.v\1_", clean_line).strip()

        if current_config:
            all_queries.append(current_config)
            
    return all_queries

def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else "queries.txt"
    queries = parse_queries_file(input_file)

    for query_num, phi in enumerate(queries):
        print(f"OUTPUT FOR QUERY {query_num + 1}:")

        # 1. Initialize Attributes and global math trackers
        agg_init = "\n".join([f"        self.v{agg} = 0" for agg in phi["F"]])
        
        # Trackers for EVERY row (to get true overall average)
        overall_trackers = [
            "        self.v_overall_sum = 0",
            "        self.v_overall_count = 0",
            "        self.vavg_quant = 0"
        ]
        
        # Trackers for specific grouping variables 1...n
        internal_trackers = []
        for i in range(1, phi["n"] + 1):
            internal_trackers.append(f"        self.v{i}_sum_quant = 0")
            internal_trackers.append(f"        self.v{i}_count_quant = 0")
        
        trackers_code = "\n".join(overall_trackers + internal_trackers)
        group_init = "\n".join([f"        self.{attr} = {attr}" for attr in phi["V"]])
        
        class_def = f"""
class MFStructureRow:
    def __init__(self, {', '.join(phi['V'])}):
{group_init}
{agg_init}
{trackers_code}
"""

        # 2. Scans
        # We perform one pass to update overall averages and another for specific conditions
        scans_code = f"""
    # Pass to calculate overall average per customer
    cur.execute("SELECT * FROM sales")
    for row in cur:
        key = tuple(row[attr] for attr in {phi['V']})
        obj = mf_struct[key]
        obj.v_overall_sum += row['quant']
        obj.v_overall_count += 1
"""
        for var_id, cond in phi["sigma"].items():
            scans_code += f"""
    # Pass for grouping variable {var_id}
    cur.execute("SELECT * FROM sales")
    for row in cur:
        if {cond}:
            key = tuple(row[attr] for attr in {phi['V']})
            obj = mf_struct[key]
            
            # Update explicit F-VECT attributes
            for agg in {phi['F']}:
                if agg.startswith("{var_id}_"):
                    if "sum" in agg: setattr(obj, 'v' + agg, getattr(obj, 'v' + agg) + row['quant'])
                    if "count" in agg: setattr(obj, 'v' + agg, getattr(obj, 'v' + agg) + 1)
            
            # Update internal trackers for state-specific averages
            obj.v{var_id}_sum_quant += row['quant']
            obj.v{var_id}_count_quant += 1
"""

        # 3. Final Average Calculations
        avg_loops = ""
        for agg in phi["F"]:
            if "avg" in agg:
                match = re.search(r'(\d+)_avg', agg)
                if match:
                    v_id = match.group(1)
                    avg_loops += f"""
        if obj.v{v_id}_count_quant > 0:
            obj.v{agg} = obj.v{v_id}_sum_quant / obj.v{v_id}_count_quant
"""

        # True overall average calculation
        avg_loops += f"""
        if obj.v_overall_count > 0:
            obj.vavg_quant = obj.v_overall_sum / obj.v_overall_count
"""

        having_cond = f"if {phi['G']}:" if phi['G'] else ""
        res_indent = "            " if phi['G'] else "        "
        
        final_logic = f"""
    _global_res = []
    for key in mf_struct:
        obj = mf_struct[key]
{avg_loops}
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