import grequests
import requests
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import time
import os
import logging
import random
import math
from io import BytesIO
from typing import List, Tuple
from dataclasses import dataclass
import progressbar

_GOOGLE_MAP_URL = 'http://www.google.cn/maps/vt?lyrs=s&x={}&y={}&z={}'
# _GOOGLE_MAP_URL = 'http://www.google.com/maps/vt?lyrs=s&x={}&y={}&z={}'

_USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.101 Safari/537.36',
    'Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US) AppleWebKit/532.5 (KHTML, like Gecko) Chrome/4.0.249.0 Safari/532.5',
    'Mozilla/5.0 (Windows; U; Windows NT 5.2; en-US) AppleWebKit/532.9 (KHTML, like Gecko) Chrome/5.0.310.0 Safari/532.9',
    'Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US) AppleWebKit/534.7 (KHTML, like Gecko) Chrome/7.0.514.0 Safari/534.7',
    'Mozilla/5.0 (Windows; U; Windows NT 6.0; en-US) AppleWebKit/534.14 (KHTML, like Gecko) Chrome/9.0.601.0 Safari/534.14',
    'Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US) AppleWebKit/534.14 (KHTML, like Gecko) Chrome/10.0.601.0 Safari/534.14',
    'Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US) AppleWebKit/534.20 (KHTML, like Gecko) Chrome/11.0.672.2 Safari/534.20", "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/534.27 (KHTML, like Gecko) Chrome/12.0.712.0 Safari/534.27',
    'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/535.1 (KHTML, like Gecko) Chrome/13.0.782.24 Safari/535.1',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 Safari/537.36']

TILE_SIZE = 256


def _image_scale(zoom):
    """
    根据缩放计算瓦片行（列）数
    :param zoom: 瓦片等级
    :return: 每行或每列的瓦片数
    """
    return 1 << zoom


def _project(lat, lng):
    """
    Web Mercator 投影
    :param lat: 纬度
    :param lng: 经度
    :return: 投影坐标
    """
    sin_y = math.sin(lat * math.pi / 180)
    sin_y = min(max(sin_y, -0.9999), 0.9999)  # Truncating to 0.9999 effectively limits latitude to 89.1897
    return 0.5 + lng / 360, 0.5 - math.log((1 + sin_y) / (1 - sin_y)) / (4 * math.pi)


def _inverse(w_x, w_y):
    """
    反投影
    :param w_x: 世界坐标x
    :param w_y: 世界坐标y
    :return: 经纬度
    """
    lat = math.atan(math.sinh(math.pi * (1 - 2 * w_y))) / math.pi * 180
    lng = (w_x - 0.5) * 360
    return lat, lng


def world_xy(lat, lng):
    """
    经纬度转“世界坐标”
    :param lat: 纬度
    :param lng: 经度
    :return: 世界坐标
    """
    p_x, p_y = _project(lat, lng)
    return TILE_SIZE * p_x, TILE_SIZE * p_y


def pixel_xy(lat, lng, zoom):
    """
    经纬度转“像素坐标”
    :param lat: 纬度
    :param lng: 经度
    :param zoom: 瓦片等级
    :return: 像素坐标
    """
    w_x, w_y = world_xy(lat, lng)
    scale = _image_scale(zoom)
    return math.floor(w_x * scale), math.floor(w_y * scale)


def tile_xy(lat: float, lng: float, zoom: int) -> Tuple[int, int]:
    """
    经纬度转“瓦片坐标”
    :param lat: 纬度
    :param lng: 经度
    :param zoom: 瓦片等级
    :return: 瓦片坐标
    """
    p_x, p_y = pixel_xy(lat, lng, zoom)
    return math.floor(p_x / TILE_SIZE), math.floor(p_y / TILE_SIZE)


def tile_extents(t_x: int, t_y: int, zoom: int) -> Tuple[float, float, float, float]:
    """
    获取指定瓦片四至经纬度
    :param t_x: x
    :param t_y: y
    :param zoom: z
    :return: 北南西东，四至经纬度
    """
    scale = _image_scale(zoom)
    unit = 1 / scale
    x_min = unit * t_x
    x_max = unit * (t_x + 1)
    y_min = unit * t_y
    y_max = unit * (t_y + 1)
    lat_top, lng_left = _inverse(x_min, y_min)
    lat_bottom, lng_right = _inverse(x_max, y_max)
    return lat_top, lat_bottom, lng_left, lng_right


def get_image_from_tiles(extents: (float, float, float, float), zoom, tiles_root):
    """
    将指定范围的瓦片拼接成图片
    :param extents: (top lat, bottom lat, left lng, right lng)
    :param zoom: google zoom level
    :param tiles_root: 瓦片根目录
    :return: Image
    """
    lat0, lat1, lng0, lng1 = extents
    x_s, y_s = tile_xy(lat0, lng0, zoom)
    x_e, y_e = tile_xy(lat1, lng1, zoom)
    return merge_tiles(x_s, x_e, y_s, y_e, zoom, tiles_root)


def merge_tiles(x_s: int, x_e: int, y_s: int, y_e: int, zoom: int, tiles_root: str) -> Image:
    """
    拼接影像
    :param x_s: 起始x瓦片坐标
    :param x_e: 截至x瓦片坐标
    :param y_s: 起始y瓦片坐标
    :param y_e: 截至y瓦片坐标
    :param zoom: 瓦片等级
    :param tiles_root: 瓦片存放根目录
    :return: PIL.Image
    """
    width = TILE_SIZE * (x_e - x_s)
    height = TILE_SIZE * (y_e - y_s)
    full_image = Image.new('RGB', (width, height))
    tile_path_base = tiles_root + '/{}/{}/{}.jpg'
    for x in range(x_s, x_e + 1):
        for y in range(y_s, y_e + 1):
            tile_path = tile_path_base.format(zoom, x, y)
            if os.path.exists(tile_path):
                tile_image = Image.open(tile_path)
                full_image.paste(tile_image, ((x - x_s) * TILE_SIZE, (y - y_s) * TILE_SIZE))
    return full_image





@dataclass
class Task:
    zoom: int  # 任务层级
    size: int  # 任务大小
    # tiles: [(int, int)]  # 任务xy，生成器或列表
    x_range: (int, int)  # 任务x范围
    y_range: (int, int)  # 任务y范围
    re_list: List[Tuple[int, int]]
    name: str = 'DEFAULT'  # 任务名称

    @staticmethod
    def from_father_tile(task_zoom, tile: (int, int, int), name=None):
        x, y, z = tile

        if task_zoom < z:
            raise ValueError('task zoom should less than z')

        if name:
            task_name = name
        else:
            task_name = 'SUB_TILES FROM {}-{}-{}'.format(z, x, y)

        task_scale = _image_scale(task_zoom)
        father_scale = _image_scale(z)
        n = int(task_scale / father_scale)

        # x_range = range(x * n, (x + 1) * n)
        # y_range = range(y * n, (y + 1) * n)
        # task_size = len(x_range) * len(y_range)
        # task_tiles = ((xx, yy) for xx in x_range for yy in y_range)

        x_range = (x * n, (x + 1) * n)
        y_range = (y * n, (y + 1) * n)
        task_size = ((x + 1) * n - x * n) * ((y + 1) * n - y * n)

        return Task(task_zoom, task_size, x_range, y_range, [], task_name)

    @staticmethod
    def from_rectangle(task_zoom, extents: (float, float, float, float), name=None):
        if name:
            task_name = name
        else:
            task_name = 'LEVEL {} TILES FROM ({}, {}, {}, {})'.format(task_zoom, *extents)
        lat0, lat1, lng0, lng1 = extents
        x_s, y_s = tile_xy(lat0, lng0, task_zoom)
        x_e, y_e = tile_xy(lat1, lng1, task_zoom)
        # x_range = range(x_s, x_e + 1)
        # y_range = range(y_s, y_e + 1)
        # task_size = len(x_range) * len(y_range)
        # task_tiles = ((xx, yy) for xx in x_range for yy in y_range)
        x_range = (x_s, x_e + 1)
        y_range = (y_s, y_e + 1)
        task_size = (x_e - x_s + 1) * (y_e - y_s + 1)
        return Task(task_zoom, task_size, x_range, y_range, [], task_name)

    @staticmethod
    def from_point(task_zoom, latlng, buffer, name=None):
        lat, lng = latlng
        extents = lat + buffer, lat - buffer, lng - buffer, lng + buffer
        return Task.from_rectangle(task_zoom, extents, name)


class ProgressbarCounter:
    def __init__(self, max_value):
        self._progress = 0
        self._max = max_value

    def update(self):
        self._progress = self._progress + 1
        print("\r" + "Task tiles downloading: {}/{}, {}%".format(self._progress,
                                                                 self._max,
                                                                 round((self._progress * 100 / self._max)), 2),
              end='', flush=True)


class Downloader:
    def __init__(self, store_path: str, task: Task = None, merge=False):
        self._task = task
        self._root_path = store_path

    def run(self, coroutine_num=30):
        task_start_time = time.time()
        # 下载初始化打印
        # print('Task name: {}'.format(self._task.name, ))
        # print('Task tiles number: {}'.format(self._task.size))
        # 进度条
        p = ProgressbarCounter(self._task.size)
        # 下载
        async_down_tiles(self._task, self._root_path, p, coroutine_num)
        # 结束打印
        task_end_time = time.time()
        # print('\n' + 'Task use time: {}s'.format(task_end_time - task_start_time))
        # print('--------------------------------------')
        # 如果有下载失败的瓦片，重新下载
        if self._task.re_list and len(self._task.re_list) > 0:
            # retry task
            self._task.name = "RETRY:" + self._task.name
            retry_downloader = Downloader(self._root_path, self._task)
            retry_downloader.run()


def async_down_tiles(task: Task, store_path, progress_bar, req_limit=30):
    # add retry
    s = requests.Session()
    retries = Retry(total=5, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504], raise_on_redirect=True,
                    raise_on_status=True)
    s.mount('http://', HTTPAdapter(max_retries=retries))
    s.mount('https://', HTTPAdapter(max_retries=retries))

    z = task.zoom
    if task.re_list and len(task.re_list) > 0:
        # if retry
        task_urls = (grequests.get(_GOOGLE_MAP_URL.format(x, y, z),
                                   session=s,
                                   hooks={'response': save_tile_hook(zoom=z, x=x, y=y, path=store_path,
                                                                     p=progress_bar, re_list=task.re_list)},
                                   headers={'user-agent': random.choice(_USER_AGENTS)})
                     for x, y in task.re_list)
    else:
        task_urls = (grequests.get(_GOOGLE_MAP_URL.format(x, y, z),
                                   session=s,
                                   hooks={'response': save_tile_hook(zoom=z, x=x, y=y, path=store_path,
                                                                     p=progress_bar, re_list=task.re_list)},
                                   headers={'user-agent': random.choice(_USER_AGENTS)})
                     for x in range(*task.x_range)
                     for y in range(*task.y_range))

    grequests.map(task_urls, size=req_limit)


def save_tile_hook(**kwargs):
    def save_tile(response, *request_args, **request_kwargs):
        zoom, x, y = kwargs['zoom'], kwargs['x'], kwargs['y']
        path = kwargs['path']
        p = kwargs['p']
        re_list = kwargs['re_list']
        if response.status_code not in (400, 404, 410):
            try:
                image = Image.open(BytesIO(response.content))
                z_path = path + '/{}'.format(zoom)
                if not os.path.exists(z_path):
                    os.mkdir(z_path)
                x_path = z_path + '/{}'.format(x)
                if not os.path.exists(x_path):
                    os.mkdir(x_path)
                image_path = x_path + '/{}.jpg'.format(y)
                image.save(image_path)
            except Exception as e:
                if re_list:
                    re_list.append((x, y))
                msg = 'tile( x:{}, y:{}, z:{}) download fail, it will retry after task'
                logging.warning(msg.format(x, y, zoom))
                logging.exception(e)
        p.update()

    return save_tile


def read_tasks_file(file_path):
    with open(file_path, 'r') as f:
        return tuple((tuple(map(int, line.strip().split(','))) for line in f.readlines()))


def download_image(image_path, task: Task, save_tile=True, tile_path=None):
    # TODO 完成整图下载
    # 下载
    # 删除切片文件夹
    if not save_tile:
        pass
    pass


if __name__ == '__main__':
    # 洛杉矶 LT_xy：34.2757819620,-118.6073152800 RB_xy：33.4426799945,-116.8645182563
    # 常州：
    # LT_xy = tile_xy(31.8822313752,119.8790377320, tasks_zoom)
    # RB_xy = tile_xy(31.7026003847,120.0009849033, tasks_zoom)
    # 拉斯维加斯 LT：36.3058948028,-115.3299402473  RB：36.0329247545,-115.0138758082
    # 巴黎 LT：48.9033085728,2.2891089475 RB:48.8169904853,2.4196910441
    # 旧金山 LT_xy：37.8027936169,-122.5235894369 RB：37.7117271669,-122.3511555838
    tasks_zoom = 20
    LT_xy = tile_xy(37.8027936169, -122.5235894369, tasks_zoom)
    RB_xy = tile_xy(37.7117271669, -122.3511555838, tasks_zoom)
    tiles_path = r"H:\Data\GoogleMap\SanFrancisco"
    nPatchs = (RB_xy[0] - LT_xy[0] + 1) * (RB_xy[1] - LT_xy[1] + 1)
    nPatch = 0
    dataCheck = True
    print(LT_xy, RB_xy, nPatchs)
    with progressbar.ProgressBar(min_value=0, max_value=nPatchs) as bar:
        for coord_x in range(LT_xy[0], RB_xy[0] + 1):
            for coord_y in range(LT_xy[1], RB_xy[1] + 1):
                if dataCheck:
                    if os.path.exists(os.path.join(tiles_path, '{zoom}/{x}/{y}.jpg'.format(zoom=tasks_zoom, x=coord_x, y=coord_y))):
                        print('\r FILE EXISTS', os.path.join(tiles_path, '{zoom}/{x}/{y}.jpg'.format(zoom=tasks_zoom, x=coord_x, y=coord_y)), end='',
                              flush=True)
                        nPatch += 1
                        bar.update(nPatch)
                        continue
                    else:
                        dataCheck = False
                test_task = Task.from_father_tile(tasks_zoom, (coord_x, coord_y, tasks_zoom))
                downloader = Downloader(tiles_path, test_task)
                downloader.run()
                nPatch += 1
                bar.update(nPatch)

# start_time = time.time()
# tasks_xyz = read_tasks_file('./task_xyz_13_4_rest.txt')
# # tasks_xyz = [(222, 103, 8)]
# tasks_zoom = 19
# tiles_path = 'E:\\'
# t = 0
# T = len(tasks_xyz)
# for xyz in tasks_xyz:
#     t = t + 1
#     print('Current task: {}/{}'.format(t, T))
#     test_task = Task.from_father_tile(tasks_zoom, xyz)
#     downloader = Downloader(tiles_path, test_task)
#     downloader.run()
# end_time = time.time()
# print('Total use time: {}s'.format(end_time-start_time))
#
# # narita = (35.764701843299996, 140.386001587)
# # lat0, lat1, lng0, lng1 = narita[0]+0.04, narita[0]-0.04, narita[1]-0.04, narita[1]+0.04
# # image = get_image_from_tiles((lat0, lat1, lng0, lng1), 15, 'D:/data/japan/gmap_tiles')
# # image.save('D:/data/narita_15.jpg')
