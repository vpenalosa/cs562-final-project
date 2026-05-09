
import os, psycopg2, psycopg2.extras, tabulate
from dotenv import load_dotenv

class MFStructureRow:
    def __init__(self, state):
        self.state = state
        self.v1_count_quant = 0
        self.v2_count_quant = 0


def query():
    load_dotenv()
    conn = psycopg2.connect(dbname=os.getenv('DBNAME'), user=os.getenv('USER'),
                            password=os.getenv('PASSWORD'), host=os.getenv('HOST', 'localhost'),
                            cursor_factory=psycopg2.extras.DictCursor)
    cur = conn.cursor()
    mf_struct = {}
    cur.execute("SELECT DISTINCT state FROM sales")
    for row in cur:
        key = tuple(row[attr] for attr in ['state'])
        mf_struct[key] = MFStructureRow(*[row[a] for a in ['state']])

    cur.execute("SELECT * FROM sales")
    for row in cur:
        if row['quant']>500:
            key = tuple(row[attr] for attr in ['state'])
            obj = mf_struct[key]
            obj.v1_count_quant += 1

    cur.execute("SELECT * FROM sales")
    for row in cur:
        if row['quant']<100:
            key = tuple(row[attr] for attr in ['state'])
            obj = mf_struct[key]
            obj.v2_count_quant += 1


    _global_res = []
    for key in mf_struct:
        obj = mf_struct[key]

        if obj.v1_count_quant > obj.v2_count_quant:
            res = {}
            for attr in ['state', '1_count_quant', '2_count_quant']:
                target = attr if attr in ['state'] else 'v' + attr
                res[attr] = getattr(obj, target, 0)
            _global_res.append(res)

    cur.close(); conn.close()
    return tabulate.tabulate(_global_res, headers="keys", tablefmt="psql")

if __name__ == "__main__":
    print(query())
