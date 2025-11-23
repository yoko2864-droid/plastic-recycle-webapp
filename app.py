import os
import pathlib
import importlib.util
import ast
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, jsonify, abort

# 如果你把上傳檔放在同一資料夾就用下面的預設名稱
USER_PY_PATH = "Plastic Recycling Classification Helper.py"
DB_PATH = 'database.db'
# 管理介面的 key，部署時請用環境變數 PLASTIC_ADMIN_KEY 覆蓋
ADMIN_KEY = os.environ.get('PLASTIC_ADMIN_KEY', 'letmein')

app = Flask(__name__, template_folder='templates', static_folder='static')


def load_plastic_data_from_file(path):
    p = pathlib.Path(path)
    if not p.exists():
        return []
    # 先嘗試用安全的匯入（如果 user 檔案會啟動 GUI，這可能失敗）
    try:
        spec = importlib.util.spec_from_file_location('user_module', str(p))
        user_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(user_mod)
        data = getattr(user_mod, 'plastic_data', None)
        if data is not None:
            return data
    except Exception:
        pass
    # fallback: 以 AST 抽取 literal plastic_data（不執行其它程式）
    src = p.read_text(encoding='utf-8')
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if getattr(t, "id", None) == "plastic_data":
                    try:
                        return ast.literal_eval(node.value)
                    except Exception:
                        return []
    return []


def get_db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            物品 TEXT,
            材質 TEXT,
            回收標示 TEXT,
            建議 TEXT,
            丟棄方式 TEXT,
            可回收性 TEXT,
            替代建議 TEXT,
            備註 TEXT
        )
    ''')
    conn.commit()
    # 如果資料表是空的，就從 user 檔匯入
    c.execute('SELECT COUNT(*) FROM items')
    count = c.fetchone()[0]
    if count == 0:
        data = load_plastic_data_from_file(USER_PY_PATH)
        for item in data:
            c.execute('''INSERT INTO items (物品, 材質, 回收標示, 建議, 丟棄方式, 可回收性, 替代建議, 備註)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', (
                item.get('物品'),
                item.get('材質'),
                item.get('回收標示'),
                item.get('建議'),
                item.get('丟棄方式'),
                item.get('可回收性'),
                item.get('替代建議'),
                item.get('備註')
            ))
        conn.commit()
    conn.close()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/search')
def api_search():
    q = request.args.get('q', '').strip()
    material = request.args.get('材質', '').strip()
    label = request.args.get('回收標示', '').strip()
    recyclable = request.args.get('可回收性', '').strip()

    conn = get_db_conn(); c = conn.cursor()
    sql = "SELECT * FROM items WHERE 1=1"
    params = []
    if q:
        sql += " AND 物品 LIKE ?"
        params.append(f'%{q}%')
    if material:
        sql += " AND 材質 = ?"
        params.append(material)
    if label:
        sql += " AND 回收標示 = ?"
        params.append(label)
    if recyclable:
        sql += " AND 可回收性 = ?"
        params.append(recyclable)
    sql += " ORDER BY 物品"
    c.execute(sql, params)
    rows = c.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/filters')
def api_filters():
    conn = get_db_conn(); c = conn.cursor()
    filters = {}
    for col in ('材質', '回收標示', '可回收性'):
        c.execute(f"SELECT DISTINCT {col} FROM items WHERE {col} IS NOT NULL AND {col} <> '' ORDER BY {col}")
        vals = [r[0] for r in c.fetchall()]
        filters[col] = vals
    conn.close()
    return jsonify(filters)


# --- Admin (protected by key in query string or PLASTIC_ADMIN_KEY env) ---
def check_admin():
    key = request.args.get('key', '')
    return key == ADMIN_KEY


@app.route('/admin')
def admin_index():
    if not check_admin():
        abort(403)
    return render_template('admin.html')


@app.route('/api/admin/items')
def api_admin_items():
    if not check_admin():
        return jsonify({'error': 'forbidden'}), 403
    conn = get_db_conn(); c = conn.cursor()
    c.execute('SELECT * FROM items ORDER BY id')
    rows = c.fetchall(); conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/add', methods=['GET', 'POST'])
def add_item():
    if request.method == 'POST':
        form = request.form
        conn = get_db_conn(); c = conn.cursor()
        c.execute('''INSERT INTO items (物品, 材質, 回收標示, 建議, 丟棄方式, 可回收性, 替代建議, 備註)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', (
            form.get('物品'), form.get('材質'), form.get('回收標示'), form.get('建議'),
            form.get('丟棄方式'), form.get('可回收性'), form.get('替代建議'), form.get('備註')
        ))
        conn.commit(); conn.close()
        return redirect(url_for('index'))
    return render_template('add.html')


@app.route('/edit/<int:item_id>', methods=['GET', 'POST'])
def edit_item(item_id):
    # 編輯僅後台可用（需帶 key）
    if not check_admin():
        abort(403)
    conn = get_db_conn(); c = conn.cursor()
    if request.method == 'POST':
        form = request.form
        c.execute('''UPDATE items SET 物品=?, 材質=?, 回收標示=?, 建議=?, 丟棄方式=?, 可回收性=?, 替代建議=?, 備註=? WHERE id=?''', (
            form.get('物品'), form.get('材質'), form.get('回收標示'), form.get('建議'),
            form.get('丟棄方式'), form.get('可回收性'), form.get('替代建議'), form.get('備註'), item_id
        ))
        conn.commit(); conn.close()
        return redirect(url_for('admin_index') + '?key=' + ADMIN_KEY)
    c.execute('SELECT * FROM items WHERE id=?', (item_id,))
    row = c.fetchone(); conn.close()
    if row:
        return render_template('edit.html', item=dict(row))
    return '項目不存在', 404


@app.route('/delete/<int:item_id>', methods=['POST'])
def delete_item(item_id):
    if not check_admin():
        abort(403)
    conn = get_db_conn(); c = conn.cursor()
    c.execute('DELETE FROM items WHERE id=?', (item_id,))
    conn.commit(); conn.close()
    return redirect(url_for('admin_index') + '?key=' + ADMIN_KEY)


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
