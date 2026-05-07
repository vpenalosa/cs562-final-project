import subprocess
import os
import re
import sys

def parse_queries_file(filename):
    if not os.path.exists(filename):
        print(f"Error: {filename} not found.")
        return []
    
    #create list of queries
    all_queries = []
    current_config = None
    curr_section = ""

    with open(filename, 'r') as f:
        for line in f:
            clean_line = line.strip()
            if not clean_line: continue

            #mark start of query using S phi operator
            if "SELECT ATTRIBUTE" in clean_line.upper():

                #save previous query, if one is available
                if current_config:
                    all_queries.append(current_config)
                #set up phi operators for current query
                current_config = {"S": [], "n": 0, "V": [], "F": [], "sigma": {}, "G": ""}
                curr_section = "S"
            elif "NUMBER OF GROUPING" in clean_line.upper(): curr_section = "n"
            elif "GROUPING ATTRIBUTES" in clean_line.upper(): curr_section = "V"
            elif "F-VECT" in clean_line.upper(): curr_section = "F"
            elif "SELECT CONDITION-VECT" in clean_line.upper(): curr_section = "sigma"
            elif "HAVING CONDITION" in clean_line.upper(): curr_section = "G"
            else:
                #connect data to correct part of the current phi operator
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

                    #puts condition into python form
                    is_match = re.search(r"([a-zA-Z0-9]+)\.(.*)", clean_line)
                    if is_match:

                        #split is_match into variable and condition (1.state='NY' to var=1, cond="state='NY'")
                        var, cond = is_match.groups()

                        #turn condition into python form (state='NY' to state=='NY')
                        py_cond = cond.replace("=", "==")

                        #split condition into variable and value
                        if "==" in py_cond:
                            parts = py_cond.split("==")
                            current_config["sigma"][var.strip()] = f"row['{parts[0].strip()}']=={parts[1].strip()}"
                elif curr_section == "G":

                    #replaces 1_sum with obj.v1_sum
                    current_config["G"] = re.sub(r"\b([a-zA-Z0-9]+)_", r"obj.v\1_", clean_line).strip()

        #add current query configuration to list of queries
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

        raw = input("SELECT ATTRIBUTE(S):\n> ")
        phi["S"] = [x.strip() for x in raw.split(",")]

        raw = input("\nNUMBER OF GROUPING VARIABLES(n):\n> ")
        num = re.search(r'\d+', raw)
        phi["n"] = int(num.group()) if num else 0

        raw = input("\nGROUPING ATTRIBUTES(V):\n> ")
        phi["V"] = [x.strip() for x in raw.split(",")]

        raw = input("\nF-VECT([F]):\n> ")
        phi["F"] = [x.strip() for x in raw.split(",")]

        print("\nSELECT CONDITION-VECT([sigma]):")
        print(f"(Enter {phi['n']} condition(s), one per line, e.g. 1.state='NY')")
        for _ in range(phi["n"]):
            line = input("> ").strip()
            is_match = re.search(r"([a-zA-Z0-9]+)\.(.*)", line)
            if is_match:
                var, cond = is_match.groups()
                py_cond = cond.replace("=", "==")
                if "==" in py_cond:
                    parts = py_cond.split("==")
                    phi["sigma"][var.strip()] = f"row['{parts[0].strip()}']=={parts[1].strip()}"

        raw = input("\nHAVING CONDITION(G) [optional, press Enter to skip]:\n> ").strip()
        phi["G"] = re.sub(r"\b([a-zA-Z0-9]+)_", r"obj.v\1_", raw).strip() if raw else ""

        queries = [phi]

    if not queries:
        print("No queries found in file.")
        return

    for query_num, phi in enumerate(queries):
        print(f"OUTPUT FOR QUERY {query_num + 1}:")

        #transform values from F to work for python (1_sum_quant turns into self.v1_sum_quant=0)
        agg_init = "\n".join([f"        self.v{agg} = 0" for agg in phi["F"]])

        #count how many rows satisfy specific condition for each grouping variable
        count_trackers = "\n".join([f"        self.v{v}_count_quant = 0" for v in phi["sigma"].keys()])

        #self.grouping_attribute (self.cust)
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

        # Build the having filter line — omit it entirely if G is empty
        if phi["G"]:
            having_check = f"        if {phi['G']}:"
            result_indent = "            "
        else:
            having_check = ""
            result_indent = "        "

        final_logic = f"""
    _global = []
    for key in mf_struct:
        obj = mf_struct[key]
{avg_loops}
{having_check}
{result_indent}res = {{}}
{result_indent}for attr in {phi['S']}:
{result_indent}    target_attr = attr if attr in {phi['V']} else 'v' + attr
{result_indent}    res[attr] = getattr(obj, target_attr)
{result_indent}_global.append(res)
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