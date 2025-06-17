import json
import sqlite3
import time
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import messagebox

import matplotlib.pyplot as plt
import matplotlib as mpl
import requests
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

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
previous_results = []  # 用于存储上一次查询的结果

# =============================================================
#                       数据库初始化部分
# =============================================================
ROOT_ID = "zb"


class TreeNode:
    def __init__(self, dataset_id: str, name: str, parent_id: str, is_parent: bool):
        self.dataset_id = dataset_id
        self.name = name
        self.parent_id = parent_id
        self.is_parent = is_parent


def grabID(parent_id: str, id_dict: dict):
    """
    Recursively fetches dataset IDs and their metadata from the National Bureau of Statistics API.

    This function sends a POST request to the API to retrieve child nodes of the given `parent_id`.
    It parses the JSON response and populates the `id_dict` with `TreeNode` objects representing
    the dataset hierarchy. If a node is a parent, the function recursively fetches its children.

    Args:
        parent_id (str): The ID of the parent node to fetch child nodes for.
        id_dict (dict[str, TreeNode]): A dictionary to store the fetched nodes, where keys are node IDs
            and values are `TreeNode` objects.

    Raises:
        Exception: If the API request fails or returns a non-200 status code.

    Notes:
        - The function includes a delay (`time.sleep`) to avoid triggering anti-scraping measures.
        - The API URL is constructed dynamically based on the `parent_id`.

    Returns:
        None
    """
    url = f"https://data.stats.gov.cn/easyquery.htm?id={parent_id}&dbcode=hgyd&wdcode=zb&m=getTree"
    response = requests.post(url, headers=HEADERS)
    print(f"Fetching data from {url}...")
    if response.status_code != 200:
        raise Exception(f"Failed to fetch data from {url}, status code: {response.status_code}")
    data = json.loads(response.text)
    for item in data:
        id_dict[item["id"]] = TreeNode(
            dataset_id=item["id"],
            name=item["name"],
            parent_id=parent_id,
            is_parent=item["isParent"]
        )
        if item["isParent"]:
            grabID(item["id"], id_dict)

    # Ensure the script doesn't run too fast and trigger anti-scraping measures
    time.sleep(0)


def gen_full_name(dataset_id: str, id_dict: dict[str:TreeNode]) -> str:
    """Generates the full name of a dataset ID.

    Args:
        dataset_id (str): The ID of the dataset to retrieve the full name for.
        id_dict (dict[str, TreeNode]): A dictionary mapping dataset IDs to their corresponding TreeNode objects.

    Raises:
        ValueError: If the dataset ID does not exist in the provided dictionary.

    Returns:
        str: The full name of the dataset ID, constructed by traversing its parent hierarchy.
    """
    if dataset_id not in id_dict:
        raise ValueError(f"ID {self.dataset_id} 不存在于字典中。")

    full_name = []
    current_node = id_dict[dataset_id]

    while current_node:
        full_name.append(current_node.name)
        if current_node.parent_id in id_dict:
            current_node = id_dict[current_node.parent_id]
        else:
            break

    return " -> ".join(reversed(full_name))


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
            id_dict = {}
            leaf_node_dict = {}
            grabID(ROOT_ID, id_dict)

            # Add leaves to leaf_node_dict
            for node_id, node in id_dict.items():
                if not node.is_parent:
                    leaf_node_dict[node_id] = node

            cursor.execute('''
                CREATE TABLE datasets (
                    dataset_id TEXT PRIMARY KEY,
                    dataset_name TEXT,            -- Name of the dataset
                    dataset_full_name TEXT       -- Full name of the dataset, can be used for display
                );
            ''')
            for leaf_node_id, leaf_node in leaf_node_dict.items():
                # Check if the dataset already exists, if not, insert it
                cursor.execute("SELECT dataset_id FROM datasets WHERE dataset_id = ?", (leaf_node_id,))
                existing = cursor.fetchone()
                if existing is None:
                    cursor.execute("""
                                   INSERT INTO datasets (dataset_id,dataset_name,dataset_full_name)
                                   VALUES (?,?,?)
                               """, (leaf_node_id, leaf_node.name, gen_full_name(leaf_node_id, id_dict)))

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
        print(f"Database Error: {e.args[0]}")
    finally:
        print("Finished initializing database tables.")
        conn.close()


# =============================================================
#                         数据处理部分
# =============================================================


def get_full_name_by_id(dataset_id: str):
    # Check if the dataset_id exists in the datasets table, and then get its full name
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("""
                            SELECT dataset_id, dataset_name, dataset_full_name
                            FROM datasets
                            WHERE dataset_id = ?
                        """, (dataset_id,))
        dataset = cursor.fetchall()
    except sqlite3.Error as e:
        messagebox.showerror("数据库错误", f"查询数据时出错: {e}")
        return ""
    finally:
        conn.close()

    if len(dataset) == 0:
        messagebox.showerror("错误", f"数据集ID {dataset_id} 不存在。")
        return ""
    return dataset[0][2]


def get_name_by_id(dataset_id: str):
    # Check if the dataset_id exists in the datasets table, and then get its name
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("""
                            SELECT dataset_id, dataset_name, dataset_full_name
                            FROM datasets
                            WHERE dataset_id = ?
                        """, (dataset_id,))
        dataset = cursor.fetchall()
    except sqlite3.Error as e:
        messagebox.showerror("数据库错误", f"查询数据时出错: {e}")
        return ""
    finally:
        conn.close()

    if len(dataset) == 0:
        messagebox.showerror("错误", f"数据集ID {dataset_id} 不存在。")
        return ""
    return dataset[0][1]


# 爬取数据并存入数据库
def fetch_data():
    """
    Fetches data from the National Bureau of Statistics API and stores it in the SQLite database.

    This function constructs a URL based on user input for dataset ID and time scope, sends a POST request
    to the API, and processes the returned JSON data. The data is then inserted or updated in the `data_points`
    table of the SQLite database.

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
    """Retrieve data from the database and display it in the text area.

    This function queries the SQLite database for data points based on user-provided
    search criteria (dataset name or dataset ID). The results are displayed in the
    text area of the GUI. If no matching data is found, a message is displayed.

    **Global Variables**:
        - previous_results (list): Stores the results of the last query for potential use in visualization.

    Raises:
        sqlite3.Error: If an error occurs during database operations.

    Returns:
        None
    """
    global previous_results
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    search_name = search_name_input.get()
    search_id = search_id_input.get()
    try:
        # step 1: filter by dataset name if specified
        if search_name != "":
            cursor.execute("""
                SELECT dataset_id, time, name, value
                FROM data_points
                WHERE name LIKE ?
                ORDER BY time
            """, (f"%{search_name}%",))

        else:
            # 查询数据点表中的所有数据
            cursor.execute("""
                       SELECT dataset_id, time, name, value
                       FROM data_points
                       ORDER BY dataset_id
                   """, ())

        rows = cursor.fetchall()

        # step 2: filter by dataset_id if specified
        if search_id != "":
            filtered_rows = []
            for row in rows:
                if row[0] == search_id:
                    filtered_rows.append(row)
            rows = filtered_rows

        previous_results = rows

        text_area.config(state=tk.NORMAL)  # 临时启用来允许编辑
        # 清空文本区域并显示查询结果
        text_area.delete(1.0, tk.END)

        # step 3: if the rows is not empty, display the results
        if rows:
            for row in rows:
                text_area.insert(tk.END, f"数据集: {get_full_name_by_id(row[0])}, "
                                         f"组ID:{row[0]},时间: {row[1]}, 名称: {row[2]}, 值: {row[3]}\n")
        else:
            text_area.insert(tk.END, "未找到匹配的数据。\n")

        text_area.config(state=tk.DISABLED)  # 设为禁用状态后，无法编辑，但可以复制

    except sqlite3.Error as e:
        messagebox.showerror("Error", f"查询数据时出错: {e}")
    finally:
        conn.close()


# =============================================================
#                         数据可视化部分
# =============================================================
def visualize_data():
    """Visualizes data from the database.

    This function uses the `previous_results` global variable to retrieve data points
    queried from the database and generates a line plot using Matplotlib. The plot
    is displayed within the Tkinter GUI. If no data is available or multiple indicators
    are present, appropriate error messages are shown.

    Raises:
        ValueError: If multiple indicators are present in the data, as only single
            indicator visualization is supported.
    """
    global fig_canvas, viz_group  # 引用全局图表小部件

    rows = previous_results

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
    plt.title(f"数据集 {get_name_by_id(rows[0][0])} 的可视化")
    plt.legend()
    plt.grid(True)
    plt.gcf().autofmt_xdate(rotation=45)  # 自动调整x轴标签以防重叠
    plt.tight_layout()  # 调整布局

    # 设置字体支持中文
    mpl.rcParams['font.sans-serif'] = ['SimHei']  # 使用黑体
    mpl.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题

    # 在Tkinter中显示图表
    fig_canvas = FigureCanvasTkAgg(plt.gcf(), master=viz_group)
    fig_canvas.draw()
    # 使用 pack 将图表小部件放入 fig_canvas 框架中并使其填满
    fig_canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)


# =============================================================
#                         tkinter部分
# =============================================================

# tkinter 组件
(
    root,
    dataset_id_input,
    time_scope_input,
    search_id_input,
    search_name_input,
    text_area,
    fig_canvas
) = None, None, None, None, None, None, None


# GUI界面
def create_gui():
    """
    Creates the graphical user interface (GUI) for the application.

    This function initializes the main Tkinter window and adds various widgets
    for user interaction, including input fields, buttons, and a text area for
    displaying results. It also binds the buttons to their respective functions
    for data fetching, querying, and visualization.

    The layout is enhanced using ttk widgets, padding, and logical grouping for
    a more modern and user-friendly appearance.
    """
    global root, dataset_id_input, time_scope_input, search_id_input, search_name_input, text_area, fig_canvas, viz_group

    root = tk.Tk()
    root.title("国家统计局数据爬取与可视化工具")
    root.geometry("1400x550")

    paned_window = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
    paned_window.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    left_frame = ttk.Frame(paned_window, padding="10")
    paned_window.add(left_frame, weight=1)

    right_frame = ttk.Frame(paned_window, padding="10")
    paned_window.add(right_frame, weight=7)

    # --- 1. 数据爬取区域 ---
    fetch_group = ttk.LabelFrame(left_frame, text="数据爬取")
    fetch_group.pack(fill=tk.X, pady=(0, 10))

    dataset_id_frame = ttk.Frame(fetch_group)
    dataset_id_frame.pack(fill=tk.X, padx=5, pady=5)
    ttk.Label(dataset_id_frame, text="表的序号:", width=12).pack(side=tk.LEFT)
    dataset_id_input = ttk.Entry(dataset_id_frame)
    dataset_id_input.insert(0, "A01030H")
    dataset_id_input.pack(side=tk.LEFT, fill=tk.X, expand=True)

    time_scope_frame = ttk.Frame(fetch_group)
    time_scope_frame.pack(fill=tk.X, padx=5, pady=(0, 5))
    ttk.Label(time_scope_frame, text="时间范围:", width=12).pack(side=tk.LEFT)
    time_scope_input = ttk.Entry(time_scope_frame)
    time_scope_input.insert(0, "LAST13")
    time_scope_input.pack(side=tk.LEFT, fill=tk.X, expand=True)

    # --- ** 新增的说明标签 ** ---
    info_text = "格式示例: 月: 202401,202405 | 季: 2024A,2024B | 年: 2023,2024 | 其他: last13, 2023-"
    info_label = ttk.Label(fetch_group, text=info_text, foreground="gray50", justify=tk.LEFT)
    info_label.pack(fill=tk.X, padx=5, pady=(0, 10))
    # --- ** 新增内容结束 ** ---

    ttk.Button(fetch_group, text="爬取数据", command=fetch_data).pack(fill=tk.X, padx=5, pady=5)

    # --- 2. 数据查询区域 ---
    query_group = ttk.LabelFrame(left_frame, text="本地数据查询")
    query_group.pack(fill=tk.X, pady=10)

    search_id_frame = ttk.Frame(query_group)
    search_id_frame.pack(fill=tk.X, padx=5, pady=5)
    ttk.Label(search_id_frame, text="查询 (表序号):", width=12).pack(side=tk.LEFT)
    search_id_input = ttk.Entry(search_id_frame)
    search_id_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
    ttk.Button(search_id_frame, text="查询", command=retrieve_data).pack(side=tk.LEFT)

    search_name_frame = ttk.Frame(query_group)
    search_name_frame.pack(fill=tk.X, padx=5, pady=5)
    ttk.Label(search_name_frame, text="查询 (名称):", width=12).pack(side=tk.LEFT)
    search_name_input = ttk.Entry(search_name_frame)
    search_name_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
    ttk.Button(search_name_frame, text="查询", command=retrieve_data).pack(side=tk.LEFT)

    # --- 3. 结果输出区域 ---
    output_group = ttk.LabelFrame(left_frame, text="结果输出")
    output_group.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

    text_container = ttk.Frame(output_group)
    text_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    text_area = tk.Text(text_container, height=10, width=50, wrap=tk.WORD, relief=tk.FLAT)
    text_area.config(state=tk.DISABLED)

    scrollbar = ttk.Scrollbar(text_container, orient=tk.VERTICAL, command=text_area.yview)
    text_area.configure(yscrollcommand=scrollbar.set)

    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    ttk.Button(left_frame, text="可视化选中数据", command=visualize_data).pack(fill=tk.X, pady=5)

    # --- 5. 可视化图表区域 ---
    viz_group = ttk.LabelFrame(right_frame, text="数据可视化图表")
    viz_group.pack(fill=tk.BOTH, expand=True)

    fig_canvas = tk.Frame(viz_group)
    fig_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    root.mainloop()


if __name__ == "__main__":
    init_tables()
    create_gui()
