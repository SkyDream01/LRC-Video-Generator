# LRC Video Generator/color_extractor.py
import colorsys
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
    """计算颜色的相对亮度 (WCAG标准)。"""
    r, g, b = [x / 255.0 for x in rgb_color]
    r = ((r <= 0.03928) and r / 12.92) or ((r + 0.055) / 1.055) ** 2.4
    g = ((g <= 0.03928) and g / 12.92) or ((g + 0.055) / 1.055) ** 2.4
    b = ((b <= 0.03928) and b / 12.92) or ((b + 0.055) / 1.055) ** 2.4
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def get_contrast_ratio(rgb1, rgb2):
    """计算两种颜色之间的对比度。"""
    lum1 = get_color_luminance(rgb1)
    lum2 = get_color_luminance(rgb2)
    return (max(lum1, lum2) + 0.05) / (min(lum1, lum2) + 0.05)

def extract_and_process_colors(image_path, num_colors=8, min_contrast=3.0):
    """
    从图像中提取主色调，并返回对比度最佳的一组颜色（主、次、描边）。

    :param image_path: 图像文件路径。
    :param num_colors: 要提取的颜色簇数量。
    :param min_contrast: 要求的最小对比度。
    :return: 一个元组(主颜色HEX, 次颜色HEX, 描边颜色HEX)。如果找不到，则返回默认值。
    """
    try:
        # 1. 加载并预处理图像
        img = Image.open(image_path).convert('RGB')
        img.thumbnail((150, 150))
        pixels = list(img.getdata())

        # 2. 使用KMeans进行颜色量化
        kmeans = KMeans(n_clusters=num_colors, random_state=42, n_init=10)
        kmeans.fit(pixels)
        dominant_colors_rgb = [list(center) for center in kmeans.cluster_centers_]

        # 3. 寻找主、次颜色的最佳对（对比度最高）
        primary_rgb, secondary_rgb = None, None
        max_contrast = 0
        for i in range(len(dominant_colors_rgb)):
            for j in range(i + 1, len(dominant_colors_rgb)):
                color1_rgb = dominant_colors_rgb[i]
                color2_rgb = dominant_colors_rgb[j]
                contrast = get_contrast_ratio(color1_rgb, color2_rgb)
                if contrast > max_contrast:
                    max_contrast = contrast
                    primary_rgb, secondary_rgb = color1_rgb, color2_rgb

        if not primary_rgb:
            return ("#FFFFFF", "#DDDDDD", "#000000") # 备用方案

        # 确保主颜色更亮
        if get_color_luminance(primary_rgb) < get_color_luminance(secondary_rgb):
            primary_rgb, secondary_rgb = secondary_rgb, primary_rgb
            
        # 4. 寻找描边颜色：与主颜色对比度最高的颜色
        outline_rgb = None
        max_outline_contrast = 0
        for color in dominant_colors_rgb:
            # 不选择主、次颜色作为描边色
            if color == primary_rgb or color == secondary_rgb:
                continue
            contrast = get_contrast_ratio(primary_rgb, color)
            if contrast > max_outline_contrast:
                max_outline_contrast = contrast
                outline_rgb = color

        # 如果找不到合适的描边色（例如颜色太少），则在黑白之间选择
        if not outline_rgb:
            outline_rgb = [0,0,0] if get_color_luminance(primary_rgb) > 0.5 else [255,255,255]

        return (rgb_to_hex(primary_rgb), rgb_to_hex(secondary_rgb), rgb_to_hex(outline_rgb))

    except Exception as e:
        print(f"提取颜色时发生错误: {e}")
        return ("#FFFFFF", "#DDDDDD", "#000000")