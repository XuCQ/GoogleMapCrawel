# -*- coding:utf-8 -*-
# author:Changing Xu
# file:Google_Map-gmap_image_joint
# datetime:2019/11/29 16:54
# software: PyCharm
import os
from PIL import Image
from io import BytesIO
import math

TILE_SIZE = 256


def traversalDir_FirstDir(path, findTag='dir', fileFormat=None):
    # 定义一个列表，用来存储结果
    list = []
    # 判断路径是否存在
    if os.path.exists(path):
        # 获取该目录下的所有文件或文件夹目录
        files = os.listdir(path)
        for file in files:
            # 得到该文件下所有目录的路径
            m = os.path.join(path, file)
            # 判断该路径下是否是文件夹
            if findTag == 'dir':
                if os.path.isdir(m):
                    h = os.path.basename(m)
                    list.append(h)
            else:
                if os.path.isfile(m):
                    h = os.path.basename(m)
                    targetName, targetFormat = h.split('.')
                    if fileFormat is not None:
                        if targetFormat == fileFormat:
                            list.append(h)
                    else:
                        list.append(h)
    return list


def joint_image(imagePath, jointSize, outputPath):
    """
    拼接影像（按照jointSize将n^2个小的image拼接为一个大的image）
    :param imagePath: image路径
    :param jointSize: 拼接尺寸
    :param outputPath: 输出地址
    :return: null
    """
    x_list = [int(info) for info in traversalDir_FirstDir(imagePath)]
    LR_x = min(x_list)
    RT_x = max(x_list)
    y_list = [int(info.replace('.jpg', '')) for info in traversalDir_FirstDir(os.path.join(imagePath, str(LR_x)), findTag='file', fileFormat='jpg')]
    LR_y = min(y_list)
    RT_y = max(y_list)
    x_gap = (RT_x - LR_x) % jointSize
    y_gap = (RT_y - LR_y) % jointSize
    tile_path_base = os.path.join(imagePath, '{}\{}.jpg')
    if not os.path.exists(outputPath):
        os.mkdir(outputPath)
    for coord_x in range(LR_x + math.floor(x_gap / 2), RT_x - math.ceil(x_gap / 2), jointSize):
        for coord_y in range(LR_y + math.floor(y_gap / 2), RT_y - math.ceil(y_gap / 2), jointSize):
            full_image = Image.new('RGB', (TILE_SIZE * jointSize, TILE_SIZE * jointSize))
            print('\rImage id: {x}/{x_max} {y}/{y_max}'.format(x=coord_x, x_max=RT_x, y=coord_y, y_max=RT_y), end='', flush=True)
            for coord_add in [(i, j) for i in range(jointSize) for j in range(jointSize)]:
                tile_path = tile_path_base.format(coord_x + coord_add[0], coord_y + coord_add[1])
                if os.path.exists(tile_path):
                    tile_image = Image.open(tile_path)
                    full_image.paste(tile_image, (coord_add[0] * TILE_SIZE, coord_add[1] * TILE_SIZE,
                                                  coord_add[0] * TILE_SIZE + TILE_SIZE, coord_add[1] * TILE_SIZE + TILE_SIZE))  # （left, upper, right, lower）
                else:
                    print('file not exist!\t', tile_path)
                    break
            try:
                savePath = os.path.join(outputPath, '{LR_x}_{LR_y}_{size}.jpg'.format(LR_x=coord_x, LR_y=coord_y, size=jointSize))
                full_image.save(savePath)
            except Exception as e:
                print(e)
                print('save ERROR\t', '{LR_x}_{LR_y}_{size}.jpg'.format(LR_x=coord_x, LR_y=coord_y, size=jointSize))


if __name__ == '__main__':
    joint_image(r'H:\Data\GoogleMap\SanFrancisco\20', 10, r'H:\Data\GoogleMap\SanFrancisco\20_joint_image_10')
    # a = traversalDir_FirstDir(r'H:\Data\GoogleMap\SanFrancisco\20', findTag='file')
    # print(a)
