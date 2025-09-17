# main.py 主逻辑：包括字段拼接、模拟请求
import re
import json
import time
import random
import logging
import hashlib
import requests
import urllib.parse
from push import push
from config import data, headers, cookies, READ_NUM, PUSH_METHOD, book, chapter

# 配置日志格式
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)-8s - %(message)s')

# 加密盐及其它默认值
KEY = "3c5c8717f3daf09iop3423zafeqoi"
COOKIE_DATA = {"rq": "%2Fweb%2Fbook%2Fread"}
READ_URL = "https://weread.qq.com/web/book/read"
RENEW_URL = "https://weread.qq.com/web/login/renewal"
FIX_SYNCKEY_URL = "https://weread.qq.com/web/book/chapterInfos"


def encode_data(data):
    """数据编码"""
    return '&'.join(f"{k}={urllib.parse.quote(str(data[k]), safe='')}" for k in sorted(data.keys()))


def cal_hash(input_string):
    """计算哈希值"""
    _7032f5 = 0x15051505
    _cc1055 = _7032f5
    length = len(input_string)
    _19094e = length - 1

    while _19094e > 0:
        _7032f5 = 0x7fffffff & (_7032f5 ^ ord(input_string[_19094e]) << (length - _19094e) % 30)
        _cc1055 = 0x7fffffff & (_cc1055 ^ ord(input_string[_19094e - 1]) << _19094e % 30)
        _19094e -= 2

    return hex(_7032f5 + _cc1055)[2:].lower()

def get_wr_skey():
    """刷新cookie密钥"""
    response = requests.post(RENEW_URL, headers=headers, cookies=cookies,
                             data=json.dumps(COOKIE_DATA, separators=(',', ':')))
    for cookie in response.headers.get('Set-Cookie', '').split(';'):
        if "wr_skey" in cookie:
            return cookie.split('=')[-1][:8]
    return None

def fix_no_synckey():
    requests.post(FIX_SYNCKEY_URL, headers=headers, cookies=cookies,
                             data=json.dumps({"bookIds":["3300060341"]}, separators=(',', ':')))

def refresh_cookie():
    logging.info(f"🍪 刷新cookie")
    new_skey = get_wr_skey()
    if new_skey:
        cookies['wr_skey'] = new_skey
        logging.info(f"✅ 密钥刷新成功，新密钥：{new_skey}")
        logging.info(f"🔄 重新本次阅读。")
    else:
        ERROR_CODE = "❌ 无法获取新密钥或者WXREAD_CURL_BASH配置有误，终止运行。"
        logging.error(ERROR_CODE)
        push(ERROR_CODE, PUSH_METHOD)
        raise Exception(ERROR_CODE)

refresh_cookie()
index = 1
MAX_FAIL_RETRY = 3 # 失败重试次数
lastTime = int(time.time()) - 30
logging.info(f"⏱️ 一共需要阅读 {READ_NUM} 次...")


while index <= READ_NUM:
    data.pop('s')
    data['b'] = random.choice(book)
    data['c'] = random.choice(chapter)
    thisTime = int(time.time())
    data['ct'] = thisTime
    data['rt'] = thisTime - lastTime
    data['ts'] = int(thisTime * 1000) + random.randint(0, 1000)
    data['rn'] = random.randint(0, 1000)
    data['sg'] = hashlib.sha256(f"{data['ts']}{data['rn']}{KEY}".encode()).hexdigest()
    data['s'] = cal_hash(encode_data(data))

    logging.info(f"⏱️ 尝试第 {index} 次阅读...")
    logging.info(f"📕 data: {data}")
    response = requests.post(READ_URL, headers=headers, cookies=cookies, data=json.dumps(data, separators=(',', ':')))
    resData = response.json()
    logging.info(f"📕 response: {resData}")

    # ---- 新的失败重试逻辑开始 ----
    if 'succ' not in resData:
        logging.warning("❌ 未返回 succ，进入重试阶段…")
        retry = 0
        while retry < MAX_FAIL_RETRY:
            retry += 1
            logging.info(f"🔁 重试 #{retry}：refresh_cookie -> POST")
            try:
                refresh_cookie()
            except Exception:
                # refresh_cookie 内部已 push + 打日志；这里直接判定失败终止脚本
                logging.error("❌ refresh_cookie 抛异常，终止脚本。")
                raise

            # 重发请求（无需改动 data 的签名时间戳也可以继续用；如需更严谨可重算一次 ts/rn/sg/s）
            response = requests.post(READ_URL, headers=headers, cookies=cookies,
                                     data=json.dumps(data, separators=(',', ':')))
            try:
                resData = response.json()
            except Exception:
                resData = {}

            logging.info(f"📕 retry response: {resData}")

            # 重试退出条件
            if 'succ' in resData:
                logging.info("✅ 重试成功，出现 succ，退出重试阶段。")
                break

            # 仍未成功：等待 2 秒再下一次重试
            logging.info(f"⏳ 2s 后继续重试…")
            time.sleep(2)

        # 超过 MAX_FAIL_RETRY 次仍无 succ => 计为失败并终止脚本
        if 'succ' not in resData:
            err = f"❌ 本次阅读在重试 {MAX_FAIL_RETRY} 次后仍未返回 succ，计为失败并终止。"
            logging.error(err)
            push(err, PUSH_METHOD)
            break
    # ---- 新的失败重试逻辑结束 ----

    # 有 succ 的正常分支
    if 'synckey' in resData:
        lastTime = thisTime
        index += 1
        logging.info(f"✅ 阅读成功，阅读进度：{(index - 1) * 0.5} 分钟")
        time.sleep(30)
    else:
        logging.warning("❌ 返回 succ 但无 synckey，尝试修复…")
        fix_no_synckey()

logging.info("🎉 阅读脚本已完成！")

if PUSH_METHOD not in (None, ''):
    logging.info("⏱️ 开始推送...")
    push(f"🎉 微信读书自动阅读完成！\n⏱️ 阅读时长：{(index - 1) * 0.5}分钟。", PUSH_METHOD)
