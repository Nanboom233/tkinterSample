import json
import time

import requests

ROOT_ID = "zb"
id_dict = {}
leaf_node_dict = {}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Mobile Safari/537.36",
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Referer': 'https://data.stats.gov.cn/easyquery.htm',  # 伪造来源页面
    'X-Requested-With': 'XMLHttpRequest'  # 表明这是一个AJAX请求，很多网站会检查这个
}


class TreeNode:
    def __init__(self, id: str, name: str, parent_id: str, is_parent: bool):
        self.id = id
        self.name = name
        self.parent_id = parent_id
        self.is_parent = is_parent


def grabID(parent_id: str):
    global id_dict
    url = f"https://data.stats.gov.cn/easyquery.htm?id={parent_id}&dbcode=hgyd&wdcode=zb&m=getTree"
    response = requests.post(url, headers=HEADERS)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch data from {url}, status code: {response.status_code}")
    data = json.loads(response.text)
    for item in data:
        id_dict[item["id"]] = TreeNode(
            id=item["id"],
            name=item["name"],
            parent_id=parent_id,
            is_parent=item["isParent"]
        )
        if item["isParent"]:
            grabID(item["id"])
    time.sleep(0.05)

def init_id_dict() -> tuple:
    grabID(ROOT_ID)

    # Add leaves to leaves_list
    for node_id, node in id_dict.items():
        if not node.is_parent:
            leaf_node_dict[node_id] = node

    return id_dict, leaf_node_dict


def get_full_name(id: str, id_dict: dict) -> str:
    """获取ID的全名"""
    if id not in id_dict:
        raise ValueError(f"ID {id} 不存在于字典中。")

    full_name = []
    current_node = id_dict[id]

    while current_node:
        full_name.append(current_node.name)
        if current_node.parent_id in id_dict:
            current_node = id_dict[current_node.parent_id]
        else:
            break

    return " -> ".join(reversed(full_name))
