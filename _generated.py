
import os, psycopg2, psycopg2.extras, tabulate
from dotenv import load_dotenv


class MFStructureRow:
    def __init__(self, cust):
        self.cust = cust
        self.v1_avg_quant = 0
        self.v2_avg_quant = 0
        self.v3_avg_quant = 0
        self.v_overall_sum = 0
        self.v_overall_count = 0
        self.vavg_quant = 0
        self.v1_sum_quant = 0
        self.v1_count_quant = 0
        self.v2_sum_quant = 0
        self.v2_count_quant = 0
        self.v3_sum_quant = 0
        self.v3_count_quant = 0


def query():
    load_dotenv()
    conn = psycopg2.connect(dbname=os.getenv('DBNAME'), user=os.getenv('USER'),
                            password=os.getenv('PASSWORD'), host=os.getenv('HOST', 'localhost'),
                            cursor_factory=psycopg2.extras.DictCursor)
    cur = conn.cursor()
    mf_struct = {}
    cur.execute("SELECT DISTINCT cust FROM sales")
    for row in cur:
        key = tuple(row[attr] for attr in ['cust'])
        mf_struct[key] = MFStructureRow(*[row[a] for a in ['cust']])

    # Pass to calculate overall average per customer
    cur.execute("SELECT * FROM sales")
    for row in cur:
        key = tuple(row[attr] for attr in ['cust'])
        obj = mf_struct[key]
        obj.v_overall_sum += row['quant']
        obj.v_overall_count += 1

    # Pass for grouping variable 1
    cur.execute("SELECT * FROM sales")
    for row in cur:
        if row['state']=='NY':
            key = tuple(row[attr] for attr in ['cust'])
            obj = mf_struct[key]
            
            # Update explicit F-VECT attributes
            for agg in ['1_avg_quant', '2_avg_quant', '3_avg_quant']:
                if agg.startswith("1_"):
                    if "sum" in agg: setattr(obj, 'v' + agg, getattr(obj, 'v' + agg) + row['quant'])
                    if "count" in agg: setattr(obj, 'v' + agg, getattr(obj, 'v' + agg) + 1)
            
            # Update internal trackers for state-specific averages
            obj.v1_sum_quant += row['quant']
            obj.v1_count_quant += 1

    # Pass for grouping variable 2
    cur.execute("SELECT * FROM sales")
    for row in cur:
        if row['state']=='NJ':
            key = tuple(row[attr] for attr in ['cust'])
            obj = mf_struct[key]
            
            # Update explicit F-VECT attributes
            for agg in ['1_avg_quant', '2_avg_quant', '3_avg_quant']:
                if agg.startswith("2_"):
                    if "sum" in agg: setattr(obj, 'v' + agg, getattr(obj, 'v' + agg) + row['quant'])
                    if "count" in agg: setattr(obj, 'v' + agg, getattr(obj, 'v' + agg) + 1)
            
            # Update internal trackers for state-specific averages
            obj.v2_sum_quant += row['quant']
            obj.v2_count_quant += 1

    # Pass for grouping variable 3
    cur.execute("SELECT * FROM sales")
    for row in cur:
        if row['state']=='CT':
            key = tuple(row[attr] for attr in ['cust'])
            obj = mf_struct[key]
            
            # Update explicit F-VECT attributes
            for agg in ['1_avg_quant', '2_avg_quant', '3_avg_quant']:
                if agg.startswith("3_"):
                    if "sum" in agg: setattr(obj, 'v' + agg, getattr(obj, 'v' + agg) + row['quant'])
                    if "count" in agg: setattr(obj, 'v' + agg, getattr(obj, 'v' + agg) + 1)
            
            # Update internal trackers for state-specific averages
            obj.v3_sum_quant += row['quant']
            obj.v3_count_quant += 1


    _global_res = []
    for key in mf_struct:
        obj = mf_struct[key]

        if obj.v1_count_quant > 0:
            obj.v1_avg_quant = obj.v1_sum_quant / obj.v1_count_quant

        if obj.v2_count_quant > 0:
            obj.v2_avg_quant = obj.v2_sum_quant / obj.v2_count_quant

        if obj.v3_count_quant > 0:
            obj.v3_avg_quant = obj.v3_sum_quant / obj.v3_count_quant

        if obj.v_overall_count > 0:
            obj.vavg_quant = obj.v_overall_sum / obj.v_overall_count

        
        res = {}
        for attr in ['cust', 'avg_quant', '1_avg_quant', '2_avg_quant', '3_avg_quant']:
            target = attr if attr in ['cust'] else 'v' + attr
            res[attr] = getattr(obj, target, 0)
        _global_res.append(res)

    cur.close(); conn.close()
    return tabulate.tabulate(_global_res, headers="keys", tablefmt="psql")

if __name__ == "__main__":
    print(query())
