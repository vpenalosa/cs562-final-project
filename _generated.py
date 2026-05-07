
import os
import psycopg2
import psycopg2.extras
import tabulate
from dotenv import load_dotenv


class MFStructureRow:
    def __init__(self, cust):
        self.cust = cust
        self.v4_sum_quant = 0
        self.v4_avg_quant = 0
        self.v5_sum_quant = 0
        self.v6_sum_quant = 0
        self.v6_avg_quant = 0
        self.v4_count_quant = 0
        self.v5_count_quant = 0
        self.v6_count_quant = 0


def query():
    load_dotenv()
    conn = psycopg2.connect(
        dbname=os.getenv('DBNAME'), user=os.getenv('USER'),
        password=os.getenv('PASSWORD'), host=os.getenv('HOST', 'localhost'),
        cursor_factory=psycopg2.extras.DictCursor
    )
    cur = conn.cursor()
    mf_struct = {}

    # SCAN 0: Initialize groups
    cur.execute("SELECT DISTINCT cust FROM sales")
    for row in cur:
        key = tuple(row[attr] for attr in ['cust'])
        mf_struct[key] = MFStructureRow(*key)


    # SCAN for variable 4
    cur.execute("SELECT * FROM sales")
    for row in cur:
        if state=='NY':
            key = tuple(row[attr] for attr in ['cust'])
            obj = mf_struct[key]
            if hasattr(obj, 'v4_sum_quant'): 
                obj.v4_sum_quant += row['quant']
            if hasattr(obj, 'v4_count_quant'):
                obj.v4_count_quant += 1

    # SCAN for variable 5
    cur.execute("SELECT * FROM sales")
    for row in cur:
        if state=='NJ':
            key = tuple(row[attr] for attr in ['cust'])
            obj = mf_struct[key]
            if hasattr(obj, 'v5_sum_quant'): 
                obj.v5_sum_quant += row['quant']
            if hasattr(obj, 'v5_count_quant'):
                obj.v5_count_quant += 1

    # SCAN for variable 6
    cur.execute("SELECT * FROM sales")
    for row in cur:
        if state=='CT':
            key = tuple(row[attr] for attr in ['cust'])
            obj = mf_struct[key]
            if hasattr(obj, 'v6_sum_quant'): 
                obj.v6_sum_quant += row['quant']
            if hasattr(obj, 'v6_count_quant'):
                obj.v6_count_quant += 1


    _global = []
    for key in mf_struct:
        obj = mf_struct[key]

        s_attr = 'v4_sum_quant'
        c_attr = 'v4_count_quant'
        a_attr = 'v4_avg_quant'
        if hasattr(obj, a_attr) and getattr(obj, c_attr, 0) > 0:
            setattr(obj, a_attr, getattr(obj, s_attr) / getattr(obj, c_attr))

        s_attr = 'v5_sum_quant'
        c_attr = 'v5_count_quant'
        a_attr = 'v5_avg_quant'
        if hasattr(obj, a_attr) and getattr(obj, c_attr, 0) > 0:
            setattr(obj, a_attr, getattr(obj, s_attr) / getattr(obj, c_attr))

        s_attr = 'v6_sum_quant'
        c_attr = 'v6_count_quant'
        a_attr = 'v6_avg_quant'
        if hasattr(obj, a_attr) and getattr(obj, c_attr, 0) > 0:
            setattr(obj, a_attr, getattr(obj, s_attr) / getattr(obj, c_attr))

        if obj.v4_sum_quant > 2 * obj.v5_sum_quant or obj.v4_avg_quant > obj.v6_avg_quant:
            res = {}
            for attr in ['cust', '4_sum_quant', '5_sum_quant', '6_sum_quant']:
                target_attr = attr if attr in ['cust'] else 'v' + attr
                res[attr] = getattr(obj, target_attr)
            _global.append(res)

    cur.close()
    conn.close()
    return tabulate.tabulate(_global, headers="keys", tablefmt="psql")

if __name__ == "__main__":
    print(query())
