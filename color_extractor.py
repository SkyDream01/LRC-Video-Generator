# LRC Video Generator/color_extractor.py
import colorsys
import numpy as np
from PIL import Image
from sklearn.cluster import KMeans

def hex_to_rgb(hex_color):
    """将HEX颜色字符串转换为(R, G, B)元组。"""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_hex(rgb_color):
    """将(R, G, B)元组转换为HEX颜色字符串。"""
    return '#{:02x}{:02x}{:02x}'.format(int(rgb_color[0]), int(rgb_color[1]), int(rgb_color[2]))

def get_color_luminance(rgb_color):
    """计算颜色的相对亮度 (0-1)。"""
    r, g, b = [x / 255.0 for x in rgb_color]
    return 0.299 * r + 0.587 * g + 0.114 * b

def get_saturation(rgb_color):
    """计算颜色的饱和度 (0-1)。"""
    r, g, b = [x / 255.0 for x in rgb_color]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return s
    
def get_contrast_ratio(rgb1, rgb2):
    """计算两种颜色之间的对比度。"""
    lum1 = get_color_luminance(rgb1)
    lum2 = get_color_luminance(rgb2)
    return (max(lum1, lum2) + 0.05) / (min(lum1, lum2) + 0.05)

def is_good_candidate(color):
    """判断一个颜色是否是好的主色候选者（不过于亮/暗/灰）。"""
    luminance = get_color_luminance(color)
    saturation = get_saturation(color)
    
    # 规则：亮度在20%到80%之间，饱和度大于25%
    return 0.2 < luminance < 0.8 and saturation > 0.25

def extract_and_process_colors(image_path, num_colors=10):
    """
    从图像中提取主色调，并返回基于重要性和对比度的一组颜色。

    :param image_path: 图像文件路径。
    :param num_colors: 要提取的颜色簇数量。
    :return: 一个元组(主颜色HEX, 次颜色HEX, 描边颜色HEX)。
    """
    try:
        # 1. 加载并预处理图像
        img = Image.open(image_path).convert('RGB')
        img.thumbnail((150, 150))
        pixels = np.array(img.getdata())

        # 2. 使用KMeans进行颜色量化
        kmeans = KMeans(n_clusters=num_colors, random_state=42, n_init=10)
        kmeans.fit(pixels)
        
        # 获取颜色及其在图像中的占比
        unique_labels, counts = np.unique(kmeans.labels_, return_counts=True)
        cluster_centers = kmeans.cluster_centers_
        
        # 3. 筛选出好的候选颜色
        candidates = []
        for i, center in enumerate(cluster_centers):
            if is_good_candidate(center):
                # 存储颜色、占比
                candidates.append({'color': center, 'percentage': counts[i] / len(pixels)})

        # 4. 选择主颜色
        if candidates:
            # 从候选者中选出占比最高的作为主色
            primary_candidate = max(candidates, key=lambda x: x['percentage'])
            primary_rgb = primary_candidate['color']
        else:
            # 如果没有符合条件的候选者，退回到选择最饱和的颜色作为备用方案
            primary_rgb = max(cluster_centers, key=lambda c: get_saturation(c))

        # 5. 选择次要颜色：与主色对比度最高
        secondary_rgb = None
        max_contrast_secondary = 0
        for center in cluster_centers:
            if np.array_equal(center, primary_rgb): continue
            contrast = get_contrast_ratio(primary_rgb, center)
            if contrast > max_contrast_secondary:
                max_contrast_secondary = contrast
                secondary_rgb = center
        if secondary_rgb is None:
            secondary_rgb = [0,0,0] if get_color_luminance(primary_rgb) > 0.5 else [255,255,255]

        # 6. 选择描边颜色：与主色对比度最高（且非次要色）
        outline_rgb = None
        max_contrast_outline = 0
        for center in cluster_centers:
            if np.array_equal(center, primary_rgb) or np.array_equal(center, secondary_rgb): continue
            contrast = get_contrast_ratio(primary_rgb, center)
            if contrast > max_contrast_outline:
                max_contrast_outline = contrast
                outline_rgb = center
        if outline_rgb is None:
             outline_rgb = [0,0,0] if get_color_luminance(primary_rgb) > 0.5 else [255,255,255]


        return (rgb_to_hex(primary_rgb), rgb_to_hex(secondary_rgb), rgb_to_hex(outline_rgb))

    except Exception as e:
        print(f"提取颜色时发生错误: {e}")
        return ("#FFFFFF", "#DDDDDD", "#000000")