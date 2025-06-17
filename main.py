import json
import sqlite3
import time
import tkinter as tk
from tkinter import messagebox

import matplotlib.pyplot as plt
import requests
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import IDGrabber

# 模块的信息填写
__author__ = "Nan"
__version__ = "1.2"
__license__ = "None"

# 默认的数据库存放路径
db_path = 'data.db'

# 设置requests请求头，模拟浏览器访问
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 "
                  "Mobile Safari/537.36",
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Referer': 'https://data.stats.gov.cn/easyquery.htm',  # 伪造来源页面
    'X-Requested-With': 'XMLHttpRequest'  # 表明这是一个AJAX请求，很多网站会检查这个
}
previous_rows = []  # 用于存储上一次查询的结果


def init_tables():
    """
    Initializes the database tables if they do not already exist.

    This function checks for the existence of the `datasets` and `data_points` tables
    in the SQLite database. If the tables are not found, it creates them with the
    appropriate schema.

    Also, if the `datasets` table does not exist, it initializes it with dataset IDs and names
    which are fetched from https://data.stats.gov.cn/easyquery.htm?id=zb&dbcode=hgyd&wdcode=zb&m=getTree

    Raises:
        sqlite3.Error: If an error occurs during database operations.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if the `datasets` table exists, if not, create and initialize it
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='datasets'
        """)
        if cursor.fetchone() is None:
            id_dict, leaf_node_dict = IDGrabber.init_id_dict()
            cursor.execute('''
                CREATE TABLE datasets (
                    dataset_id TEXT PRIMARY KEY,
                    dataset_name TEXT               -- Name of the dataset
                );
            ''')
            for leaf_node_id, leaf_node in leaf_node_dict.items():
                # Check if the dataset already exists, if not, insert it
                cursor.execute("SELECT dataset_id FROM datasets WHERE dataset_id = ?", (leaf_node_id,))
                existing = cursor.fetchone()
                if existing is None:
                    cursor.execute("""
                                   INSERT INTO datasets (dataset_id,dataset_name)
                                   VALUES (?,?)
                               """, (leaf_node_id, leaf_node.name))

        # Check if the `data_points` table exists, and create it if not
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='data_points'
        """)
        if cursor.fetchone() is None:
            cursor.execute('''
                CREATE TABLE data_points (
                    dataset_id TEXT NOT NULL,
                    time TEXT NOT NULL,                 -- Time string
                    name TEXT NOT NULL,                 -- Indicator name string
                    value REAL,                         -- Floating-point value
                    FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id),
                    UNIQUE(dataset_id, time, name)      -- Prevent duplicate data
                );
            ''')

        conn.commit()
    except sqlite3.Error as e:
        print(f"An error occurred: {e.args[0]}")
    finally:
        conn.close()


# 爬取数据并存入数据库
def fetch_data():
    """
    Fetches data from the National Bureau of Statistics API and stores it in the SQLite database.

    This function constructs a URL based on user input for dataset ID and time scope, sends a POST request
    to the API, and processes the returned JSON data. The data is then inserted or updated in the `data_points`
    table of the SQLite database.

    Args:
        None

    Raises:
        Exception: If the API request fails or returns a non-200 status code.
        ValueError: If the data node lacks necessary time or name information, or if the dataset ID does not exist
                    in the database.
        sqlite3.Error: If an error occurs during database operations.

    Returns:
        None
    """
    dataset_id, time_scope = dataset_id_input.get(), time_scope_input.get()
    conn = sqlite3.connect(db_path)

    # building URL with source_name and time_scope arguments
    source_name_argument = '{"wdcode":"zb","valuecode":"' + dataset_id + '"}'
    time_scope_argument = '{"wdcode":"sj","valuecode":"' + time_scope + '"}'
    dfwds_argument = f"&dfwds=[{source_name_argument},{time_scope_argument}]"
    time_argument = f'&k1={int(time.time())}&h=1'
    base_url = "https://data.stats.gov.cn/easyquery.htm?m=QueryData&dbcode=hgyd&rowcode=zb&colcode=sj&wds=[]"
    url = base_url + dfwds_argument + time_argument

    try:
        response = requests.post(url, headers=HEADERS)
        if response.status_code != 200:
            raise Exception(f"Failed to fetch data from {url}, status code: {response.status_code}")

        return_data = json.loads(response.text)["returndata"]

        # read the node names from the JSON response and store them in a dict
        node_name_dicts = {}
        wdnodes = return_data["wdnodes"]
        for wdnode in wdnodes:
            wdcode = wdnode["wdcode"]
            if wdcode not in node_name_dicts:
                node_name_dicts[wdcode] = {}
            nodes = wdnode["nodes"]
            for node in nodes:
                node_name_dicts[wdcode][node["code"]] = node["name"]

        # transform the datanodes and transform the data
        datanodes = return_data["datanodes"]
        for datanode in datanodes:
            data = datanode["data"]["data"]
            wds = datanode["wds"]
            node_time, node_name = "", ""
            for wd in wds:
                if wd["wdcode"] == "zb":
                    node_name = node_name_dicts[wd["wdcode"]][wd["valuecode"]]
                elif wd["wdcode"] == "sj":
                    node_time = wd["valuecode"]
            if node_name == "" or node_time == "":
                raise ValueError("数据节点缺少必要的时间或名称信息。")

            # insert the data into the database
            cursor = conn.cursor()
            # Check if the dataset_id exists in the datasets table
            cursor.execute("SELECT 1 FROM datasets WHERE dataset_id = ?", (dataset_id,))
            if cursor.fetchone() is None:
                raise ValueError(f"数据集ID {dataset_id} 不存在于数据库中，可能需要重新初始化数据库。")

            # insert or update the data point in the data_points table
            cursor.execute("""
                INSERT INTO data_points (dataset_id, time, name, value)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(dataset_id, time, name) DO UPDATE SET value=excluded.value
            """, (dataset_id, node_time, node_name, data))
            conn.commit()

        messagebox.showinfo("成功", f"成功获取了{len(datanodes)}条数据并存储于数据库中。")
    except sqlite3.Error as e:
        messagebox.showerror('数据库错误', f"在获取数据的过程中发生了数据库错误: {str(e)}")
    except Exception as e:
        messagebox.showerror('错误', f"在获取数据的过程中发生了未知错误: {str(e)}")
    finally:
        conn.close()


# 从数据库中提取数据
def retrieve_data():
    """从数据库中提取数据并显示在文本区域"""
    global previous_rows
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        # 查询数据点表中的所有数据
        cursor.execute("""
            SELECT dataset_id, time, name, value
            FROM data_points
            ORDER BY dataset_id
        """, ())

        if search_id.get() != "":
            cursor.execute("""
                SELECT dataset_id, time, name, value
                FROM data_points
                WHERE dataset_id = ?
                ORDER BY name
            """, (search_id.get(),))

        if search_name.get() != "":
            cursor.execute("""
                        SELECT dataset_id, time, name, value
                        FROM data_points
                        WHERE name LIKE ?
                        ORDER BY time
                    """, ("%" + search_name.get() + "%",))
        previous_rows = rows = cursor.fetchall()

        # 清空文本区域并显示查询结果
        text_area.delete(1.0, tk.END)
        if rows:
            for row in rows:
                text_area.insert(tk.END, f"数据集: {IDGrabber.get_full_name(row[0], id_dict)}, "
                                         f"组ID:{row[0]},时间: {row[1]}, 名称: {row[2]}, 值: {row[3]}\n")
        else:
            text_area.insert(tk.END, "未找到匹配的数据。\n")
    except sqlite3.Error as e:
        messagebox.showerror("Error", f"查询数据时出错: {e}")
    finally:
        conn.close()


# 数据可视化
def visualize_data():
    """可视化数据库中的数据"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        rows = previous_rows

        if not rows:
            messagebox.showinfo("Info", "未找到匹配的数据进行可视化。")
            return

        # 准备数据进行可视化
        times = [row[1] for row in rows]
        values = [row[3] for row in rows]
        names = list(set(f"{row[0]}{row[2]}" for row in rows))  # 获取唯一的指标名称

        if len(names) > 1:
            messagebox.showerror("Error", "当前仅支持单一指标的可视化。")
            return

        # 检查是否已有图表，如果没有则创建
        if not plt.get_fignums():
            plt.figure(figsize=(10, 5))

        # 在当前图表上绘制
        plt.plot(times, values, marker='o', label=names[0])
        plt.xlabel("时间")
        plt.ylabel("值")
        plt.title(f"数据集 {id_dict[search_id.get()].name} 的可视化")
        plt.legend()
        plt.grid(True)

        # 设置字体支持中文
        plt.rcParams['font.sans-serif'] = ['SimHei']  # 使用黑体
        plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题

        # 在Tkinter中显示图表
        global fig_canvas
        try:
            fig_canvas.get_tk_widget().destroy()
        except Exception:
            pass
        fig_canvas = FigureCanvasTkAgg(plt.gcf(), master=root)
        fig_canvas.get_tk_widget().pack()
        fig_canvas.draw()

    except sqlite3.Error as e:
        messagebox.showerror("Error", f"可视化数据时出错: {e}")
    finally:
        conn.close()


# GUI界面
def create_gui():
    global root, dataset_id_input, time_scope_input, search_id, search_name, text_area

    root = tk.Tk()
    root.title("国家统计局数据爬取与可视化工具")

    tk.Label(root, text="输入对应的表的序号:").pack()
    dataset_id_input = tk.Entry(root, width=50)
    dataset_id_input.insert(0, "A01030H")
    dataset_id_input.pack()

    tk.Label(root, text="输入对应的时间:").pack()
    time_scope_input = tk.Entry(root, width=50)
    time_scope_input.insert(0, "LAST13")
    time_scope_input.pack()

    # 爬取按钮
    tk.Button(root, text="爬取数据", command=fetch_data).pack()

    # 查询条件输入
    tk.Label(root, text="查询内容（表序号）:").pack()
    search_id = tk.Entry(root, width=30)
    search_id.pack()

    # 查询条件输入
    tk.Label(root, text="查询内容（名称）:").pack()
    search_name = tk.Entry(root, width=30)
    search_name.pack()

    # 查询按钮
    tk.Button(root, text="查询数据", command=retrieve_data).pack()

    # 结果显示区域
    text_area = tk.Text(root, height=15, width=80)
    text_area.pack()

    # 可视化按钮
    tk.Button(root, text="可视化数据", command=visualize_data).pack()

    root.mainloop()


if __name__ == "__main__":
    init_tables()
    create_gui()
