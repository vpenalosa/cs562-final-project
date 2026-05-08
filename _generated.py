
import os, psycopg2, psycopg2.extras, tabulate
from dotenv import load_dotenv

class MFStructureRow:
    def __init__(self, cust):
        self.cust = cust
        self.v1_avg_quant = 0
        self.v2_avg_quant = 0
        self.v3_avg_quant = 0
        self.v0_avg_quant = 0
        self.v1_sum_quant = 0
        self.v1_cnt_quant = 0
        self.v2_sum_quant = 0
        self.v2_cnt_quant = 0
        self.v3_sum_quant = 0
        self.v3_cnt_quant = 0
        self.v0_sum_quant = 0
        self.v0_cnt_quant = 0

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

    cur.execute("SELECT * FROM sales")
    for row in cur:
        if row['state']=='NY':
            key = tuple(row[attr] for attr in ['cust'])
            obj = mf_struct[key]
            obj.v1_sum_quant += row['quant']
            obj.v1_cnt_quant += 1

    cur.execute("SELECT * FROM sales")
    for row in cur:
        if row['state']=='NJ':
            key = tuple(row[attr] for attr in ['cust'])
            obj = mf_struct[key]
            obj.v2_sum_quant += row['quant']
            obj.v2_cnt_quant += 1

    cur.execute("SELECT * FROM sales")
    for row in cur:
        if row['state']=='CT':
            key = tuple(row[attr] for attr in ['cust'])
            obj = mf_struct[key]
            obj.v3_sum_quant += row['quant']
            obj.v3_cnt_quant += 1

    cur.execute("SELECT * FROM sales")
    for row in cur:
        if True:
            key = tuple(row[attr] for attr in ['cust'])
            obj = mf_struct[key]
            obj.v0_sum_quant += row['quant']
            obj.v0_cnt_quant += 1


    _global_res = []
    for key in mf_struct:
        obj = mf_struct[key]

        if obj.v1_cnt_quant > 0: obj.v1_avg_quant = obj.v1_sum_quant / obj.v1_cnt_quant
        else:
            cur.execute("SELECT AVG(quant) FROM sales WHERE cust = %s", [getattr(obj, a) for a in ['cust']])
            _row = cur.fetchone(); obj.v1_avg_quant = float(_row[0] or 0) if _row else 0
        if obj.v2_cnt_quant > 0: obj.v2_avg_quant = obj.v2_sum_quant / obj.v2_cnt_quant
        else:
            cur.execute("SELECT AVG(quant) FROM sales WHERE cust = %s", [getattr(obj, a) for a in ['cust']])
            _row = cur.fetchone(); obj.v2_avg_quant = float(_row[0] or 0) if _row else 0
        if obj.v3_cnt_quant > 0: obj.v3_avg_quant = obj.v3_sum_quant / obj.v3_cnt_quant
        else:
            cur.execute("SELECT AVG(quant) FROM sales WHERE cust = %s", [getattr(obj, a) for a in ['cust']])
            _row = cur.fetchone(); obj.v3_avg_quant = float(_row[0] or 0) if _row else 0
        if obj.v0_cnt_quant > 0: obj.v0_avg_quant = obj.v0_sum_quant / obj.v0_cnt_quant
        else:
            cur.execute("SELECT AVG(quant) FROM sales WHERE cust = %s", [getattr(obj, a) for a in ['cust']])
            _row = cur.fetchone(); obj.v0_avg_quant = float(_row[0] or 0) if _row else 0
        
        res = {}
        for attr in ['cust', '0_avg_quant', '1_avg_quant', '2_avg_quant', '3_avg_quant']:
            target = attr if attr in ['cust'] else 'v' + attr
            res[attr] = getattr(obj, target, 0)
        _global_res.append(res)

    cur.close(); conn.close()
    return tabulate.tabulate(_global_res, headers="keys", tablefmt="psql")

if __name__ == "__main__":
    print(query())
