import json
import sqlite3
import time
import tkinter as tk
from tkinter import messagebox

import matplotlib.pyplot as plt
import requests
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import IDGrabber

db_path = 'data.db'
USER_AGENT = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/135.0.0.0 Mobile Safari/537.36")
node_name_dicts = {}
previous_rows = []  # 用于存储上一次查询的结果
id_dict, leaves_dict = IDGrabber.init_id_dict()


def init_tables():
    """初始化数据库，如果表已存在则跳过创建"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 检查表是否存在并创建数据集表
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='datasets'
        """)
        if cursor.fetchone() is None:
            cursor.execute('''
                CREATE TABLE datasets (
                    dataset_id TEXT PRIMARY KEY,
                    dataset_name TEXT               -- 数据集名称
                );
            ''')

        # 检查表是否存在并创建数据点表
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='data_points'
        """)
        if cursor.fetchone() is None:
            cursor.execute('''
                CREATE TABLE data_points (
                    dataset_id TEXT NOT NULL,
                    time TEXT NOT NULL,                 -- 时间字符串
                    name TEXT NOT NULL,                 -- 指标名称字符串
                    value REAL,                         -- 浮点数值
                    FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id),
                    UNIQUE(dataset_id, time, name)      -- 防止重复数据
                );
            ''')
        conn.commit()
    except sqlite3.Error as e:
        print(f"An error occurred: {e.args[0]}")
    finally:
        conn.close()


def init_dataset(dataset_id: str):
    """初始化数据集（如果不存在则创建）"""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        # 检查数据集是否已存在
        cursor.execute("SELECT dataset_id FROM datasets WHERE dataset_id = ?", (dataset_id,))
        existing = cursor.fetchone()
        if existing is None:
            # 插入新数据集
            cursor.execute("""
                    INSERT INTO datasets (dataset_id,dataset_name)
                    VALUES (?,?)
                """, (dataset_id, id_dict[dataset_id].name))
    finally:
        conn.commit()
        conn.close()


def insert_data_point(dataset_id, time, name, value):
    """插入数据点（如果不存在）"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        # 检查数据集ID是否存在
        cursor.execute("SELECT 1 FROM datasets WHERE dataset_id = ?", (dataset_id,))
        if cursor.fetchone() is None:
            raise ValueError(f"数据集ID {dataset_id} 不存在，请先初始化数据集。")

        # 尝试插入数据点
        cursor.execute("""
            INSERT INTO data_points (dataset_id, time, name, value)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(dataset_id, time, name) DO UPDATE SET value=excluded.value
        """, (dataset_id, time, name, value))
    except sqlite3.Error as e:
        raise Exception(f"插入数据点错误: {str(e)}")
    finally:
        conn.commit()
        conn.close()


# 爬取数据并存入数据库
def fetch_data():
    global node_name_dicts
    # generate the URL
    source_name_argument = '{"wdcode":"zb","valuecode":"' + source_name.get() + '"}'
    time_scope_argument = '{"wdcode":"sj","valuecode":"' + time_scope.get() + '"}'

    dfwds_argument = f"&dfwds=[{source_name_argument},{time_scope_argument}]"
    time_argument = f'&k1={time.time()}&h=1'
    url = "https://data.stats.gov.cn/easyquery.htm?m=QueryData&dbcode=hgyd&rowcode=zb&colcode=sj&wds=[]" + dfwds_argument + time_argument

    try:
        # 初始化数据集
        init_dataset(source_name.get())

        response = requests.post(url, headers={'User-Agent': USER_AGENT})
        if response.status_code != 200:
            raise Exception(f"Failed to fetch data from {url}, status code: {response.status_code}")

        returndata = json.loads(response.text)["returndata"]

        # read the node names from the JSON response and store them in a global dict
        wdnodes = returndata["wdnodes"]
        for wdnode in wdnodes:
            wdcode = wdnode["wdcode"]
            if wdcode not in node_name_dicts:
                node_name_dicts[wdcode] = {}
            nodes = wdnode["nodes"]
            for node in nodes:
                node_name_dicts[wdcode][node["code"]] = node["name"]

        # translate the datanodes and transform the data
        datanodes = returndata["datanodes"]
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
            # 插入数据点到数据库
            insert_data_point(source_name.get(), node_time, node_name, data)

        # cursor.execute('INSERT INTO data (url, content) VALUES (?, ?)', (url, response.text))
        # conn.commit()
        messagebox.showinfo('Success', 'Data fetched and stored successfully!')
    except Exception as e:
        messagebox.showerror('Error', str(e))


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
    global root, source_name, time_scope, search_id, search_name, text_area

    root = tk.Tk()
    root.title("国家统计局数据爬取与可视化工具")

    tk.Label(root, text="输入对应的表的序号:").pack()
    source_name = tk.Entry(root, width=50)
    source_name.insert(0, "A01030H")
    source_name.pack()

    tk.Label(root, text="输入对应的时间:").pack()
    time_scope = tk.Entry(root, width=50)
    time_scope.insert(0, "LAST13")
    time_scope.pack()

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
